"""
Nhost PostgreSQL backend (secondary/redundant remote database).

The interface is intentionally identical to NeonBackend so the reconciler
can treat both polymorphically.
"""
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import List, Optional

import psycopg2
import psycopg2.pool
from psycopg2.extras import RealDictCursor

from database.models import Video

logger = logging.getLogger(__name__)

_CREATE_VIDEOS_SQL = """
CREATE TABLE IF NOT EXISTS videos (
    video_id                VARCHAR PRIMARY KEY,
    playlist_id             VARCHAR NOT NULL,
    title                   VARCHAR NOT NULL,
    channel_name            VARCHAR,
    duration_sec            INT DEFAULT 0,
    status                  VARCHAR NOT NULL DEFAULT 'PENDING',
    storage_backend         VARCHAR,
    rclone_remote           VARCHAR,
    file_path               VARCHAR,
    uncompressed_size_bytes BIGINT,
    compressed_size_bytes   BIGINT,
    updated_at              TIMESTAMPTZ NOT NULL
);
"""


class NhostBackend:
    def __init__(self, dsn: str):
        if not dsn:
            raise ValueError("NHOST_DATABASE_URL is not set — Nhost backend disabled.")
        self._pool = psycopg2.pool.ThreadedConnectionPool(1, 3, dsn=dsn)
        self._init_tables()

    @contextmanager
    def _get_conn(self):
        conn = self._pool.getconn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)

    def _init_tables(self):
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(_CREATE_VIDEOS_SQL)

    def upsert_video(self, video: Video) -> bool:
        try:
            video.updated_at = datetime.now(timezone.utc)
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO videos (
                            video_id, playlist_id, title, channel_name, duration_sec,
                            status, storage_backend, rclone_remote, file_path,
                            uncompressed_size_bytes, compressed_size_bytes, updated_at
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (video_id) DO UPDATE SET
                            playlist_id             = EXCLUDED.playlist_id,
                            title                   = EXCLUDED.title,
                            channel_name            = EXCLUDED.channel_name,
                            duration_sec            = EXCLUDED.duration_sec,
                            status                  = EXCLUDED.status,
                            storage_backend         = EXCLUDED.storage_backend,
                            rclone_remote           = EXCLUDED.rclone_remote,
                            file_path               = EXCLUDED.file_path,
                            uncompressed_size_bytes = EXCLUDED.uncompressed_size_bytes,
                            compressed_size_bytes   = EXCLUDED.compressed_size_bytes,
                            updated_at              = EXCLUDED.updated_at
                    """, (
                        video.video_id, video.playlist_id, video.title, video.channel_name,
                        video.duration_sec, video.status, video.storage_backend,
                        video.rclone_remote, video.file_path,
                        video.uncompressed_size_bytes, video.compressed_size_bytes,
                        video.updated_at,
                    ))
            return True
        except Exception as exc:
            logger.warning("Nhost upsert failed: %s", exc)
            return False

    def get_videos_since(self, since: datetime) -> List[Video]:
        try:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        "SELECT * FROM videos WHERE updated_at > %s ORDER BY updated_at ASC",
                        (since,)
                    )
                    return [Video.from_dict(dict(r)) for r in cur.fetchall()]
        except Exception as exc:
            logger.warning("Nhost get_videos_since failed: %s", exc)
            return []

    def get_all_videos(self) -> List[Video]:
        try:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("SELECT * FROM videos ORDER BY updated_at ASC")
                    return [Video.from_dict(dict(r)) for r in cur.fetchall()]
        except Exception as exc:
            logger.warning("Nhost get_all_videos failed: %s", exc)
            return []

    def get_max_updated_at(self) -> Optional[datetime]:
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT MAX(updated_at) FROM videos")
                    row = cur.fetchone()
                    return row[0] if row and row[0] else None
        except Exception as exc:
            logger.warning("Nhost get_max_updated_at failed: %s", exc)
            return None

    def is_available(self) -> bool:
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
            return True
        except Exception:
            return False

    def close(self):
        self._pool.closeall()
