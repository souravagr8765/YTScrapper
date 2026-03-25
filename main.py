"""
YTScrapper — Main Entry Point

Workflow:
  1. Load configuration
  2. Initialize all three DB backends
  3. Seed local DB with rclone remote configs from config.yaml
  4. Run reconciler to sync state across all DBs
  5. For each playlist:
     a. Fetch playlist metadata
     b. Register new videos in all DBs
     c. Download each pending video
     d. Route to storage (local or rclone)
     e. Update video status in all DBs
"""
import logging
import sys
from pathlib import Path
from typing import List, Optional

# ---- Logging setup (before any imports that log) ----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("ytpl_sync.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("ytpl_sync.main")

from config_manager import load_config, AppConfig
from database.local_db import LocalDB
from database.neon_backend import NeonBackend
from database.nhost_backend import NhostBackend
from database.reconciler import Reconciler
from database.models import Video, RcloneRemote
from scraper.downloader import Downloader
from scraper.encoder import Encoder
from storage.router import route_file


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _upsert_all(video: Video, local_db: LocalDB, remotes: list):
    """Write a video record to every available backend."""
    local_db.upsert_video(video)
    for remote in remotes:
        remote.upsert_video(video)  # Silently swallows failures internally


def _init_remote_backends(config: AppConfig) -> list:
    """
    Create Neon and/or Nhost backend objects.

    Each backend is skipped when:
      - Its `enabled` flag is False in config.yaml  → INFO (intentional)
      - Its DSN env-var is missing                  → WARNING (misconfiguration)
      - Connection fails at runtime                 → WARNING (transient error)
    """
    backends = []

    # --- Neon ---
    if not config.neon_enabled:
        logger.info("Neon backend disabled in config.yaml — skipping.")
    elif not config.neon_dsn:
        logger.warning("Neon enabled but NEON_DATABASE_URL is not set — skipping.")
    else:
        try:
            neon = NeonBackend(dsn=config.neon_dsn)
            backends.append(neon)
            logger.info("Neon backend connected.")
        except Exception as exc:
            logger.warning("Neon backend unavailable: %s", exc)

    # --- Nhost ---
    if not config.nhost_enabled:
        logger.info("Nhost backend disabled in config.yaml — skipping.")
    elif not config.nhost_dsn:
        logger.warning("Nhost enabled but NHOST_DATABASE_URL is not set — skipping.")
    else:
        try:
            nhost = NhostBackend(dsn=config.nhost_dsn)
            backends.append(nhost)
            logger.info("Nhost backend connected.")
        except Exception as exc:
            logger.warning("Nhost backend unavailable: %s", exc)

    return backends


def _seed_remotes(config: AppConfig, local_db: LocalDB):
    """
    Ensure rclone_remotes from config.yaml are registered in the local DB.
    Existing entries are preserved (we don't overwrite live space data).
    """
    existing = {r.remote_name for r in local_db.get_remotes()}
    for rc in config.rclone_remotes:
        if rc.name not in existing:
            local_db.upsert_remote(RcloneRemote(
                remote_name=rc.name,
                target_path=rc.target_path,
            ))
            logger.info("Registered new rclone remote: %s → %s", rc.name, rc.target_path)


