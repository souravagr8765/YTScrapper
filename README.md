# YTScrapper

A fault-tolerant YouTube playlist downloader that uses `yt-dlp` to download videos in a storage-efficient format, uploads them to configured Rclone remotes (e.g., Google Drive) with automatic account rotation, and tracks all state across three redundant databases (Local SQLite, Neon, Nhost) with smart delta-sync reconciliation.

## Requirements

- Python 3.9+
- [Rclone](https://rclone.org/downloads/) (installed and in PATH, configured with remote names)
- A Neon account (optional but recommended): [neon.tech](https://neon.tech)
- A Nhost account (optional but recommended): [nhost.run](https://nhost.run)

## Quick Start

### 1. Install dependencies

**Windows:**
```bat
setup.bat
```

**Linux/macOS/Termux:**
```bash
bash setup.sh
```

### 2. Configure

Edit `config.yaml` — add your playlist URL(s) and Rclone remote names:
```yaml
playlists:
  - "https://www.youtube.com/playlist?list=YOUR_PLAYLIST_ID"

rclone_remotes:
  - name: "gdrive_1"
    target_path: "gdrive_1:YT_Backups"
```

Copy `.env.example` → `.env` and fill in your database credentials:
```bash
cp .env.example .env
```

### 3. Run

```bash
python main.py
```

---

## Storage Modes

Set `storage.mode` in `config.yaml`:

| Mode | Description |
|------|-------------|
| `local` | Files are moved to `storage.local_destination` on disk |
| `rclone` | Files are uploaded via Rclone to configured remotes in order |

### Rclone Setup (for Google Drive)

1. Install Rclone: https://rclone.org/downloads/
2. Run `rclone config` and follow prompts to add a remote named `gdrive_1`
3. Use the same names in `config.yaml` under `rclone_remotes`

When `gdrive_1` is full, the app automatically switches to `gdrive_2`, etc.

---

## Database Redundancy

The app writes every state change to **three databases simultaneously**:

| Database | Type | Purpose |
|----------|------|---------|
| Local SQLite | `ytpl_sync.db` | Always-available local cache |
| Neon | PostgreSQL | Primary remote backup |
| Nhost | PostgreSQL | Secondary remote backup |

### Startup Reconciliation

On every run, the app compares `updated_at` high-water marks across all active databases and syncs only the **delta** (never the full table). This means:

- If one remote was offline, it's automatically backfilled when it comes back
- Egress and credit usage stays minimal
- You can run the app from multiple machines and states will merge correctly

---

## Video Format (Storage Efficiency)

The default yt-dlp format:
```
bestvideo[vcodec^=hev][height<=1080]+bestaudio/best[height<=1080]
```

This downloads **HEVC/H.265** encoded video (when available), which is \~40–50% smaller than H.264 at equivalent visual quality. No re-encoding — the downloaded stream is used as-is.

---

## Project Structure

```
.
├── main.py                  # Entry point
├── config_manager.py        # Config loader
├── config.yaml              # User configuration
├── .env                     # Secrets (not committed)
├── database/
│   ├── models.py            # Video & RcloneRemote dataclasses
│   ├── local_db.py          # SQLite backend
│   ├── neon_backend.py      # Neon PostgreSQL backend
│   ├── nhost_backend.py     # Nhost PostgreSQL backend
│   └── reconciler.py        # Delta-sync across all DBs
├── scraper/
│   └── downloader.py        # yt-dlp playlist fetcher & downloader
├── storage/
│   ├── rclone_upload.py     # Rclone CLI wrapper with remote rotation
│   ├── local.py             # Local file mover
│   └── router.py            # Dispatches to correct backend
└── docs/
    └── project.md           # Source of truth documentation
```

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `NEON_DATABASE_URL` | Neon PostgreSQL connection string |
| `NHOST_DATABASE_URL` | Nhost PostgreSQL connection string |

Both are optional — the app gracefully degrades to local-only if they are missing.
