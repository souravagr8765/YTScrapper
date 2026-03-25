"""
Rclone Upload — wraps Rclone CLI to upload files to configured cloud remotes.

Features:
  - Checks available quota on a remote before uploading (rclone about)
  - Automatically rotates to the next remote if the current one is full
  - Updates the local DB with the chosen remote's available space after upload
  - Uses `rclone moveto` so local temp files are cleaned up automatically
"""
import json
import logging
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from database.local_db import LocalDB
from database.models import RcloneRemote

logger = logging.getLogger(__name__)


def _run_rclone(args: List[str], timeout: int = 600) -> Tuple[int, str, str]:
    """Run an rclone command. Returns (returncode, stdout, stderr)."""
    cmd = ["rclone"] + args
    logger.debug("Running: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.returncode, result.stdout, result.stderr


def get_remote_free_space(remote_name: str) -> Optional[int]:
    """
    Query free space on a remote via `rclone about --json`.
    Returns bytes free, or None if the query failed or rclone doesn't support it.
    """
    try:
        rc, stdout, stderr = _run_rclone(["about", remote_name + ":", "--json"], timeout=30)
        if rc != 0:
            logger.warning("rclone about failed for %s: %s", remote_name, stderr.strip())
            return None
        data = json.loads(stdout)
        # 'free' key is available for most remotes that support quota
        return data.get("free")
    except Exception as exc:
        logger.warning("Could not query rclone quota for %s: %s", remote_name, exc)
        return None


class RcloneUploader:
    def __init__(self, remotes: List[RcloneRemote], local_db: LocalDB):
        """
        Args:
            remotes: Ordered list of RcloneRemote configs from the DB.
            local_db: LocalDB reference to track remote space state.
        """
        self.remotes = remotes
        self.local_db = local_db

    def upload(self, file_path: Path, file_size_bytes: int) -> Optional[str]:
        """
        Upload a file to the first remote with sufficient space.

        Returns the remote_name where the file was uploaded, or None on failure.
        The source file is moved (deleted after successful upload).
        """
        for remote in self.remotes:
            if not remote.is_active:
                logger.info("Skipping inactive remote: %s", remote.remote_name)
                continue

            # 1. Refresh quota from Rclone
            free = get_remote_free_space(remote.remote_name)
            if free is not None:
                remote.available_space = free
                self.local_db.update_remote_space(
                    remote.remote_name, available_space=free, is_active=True
                )

            if remote.available_space is not None and remote.available_space < file_size_bytes:
                logger.warning(
                    "Remote %s has %.1f GB free — not enough for %.1f MB file. Trying next.",
                    remote.remote_name,
                    remote.available_space / 1_073_741_824,
                    file_size_bytes / 1_048_576,
                )
                self.local_db.update_remote_space(
                    remote.remote_name,
                    available_space=remote.available_space,
                    is_active=False,
                )
                remote.is_active = False
                continue

            # 2. Upload via rclone moveto (moves and deletes source on success)
            dest = f"{remote.target_path}/{file_path.name}"
            logger.info("Uploading %s → %s", file_path.name, dest)
            rc, _, stderr = _run_rclone(
                ["moveto", str(file_path), dest, "--progress"],
                timeout=3600,
            )

            if rc == 0:
                logger.info("Successfully uploaded %s to %s", file_path.name, remote.remote_name)
                # Deduct file size from tracked space
                if remote.available_space is not None:
                    new_space = max(0, remote.available_space - file_size_bytes)
                    self.local_db.update_remote_space(
                        remote.remote_name, available_space=new_space, is_active=True
                    )
                return remote.remote_name
            else:
                logger.error(
                    "rclone moveto failed for %s on remote %s: %s",
                    file_path.name, remote.remote_name, stderr.strip()
                )

        logger.error("All Rclone remotes exhausted or failed. File NOT uploaded: %s", file_path)
        return None
