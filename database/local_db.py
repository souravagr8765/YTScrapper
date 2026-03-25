"""
Local SQLite database backend.

This is the fast, always-available source of truth that runs locally.
All three table schemas mirror the remote PostgreSQL schemas exactly.
"""
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import List, Optional

from database.models import Video, RcloneRemote

# Thread-local storage means each thread gets its own connection.
# This avoids "SQLite objects created in a thread can only be used in that thread" errors.
_local = threading.local()


class LocalDB:
    def __init__(self, db_path: str):
        self.db_path = db_path
        # Create tables when the object is instantiated
        self._init_tables()

    @contextmanager
    def _get_conn(self):
        """Provides a SQLite connection with row_factory set to dict-like access."""
        if not hasattr(_local, "conn") or _local.conn is None:
            _local.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            _local.conn.row_factory = sqlite3.Row
            _local.conn.execute("PRAGMA journal_mode=WAL")  # Better concurrent read perf
        try:
            yield _local.conn
        except Exception:
            _local.conn.rollback()
            raise

    def _init_tables(self):
        """Create tables if they do not yet exist."""
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS videos (
                    video_id                TEXT PRIMARY KEY,
                    playlist_id             TEXT NOT NULL,
                    title                   TEXT NOT NULL,
                    channel_name            TEXT,
                    duration_sec            INTEGER DEFAULT 0,
                    status                  TEXT NOT NULL DEFAULT 'PENDING',
                    storage_backend         TEXT,
                    rclone_remote           TEXT,
                    file_path               TEXT,
                    uncompressed_size_bytes INTEGER,
                    compressed_size_bytes   INTEGER,
                    updated_at              TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS rclone_remotes (
                    remote_name     TEXT PRIMARY KEY,
                    target_path     TEXT NOT NULL,
                    available_space INTEGER,
                    is_active       INTEGER NOT NULL DEFAULT 1
                );
            """)
            conn.commit()

    # -------------------------------------------------------------------------
    # Video operations
    # -------------------------------------------------------------------------

    def upsert_video(self, video: Video):
        """Insert or update a video record. updated_at is always refreshed."""
        video.updated_at = datetime.now(timezone.utc)
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO videos (
                    video_id, playlist_id, title, channel_name, duration_sec,
                    status, storage_backend, rclone_remote, file_path,
                    uncompressed_size_bytes, compressed_size_bytes, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(video_id) DO UPDATE SET
                    playlist_id             = excluded.playlist_id,
                    title                   = excluded.title,
                    channel_name            = excluded.channel_name,
                    duration_sec            = excluded.duration_sec,
                    status                  = excluded.status,
                    storage_backend         = excluded.storage_backend,
                    rclone_remote           = excluded.rclone_remote,
                    file_path               = excluded.file_path,
                    uncompressed_size_bytes = excluded.uncompressed_size_bytes,
                    compressed_size_bytes   = excluded.compressed_size_bytes,
                    updated_at              = excluded.updated_at
            """, (
                video.video_id, video.playlist_id, video.title, video.channel_name,
                video.duration_sec, video.status, video.storage_backend,
                video.rclone_remote, video.file_path,
                video.uncompressed_size_bytes, video.compressed_size_bytes,
                video.updated_at.isoformat(),
            ))
            conn.commit()

    def get_video(self, video_id: str) -> Optional[Video]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM videos WHERE video_id = ?", (video_id,)
            ).fetchone()
            return self._row_to_video(row) if row else None

    def get_videos_since(self, since: datetime) -> List[Video]:
        """Return all video records updated after `since` (exclusive).
        Used for delta-sync during reconciliation."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM videos WHERE updated_at > ? ORDER BY updated_at ASC",
                (since.isoformat(),)
            ).fetchall()
            return [self._row_to_video(r) for r in rows]

    def get_all_videos(self) -> List[Video]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM videos ORDER BY updated_at ASC").fetchall()
            return [self._row_to_video(r) for r in rows]

    def get_max_updated_at(self) -> Optional[datetime]:
        """High-water mark – the newest updated_at timestamp in the local DB."""
        with self._get_conn() as conn:
            row = conn.execute("SELECT MAX(updated_at) AS m FROM videos").fetchone()
            if row and row["m"]:
                return datetime.fromisoformat(row["m"])
            return None

    def count_videos(self) -> int:
        with self._get_conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]

    @staticmethod
    def _row_to_video(row) -> Video:
        d = dict(row)
        return Video.from_dict(d)

    # -------------------------------------------------------------------------
    # RcloneRemote operations
    # -------------------------------------------------------------------------

    def upsert_remote(self, remote: RcloneRemote):
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO rclone_remotes (remote_name, target_path, available_space, is_active)
                VALUES (?,?,?,?)
                ON CONFLICT(remote_name) DO UPDATE SET
                    target_path     = excluded.target_path,
                    available_space = excluded.available_space,
                    is_active       = excluded.is_active
            """, (
                remote.remote_name, remote.target_path,
                remote.available_space, 1 if remote.is_active else 0,
            ))
            conn.commit()

    def get_remotes(self) -> List[RcloneRemote]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM rclone_remotes ORDER BY remote_name").fetchall()
            return [
                RcloneRemote(
                    remote_name=r["remote_name"],
                    target_path=r["target_path"],
                    available_space=r["available_space"],
                    is_active=bool(r["is_active"]),
                )
                for r in rows
            ]

    def update_remote_space(self, remote_name: str, available_space: int, is_active: bool):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE rclone_remotes SET available_space=?, is_active=? WHERE remote_name=?",
                (available_space, 1 if is_active else 0, remote_name)
            )
            conn.commit()