def _print_progress(pct: float, downloaded: int, total: int):
    bar_len = 40
    filled = int(bar_len * pct / 100)
    bar = "█" * filled + "░" * (bar_len - filled)
    mb_done = downloaded / 1_048_576
    mb_total = total / 1_048_576
    print(
        f"\r  [{bar}] {pct:5.1f}%  {mb_done:.1f}/{mb_total:.1f} MB",
        end="", flush=True
    )


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run():
    logger.info("=" * 60)
    logger.info("YTScrapper starting")
    logger.info("=" * 60)

    # 1. Load configuration
    try:
        config = load_config("config.yaml")
    except Exception as exc:
        logger.critical("Failed to load configuration: %s", exc)
        sys.exit(1)

    if not config.playlists:
        logger.error("No playlists configured in config.yaml. Exiting.")
        sys.exit(1)

    logger.info("Storage mode: %s", config.storage_mode.upper())
    logger.info("Playlists to process: %d", len(config.playlists))

    # 2. Initialize databases
    local_db = LocalDB(db_path=config.local_db_path)
    remote_backends = _init_remote_backends(config)

    # 3. Seed rclone remotes into local DB (first-run setup)
    if config.storage_mode.lower() == "rclone":
        _seed_remotes(config, local_db)

    # 4. Reconcile: sync state across all backends before processing
    if remote_backends:
        reconciler = Reconciler(local=local_db, remotes=remote_backends)
        reconciler.run()
    else:
        logger.warning("No remote backends available — running in local-only mode.")

    # 5. Initialize downloader and (optionally) encoder
    downloader = Downloader(
        output_folder=config.output_folder,
        yt_dlp_format=config.yt_dlp_format,
    )

    encoder: Encoder | None = None
    if config.encode.enabled:
        encoder = Encoder(
            ffmpeg_path=config.encode.ffmpeg_path,
            codec=config.encode.codec,
            crf=config.encode.crf,
            preset=config.encode.preset,
        )
        logger.info(
            "FFmpeg encoding enabled: %s, CRF=%d, preset=%s",
            config.encode.codec.upper(), config.encode.crf, config.encode.preset,
        )
    else:
        logger.info("FFmpeg encoding disabled.")

    # 6. Process each playlist
    total_downloaded = 0
    total_skipped = 0
    total_failed = 0

    for playlist_url in config.playlists:
        logger.info("Processing playlist: %s", playlist_url)

        # Fetch metadata (no download yet)
        playlist_videos: List[Video] = downloader.fetch_playlist_videos(playlist_url)
        if not playlist_videos:
            logger.warning("No videos found in playlist: %s", playlist_url)
            continue

        for video in playlist_videos:
            # Check if already processed (in local DB)
            existing = local_db.get_video(video.video_id)
            if existing and existing.status == "COMPLETED":
                logger.debug("Skipping [%s] %s — already COMPLETED.", video.video_id, video.title)
                total_skipped += 1
                continue
            if existing and existing.status in ("DOWNLOADING", "UPLOADING"):
                logger.info(
                    "Resuming [%s] %s from status %s.",
                    video.video_id, video.title, existing.status
                )
                video = existing  # Use the existing record to preserve state

            # Register PENDING video so all backends know about it
            video.status = "PENDING"
            _upsert_all(video, local_db, remote_backends)

            # --- Download ---
            video.status = "DOWNLOADING"
            _upsert_all(video, local_db, remote_backends)

            print(f"\n>> [{video.video_id}] {video.title}")
            file_path: Optional[Path] = downloader.download(video, on_progress=_print_progress)
            print()  # Newline after progress bar

            if file_path is None:
                video.status = "FAILED"
                _upsert_all(video, local_db, remote_backends)
                total_failed += 1
                logger.error("Download failed: [%s] %s", video.video_id, video.title)
                continue

            video.status = "DOWNLOADED"
            # Record actual raw download size BEFORE any re-encoding
            video.uncompressed_size_bytes = file_path.stat().st_size if file_path.exists() else 0
            _upsert_all(video, local_db, remote_backends)

            # --- Optional FFmpeg H.265 encoding ---
            if encoder is not None:
                video.status = "ENCODING"
                _upsert_all(video, local_db, remote_backends)
                try:
                    file_path = encoder.compress(file_path)
                    video.compressed_size_bytes = file_path.stat().st_size
                    logger.info(
                        "Encoded [%s] %s → %.1f MB (was %.1f MB)",
                        video.video_id, video.title,
                        video.compressed_size_bytes / 1_048_576,
                        video.uncompressed_size_bytes / 1_048_576,
                    )
                except Exception as enc_exc:
                    logger.error(
                        "Encoding failed for [%s] %s: %s",
                        video.video_id, video.title, enc_exc,
                    )
                    video.status = "FAILED"
                    _upsert_all(video, local_db, remote_backends)
                    total_failed += 1
                    continue
            else:
                # No encoding — compressed size equals raw download size
                video.compressed_size_bytes = video.uncompressed_size_bytes

            # --- Storage routing ---
            video.status = "UPLOADING"
            _upsert_all(video, local_db, remote_backends)

            file_size = file_path.stat().st_size if file_path.exists() else 0
            video.compressed_size_bytes = file_size

            storage_backend, dest_info = route_file(
                file_path=file_path,
                file_size_bytes=file_size,
                config=config,
                local_db=local_db,
            )

            if dest_info is None:
                video.status = "FAILED"
                _upsert_all(video, local_db, remote_backends)
                total_failed += 1
                logger.error(
                    "Storage failed for [%s] %s (backend=%s).",
                    video.video_id, video.title, storage_backend
                )
                continue

            video.status = "COMPLETED"
            video.storage_backend = storage_backend
            if storage_backend == "RCLONE":
                video.rclone_remote = dest_info
                video.file_path = dest_info  # remote name as identifier
            else:
                video.file_path = dest_info

            _upsert_all(video, local_db, remote_backends)
            total_downloaded += 1
            logger.info(
                "✓ COMPLETED [%s] %s → %s (%s)",
                video.video_id, video.title, dest_info, storage_backend
            )

    # 7. Final reconciliation to push any local-only updates to remote backends
    if remote_backends:
        logger.info("Running final reconciliation to push completed records to remotes...")
        reconciler.run()

    # 8. Summary
    logger.info("=" * 60)
    logger.info(
        "Done. Downloaded: %d | Skipped: %d | Failed: %d",
        total_downloaded, total_skipped, total_failed
    )
    logger.info("=" * 60)

    # 9. Clean up DB connections
    for backend in remote_backends:
        try:
            backend.close()
        except Exception:
            pass


if __name__ == "__main__":
    run()
