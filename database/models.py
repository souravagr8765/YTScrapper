"""
Shared data models (dataclasses) for the entire application.
All database backends use these as the canonical representation of a record.
"""
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


@dataclass
class Video:
    video_id: str
    playlist_id: str
    title: str
    channel_name: str
    duration_sec: int
    status: str  # PENDING | DOWNLOADING | DOWNLOADED | UPLOADING | COMPLETED | FAILED
    storage_backend: Optional[str] = None   # LOCAL | RCLONE
    rclone_remote: Optional[str] = None
    file_path: Optional[str] = None
    uncompressed_size_bytes: Optional[int] = None
    compressed_size_bytes: Optional[int] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "video_id": self.video_id,
            "playlist_id": self.playlist_id,
            "title": self.title,
            "channel_name": self.channel_name,
            "duration_sec": self.duration_sec,
            "status": self.status,
            "storage_backend": self.storage_backend,
            "rclone_remote": self.rclone_remote,
            "file_path": self.file_path,
            "uncompressed_size_bytes": self.uncompressed_size_bytes,
            "compressed_size_bytes": self.compressed_size_bytes,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @staticmethod
    def from_dict(d: dict) -> "Video":
        updated_at = d.get("updated_at")
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)
        return Video(
            video_id=d["video_id"],
            playlist_id=d["playlist_id"],
            title=d["title"],
            channel_name=d.get("channel_name", ""),
            duration_sec=d.get("duration_sec", 0),
            status=d["status"],
            storage_backend=d.get("storage_backend"),
            rclone_remote=d.get("rclone_remote"),
            file_path=d.get("file_path"),
            uncompressed_size_bytes=d.get("uncompressed_size_bytes"),
            compressed_size_bytes=d.get("compressed_size_bytes"),
            updated_at=updated_at,
        )


@dataclass
class RcloneRemote:
    remote_name: str
    target_path: str
    available_space: Optional[int] = None
    is_active: bool = True
