"""
Encoder — post-download FFmpeg transcoding to H.265 / HEVC.

After yt-dlp has finished downloading a video, this module re-encodes
it with libx265 to produce a significantly smaller file (typically
30-50% smaller than the same resolution in H.264) at comparable quality.

Workflow:
  1. Record the original file size (uncompressed_size_bytes).
  2. Run: ffmpeg -i <input> -c:v libx265 -crf <crf> -preset <preset>
                 -c:a copy -y <output.tmp.mkv>
  3. On success: delete original, rename <output.tmp.mkv> → <input path>
  4. Return the final file path.
"""

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class Encoder:
    """Wraps FFmpeg to transcode a video file to H.265."""

    SUPPORTED_CODECS = {"h265": "libx265"}

    def __init__(
        self,
        ffmpeg_path: str = "ffmpeg",
        codec: str = "h265",
        crf: int = 28,
        preset: str = "medium",
    ):
        self.ffmpeg_path = ffmpeg_path
        self.codec = codec.lower()
        self.crf = crf
        self.preset = preset

        if self.codec not in self.SUPPORTED_CODECS:
            raise ValueError(
                f"Unsupported codec '{codec}'. Supported: {list(self.SUPPORTED_CODECS)}"
            )

    def compress(self, input_path: Path) -> Path:
        """
        Re-encode *input_path* to H.265 in-place.

        The original file is replaced by the compressed version.
        Returns the (same) path of the final file.

        Raises RuntimeError if FFmpeg exits with a non-zero code.
        """
        input_path = Path(input_path)
        if not input_path.exists():
            raise FileNotFoundError(f"Input file does not exist: {input_path}")

        uncompressed_size = input_path.stat().st_size
        lib_codec = self.SUPPORTED_CODECS[self.codec]

        # Write to a sibling temp file so we never corrupt the original on failure
        tmp_path = input_path.with_suffix(".h265_tmp.mkv")

        cmd = [
            self.ffmpeg_path,
            "-i", str(input_path),
            "-c:v", lib_codec,
            "-crf", str(self.crf),
            "-preset", self.preset,
            "-c:a", "copy",          # copy audio stream unchanged
            "-movflags", "+faststart",
            "-y",                    # overwrite tmp if it exists
            str(tmp_path),
        ]

        logger.info(
            "Encoding [%s] with FFmpeg (%s, CRF=%d, preset=%s) …",
            input_path.name, self.codec.upper(), self.crf, self.preset,
        )
        logger.debug("FFmpeg command: %s", " ".join(cmd))

        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except FileNotFoundError:
            raise RuntimeError(
                f"FFmpeg binary not found at '{self.ffmpeg_path}'. "
                "Install FFmpeg or set encode.ffmpeg_path in config.yaml."
            )

        if result.returncode != 0:
            # Clean up the failed temp file
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            # Surface the FFmpeg stderr so the user knows what went wrong
            logger.error("FFmpeg stderr:\n%s", result.stderr[-2000:])
            raise RuntimeError(
                f"FFmpeg failed (exit code {result.returncode}) for '{input_path.name}'. "
                "See log for details."
            )

        compressed_size = tmp_path.stat().st_size
        savings_pct = (1 - compressed_size / uncompressed_size) * 100 if uncompressed_size else 0

        # Replace original with compressed version
        input_path.unlink()
        tmp_path.rename(input_path)

        logger.info(
            "Encoded %s → %.1f MB → %.1f MB  (saved %.1f%%)",
            input_path.name,
            uncompressed_size / 1_048_576,
            compressed_size / 1_048_576,
            savings_pct,
        )

        return input_path
