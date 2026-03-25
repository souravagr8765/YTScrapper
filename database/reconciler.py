"""
Reconciler — synchronizes Local SQLite, Neon, and Nhost databases.

Strategy:
  1. Collect the max updated_at from each active backend.
  2. Pull delta records (newer than local high-water) from the most up-to-date
     remote into local.
  3. Push local records that are newer than each remote's high-water mark back
     to those remotes.

This only ever reads/writes the *delta*, never the full table, to avoid
blowing through egress/credit limits on Neon and Nhost free tiers.
"""
import logging
from datetime import datetime, timezone
from typing import List, Optional

from database.local_db import LocalDB
from database.models import Video

logger = logging.getLogger(__name__)

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class Reconciler:
    def __init__(self, local: LocalDB, remotes: list):
        """
        Args:
            local: LocalDB instance
            remotes: list of (NeonBackend | NhostBackend) instances
        """
        self.local = local
        self.remotes = remotes

    def _get_highwater(self, backend) -> Optional[datetime]:
        """Safely get max updated_at from a backend. Returns EPOCH if None."""
        try:
            ts = backend.get_max_updated_at()
            return ts if ts else EPOCH
        except Exception as exc:
            logger.warning("Could not get high-water from %s: %s", type(backend).__name__, exc)
            return None  # None means the backend is unavailable

    def run(self):
        """
        Called at application startup. Performs bi-directional delta sync
        between local SQLite and all available remote backends.
        """
        logger.info("--- Starting reconciliation ---")

        local_hw = self._get_highwater(self.local) or EPOCH

        # --- Phase 1: Pull from remotes into local ---
        # Find the remote with the highest water mark (most up-to-date)
        best_remote = None
        best_remote_hw = EPOCH
        for remote in self.remotes:
            hw = self._get_highwater(remote)
            if hw is not None and hw > best_remote_hw:
                best_remote_hw = hw
                best_remote = remote

        if best_remote and best_remote_hw > local_hw:
            logger.info(
                "Remote (%s) is ahead by records newer than %s. Pulling delta...",
                type(best_remote).__name__, local_hw.isoformat()
            )
            delta: List[Video] = best_remote.get_videos_since(local_hw)
            logger.info("Pulling %d records from remote into local.", len(delta))
            for video in delta:
                self.local.upsert_video(video)
        else:
            logger.info("Local DB is up-to-date (or remotes unavailable). No pull needed.")

        # Refresh local HW after potential pull
        local_hw = self._get_highwater(self.local) or EPOCH

        # --- Phase 2: Push from local into each remote that is behind ---
        for remote in self.remotes:
            remote_hw = self._get_highwater(remote)
            if remote_hw is None:
                logger.warning("%s is unavailable. Skipping push.", type(remote).__name__)
                continue

            if local_hw > remote_hw:
                delta = self.local.get_videos_since(remote_hw)
                if delta:
                    logger.info(
                        "Pushing %d local records to %s (behind by records since %s).",
                        len(delta), type(remote).__name__, remote_hw.isoformat()
                    )
                    failed = 0
                    for video in delta:
                        if not remote.upsert_video(video):
                            failed += 1
                    if failed:
                        logger.warning(
                            "%d records failed to push to %s.",
                            failed, type(remote).__name__
                        )
                else:
                    logger.info("%s is already in sync.", type(remote).__name__)
            else:
                logger.info("%s is in sync with local.", type(remote).__name__)

        local_count = self.local.count_videos()
        logger.info("--- Reconciliation complete. Local: %d records. ---", local_count)
