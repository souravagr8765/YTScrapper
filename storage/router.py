"""
Storage Router — dispatches to the correct storage backend based on config.

Keeps main.py clean by centralizing the "where do I put this file?" decision.
"""
import logging
from pathlib import Path
from typing import Optional, Tuple

from config_manager import AppConfig
from database.local_db import LocalDB
from database.models import RcloneRemote
from storage.local import move_to_local
from storage.rclone_upload import RcloneUploader

logger = logging.getLogger(__name__)


def route_file(
    file_path: Path,
    file_size_bytes: int,
    config: AppConfig,
    local_db: LocalDB,
) -> Tuple[str, Optional[str]]:
    """
    Route a downloaded file to its final storage destination.

    Returns:
        (storage_backend, destination_info) where:
          - storage_backend is "LOCAL" or "RCLONE"
          - destination_info is the local path string or rclone remote name
            (None if storage failed)
    """
    mode = config.storage_mode.lower()

    if mode == "local":
        dest = move_to_local(file_path, config.local_destination)
        return ("LOCAL", str(dest) if dest else None)

    elif mode == "rclone":
        # Load the ordered remotes from local DB (includes live space data)
        db_remotes = local_db.get_remotes()
        # Fall back to config remotes if DB has none yet (first run)
        if not db_remotes:
            db_remotes = [
                RcloneRemote(
                    remote_name=r.name,
                    target_path=r.target_path,
                )
                for r in config.rclone_remotes
            ]

        uploader = RcloneUploader(remotes=db_remotes, local_db=local_db)
        remote_name = uploader.upload(file_path, file_size_bytes)
        return ("RCLONE", remote_name)

    else:
        logger.error("Unknown storage mode: '%s'. File left in: %s", mode, file_path)
        return (mode.upper(), None)
