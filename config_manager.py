"""
Configuration Manager — loads config.yaml and .env into a single typed config object.
Creates default config.yaml and .env on first run if they don't exist.
"""
import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = Path(__file__).parent / "config.yaml"
_DEFAULT_ENV_PATH = Path(__file__).parent / ".env"
_ENV_EXAMPLE_PATH = Path(__file__).parent / ".env.example"


@dataclass
class RcloneRemoteConfig:
    name: str
    target_path: str


@dataclass
class EncodeConfig:
    enabled: bool = False
    codec: str = "h265"
    crf: int = 28
    preset: str = "medium"
    ffmpeg_path: str = "ffmpeg"


@dataclass
class AppConfig:
    # Playlists
    playlists: List[str]

    # Download settings
    yt_dlp_format: str
    output_folder: str

    # Encoding
    encode: EncodeConfig

    # Storage
    storage_mode: str          # "local" or "rclone"
    local_destination: str     # used if storage_mode == "local"

    # Rclone remotes (ordered, space-filled in sequence)
    rclone_remotes: List[RcloneRemoteConfig]

    # Database
    local_db_path: str

    # Remote DB — enabled flags (from config.yaml, default True)
    neon_enabled: bool
    nhost_enabled: bool

    # Remote DB credentials (from env)
    neon_dsn: Optional[str]
    nhost_dsn: Optional[str]


def load_config(config_path: str = "config.yaml") -> AppConfig:
    """
    Load configuration from config.yaml and .env.
    Creates defaults from templates if files are missing.
    """
    cfg_path = Path(config_path)

    # Auto-create config.yaml from template if missing
    if not cfg_path.exists():
        template = Path(__file__).parent / "config.yaml"
        if template.exists():
            shutil.copy(template, cfg_path)
            logger.warning(
                "config.yaml not found — created a default at '%s'. "
                "Please edit it before running.", cfg_path
            )
        else:
            raise FileNotFoundError(
                f"config.yaml not found at '{cfg_path}' and no template available."
            )

    # Auto-create .env from .env.example if missing
    env_path = cfg_path.parent / ".env"
    if not env_path.exists():
        example = cfg_path.parent / ".env.example"
        if example.exists():
            shutil.copy(example, env_path)
            logger.warning(
                ".env not found — created one from .env.example at '%s'. "
                "Please fill in your credentials.", env_path
            )

    load_dotenv(env_path)

    with open(cfg_path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    remotes = [
        RcloneRemoteConfig(
            name=r["name"],
            target_path=r["target_path"],
        )
        for r in (raw.get("rclone_remotes") or [])
    ]

    storage = raw.get("storage", {})
    dl = raw.get("download", {})
    db = raw.get("database", {})
    enc = raw.get("encode", {})

    # Per-backend enabled flags — default True so existing configs work unchanged
    neon_enabled = db.get("neon", {}).get("enabled", True)
    nhost_enabled = db.get("nhost", {}).get("enabled", True)

    encode_cfg = EncodeConfig(
        enabled=enc.get("enabled", False),
        codec=enc.get("codec", "h265"),
        crf=int(enc.get("crf", 28)),
        preset=enc.get("preset", "medium"),
        ffmpeg_path=enc.get("ffmpeg_path", "ffmpeg"),
    )

    return AppConfig(
        playlists=raw.get("playlists", []),
        yt_dlp_format=dl.get("format", "bestvideo[vcodec^=hev][height<=1080]+bestaudio/best[height<=1080]"),
        output_folder=dl.get("output_folder", "./downloads"),
        encode=encode_cfg,
        storage_mode=storage.get("mode", "local"),
        local_destination=storage.get("local_destination", "./output"),
        rclone_remotes=remotes,
        local_db_path=db.get("local_db_path", "./ytpl_sync.db"),
        neon_enabled=neon_enabled,
        nhost_enabled=nhost_enabled,
        neon_dsn=os.getenv("NEON_DATABASE_URL"),
        nhost_dsn=os.getenv("NHOST_DATABASE_URL"),
    )
