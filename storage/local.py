"""
Local storage backend — simply moves the downloaded file to the configured
local destination folder.
"""
import logging
import shutil
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def move_to_local(file_path: Path, destination_folder: str) -> Optional[Path]:
    """
    Move `file_path` into `destination_folder`.
    Creates the destination directory if it does not exist.
    Returns the new Path on success, or None on failure.
    """
    dest_dir = Path(destination_folder)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / file_path.name
    try:
        shutil.move(str(file_path), str(dest_path))
        logger.info("Moved %s → %s", file_path.name, dest_path)
        return dest_path
    except Exception as exc:
        logger.error("Failed to move %s to %s: %s", file_path, destination_folder, exc)
        return None
