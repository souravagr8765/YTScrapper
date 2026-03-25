"""
Downloader — wraps yt-dlp to fetch playlist metadata and download individual videos.

Download format is chosen for maximum storage efficiency:
  HEVC/H.265 video (up to 1080p) + best audio → merged into .mkv or .mp4
  This is ~40-50% smaller than H.264 at the same visual quality.

The downloader reports back uncompressed_size_bytes (from yt-dlp's
filesize_approx metadata field) and compressed_size_bytes (the actual
file size on disk after download).
"""
import logging
import os
from pathlib import Path
from typing import List, Optional, Callable

import yt_dlp

from database.models import Video

logger = logging.getLogger(__name__)


def _make_progress_hook(on_progress: Optional[Callable] = None):
    def hook(d):
        if d["status"] == "downloading" and on_progress:
            downloaded = d.get("downloaded_bytes", 0)
            total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
            if total:
                pct = downloaded / total * 100
                on_progress(pct, downloaded, total)
        elif d["status"] == "finished":
            logger.debug("Download finished: %s", d.get("filename"))
    return hook


class Downloader:
    def __init__(self, output_folder: str, yt_dlp_format: str):
        self.output_folder = Path(output_folder)
        self.output_folder.mkdir(parents=True, exist_ok=True)
        self.yt_dlp_format = yt_dlp_format

    def fetch_playlist_videos(self, playlist_url: str) -> List[Video]:
        """
        Extract all video metadata from a playlist WITHOUT downloading.
        Returns a list of Video objects with status=PENDING.
        """
        logger.info("Fetching playlist metadata: %s", playlist_url)
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",  # No download, just metadata
            "ignoreerrors": True,
        }
        videos: List[Video] = []
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(playlist_url, download=False)
            if not info or "entries" not in info:
                logger.warning("Could not extract playlist info from %s", playlist_url)
                return []
            playlist_id = info.get("id", playlist_url)
            for entry in info.get("entries", []):
                if not entry:
                    continue
                videos.append(Video(
                    video_id=entry.get("id", ""),
                    playlist_id=playlist_id,
                    title=entry.get("title", ""),
                    channel_name=entry.get("uploader", entry.get("channel", "")),
                    duration_sec=int(entry.get("duration") or 0),
                    status="PENDING",
                    uncompressed_size_bytes=entry.get("filesize_approx"),
                ))
        logger.info("Found %d videos in playlist.", len(videos))
        return videos

    def download(
        self,
        video: Video,
        on_progress: Optional[Callable] = None,
    ) -> Optional[Path]:
        """
        Download a single video. Returns the path to the downloaded file,
        or None if the download failed.
        """
        video_url = f"https://www.youtube.com/watch?v={video.video_id}"
        out_template = str(self.output_folder / "%(id)s.%(ext)s")

        ydl_opts = {
            "format": self.yt_dlp_format,
            "outtmpl": out_template,
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": False,
            "merge_output_format": "mkv",   # mkv is universally compatible
            "postprocessors": [],
            "progress_hooks": [_make_progress_hook(on_progress)],
            # Write thumbnail as well (optional metadata)
            "writethumbnail": False,
        }

        logger.info("Downloading: [%s] %s", video.video_id, video.title)
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=True)
                if info is None:
                    raise RuntimeError("yt-dlp returned None for video info.")
                # Resolve the actual output filename
                filename = ydl.prepare_filename(info)
                # yt-dlp may change extension (e.g. .webm → .mkv) — check both
                file_path = Path(filename)
                # Try the prepared filename and common variants
                candidates = [
                    file_path,
                    file_path.with_suffix(".mkv"),
                    file_path.with_suffix(".mp4"),
                    file_path.with_suffix(".webm"),
                ]
                found = next((p for p in candidates if p.exists()), None)
                if not found:
                    # Fallback: scan output folder for file with matching video_id
                    matches = list(self.output_folder.glob(f"{video.video_id}.*"))
                    found = matches[0] if matches else None

                if not found:
                    raise FileNotFoundError(
                        f"Downloaded file for {video.video_id} could not be located."
                    )

                video.compressed_size_bytes = found.stat().st_size
                logger.info(
                    "Downloaded %s → %s (%.1f MB)",
                    video.video_id, found.name, found.stat().st_size / 1_048_576
                )
                return found

        except Exception as exc:
            logger.error("Download failed for %s: %s", video.video_id, exc)
            return None
