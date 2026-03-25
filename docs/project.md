# YTScrapper (ytpl-sync)

## Project Overview
YTScrapper is an automated application designed to scrape videos from YouTube playlists using `yt-dlp` and upload them to either local storage or multiple cloud remotes using **Rclone** (e.g., Google Drive accounts). The project is built to handle space constraints by seamlessly moving to the next available Rclone remote once a remote's storage is full.

To ensure reliability, fault tolerance, and cost efficiency, the application state is tracked across three database layers: 
1. **Local SQLite Database**: The fast, local source of truth.
2. **Neon (PostgreSQL)**: The primary remote resilient database.
3. **Nhost (PostgreSQL)**: A redundant secondary remote database.

The local database pulls the latest state from the remote ones on start up (reconciliation) so it can resume partial downloads or uploads even if one service goes offline, ensuring we don't exceed bandwidth or credit limits of our providers.

## System Architecture

The application is broken down into the following modules connecting together:

- **`main.py`**: The entry point. Coordinates initialization, syncs the DBs, and starts the scraper pipeline.
- **`config_manager.py`**: Reads `config.yaml` and `.env` files to load all credentials and user preferences.
- **`database/`**:
  - `local_db.py`: SQLite operations.
  - `neon_backend.py`: Neon PostgreSQL connection via SQLAlchemy or `psycopg2`.
  - `nhost_backend.py`: Nhost PostgreSQL connection.
  - `reconciler.py`: Syncs Local, Neon, and Nhost databases efficiently at startup and during updates.
- **`scraper/`**:
  - `downloader.py`: Encapsulates `yt-dlp` logic to extract playlist metadata and download videos in an efficient format (e.g., `bestvideo[ext=mp4]+bestaudio[ext=m4a]/best`).
  - `encoder.py`: Wraps FFmpeg to re-encode a downloaded file to H.265/HEVC (libx265). Runs only when `encode.enabled: true` in `config.yaml`. Replaces the source file in-place and reports both raw and compressed sizes.
- **`storage/`**:
  - `router.py`: Decides if a file should go to Local Storage or be uploaded via Rclone based on `config.yaml`.
  - `rclone_upload.py`: Wraps Rclone commands. Checks quota on the active remote. If `Account A` is full, it switches to `Account B` and performs `rclone move`.
  - `local.py`: Handles moving files to a local directory.

## Database Schema

Both Remote and Local databases use the same simplified schema to avoid complexity:

### `videos` table
| Column | Type | Description |
| --- | --- | --- |
| `video_id` | `VARCHAR` (PK) | YouTube Video ID |
| `playlist_id` | `VARCHAR` | YouTube Playlist ID |
| `title` | `VARCHAR` | Video Title |
| `channel_name` | `VARCHAR` | YouTube Channel Name |
| `duration_sec` | `INT` | Video duration in seconds |
| `status` | `VARCHAR` | Current state (`PENDING`, `DOWNLOADING`, `DOWNLOADED`, `UPLOADING`, `COMPLETED`, `FAILED`) |
| `storage_backend` | `VARCHAR` | `LOCAL` or `RCLONE` |
| `rclone_remote` | `VARCHAR` | Nullable. The Rclone remote where it was uploaded. |
| `file_path` | `VARCHAR` | Nullable. Local path or Remote file path. |
| `uncompressed_size_bytes` | `BIGINT` | File size immediately after yt-dlp download (before FFmpeg). |
| `compressed_size_bytes` | `BIGINT` | File size after FFmpeg H.265 encoding; equals `uncompressed_size_bytes` when encoding is disabled. |
| `updated_at` | `TIMESTAMP` | Last updated timestamp, used heavily for reconciliation. |

### `rclone_remotes` table
| Column | Type | Description |
| --- | --- | --- |
| `remote_name` | `VARCHAR` (PK) | The Rclone remote name (e.g., `gdrive1:`) |
| `target_path` | `VARCHAR` | The folder path on the remote to upload to |
| `available_space`| `BIGINT` | Tracked available bytes; updated after each upload |
| `is_active` | `BOOLEAN` | If false, account is skipped (e.g. quota exceeded) |

## Environment Configuration
The `.env` file should contain secrets that shouldn't be in source control:

```env
# Neon Database
NEON_DATABASE_URL=postgresql://user:password@neon-host.com/dbname

# Nhost Database
NHOST_DATABASE_URL=postgresql://user:password@nhost-host.com/dbname
```

## Configuration Management
User preferences are stored in `config.yaml`:

```yaml
playlists:
  - "https://www.youtube.com/playlist?list=YOUR_PLAYLIST_ID"

download:
  # Efficient storage and good quality using yt-dlp format strings
  format: "bestvideo[vcodec^=hev][height<=1080]+bestaudio/bestvideo[vcodec^=avc][height<=1080]+bestaudio/bestvideo[height<=1080]+bestaudio/best"
  output_folder: "./downloads"

  # Optional: Netscape-format cookies file to bypass YouTube bot detection.
  # Export from your browser (e.g. via a browser extension like "Get cookies.txt")
  # and point this to the file. Set to null to disable.
  cookies_file: "./cookies.txt"

encode:
  # Set enabled: true to run FFmpeg H.265 compression after each download.
  enabled: true
  codec: "h265"        # libx265
  crf: 28              # 24 (high quality) – 30 (smaller file)
  preset: "medium"     # ultrafast → veryslow
  ffmpeg_path: "ffmpeg" # path to binary or just "ffmpeg" if on PATH

storage:
  # Can be "local" or "rclone"
  mode: "rclone"

rclone_remotes:
  - name: "gdrive_1"
    target_path: "gdrive_1:YT_Backups"
  - name: "gdrive_2"
    target_path: "gdrive_2:YT_Backups"

database:
  local_db_path: "./ytpl_sync.db"

  # Set enabled: false to skip a remote backend entirely.
  # Both disabled → local-only mode (no remote sync).
  neon:
    enabled: true   # Neon PostgreSQL — primary remote backend

  nhost:
    enabled: true   # Nhost PostgreSQL — secondary remote backend
```

## Code Workflow
1. **Request (Start)**: User runs `python main.py`.
2. **Configuration**: ConfigManager loads `config.yaml` and `.env`.
3. **DB Initialisation**: `_init_remote_backends()` checks each backend:
   - If `enabled: false` in config → skipped (INFO log, intentional).
   - If enabled but DSN env-var missing → skipped (WARNING, misconfiguration).
   - If connection fails → skipped (WARNING, transient error).
   - If neither Neon nor Nhost ends up active → local-only mode.
4. **Scraping**: `yt-dlp` extracts the playlist videos.
5. **Database Check**: For each scraped video, if `status == COMPLETED`, skip.
6. **Downloading**: `downloader.py` downloads the video to a temporary `output_folder`. Sets status to `DOWNLOADED`. Records `uncompressed_size_bytes`.
7. **Encoding** *(optional)*: If `encode.enabled: true`, `encoder.py` re-encodes the file with FFmpeg (libx265). Status transitions `DOWNLOADING → DOWNLOADED → ENCODING → UPLOADING`. On success, `compressed_size_bytes` is updated. On failure, status is set to `FAILED` and the video is skipped.
8. **Storage Routing**: 
   - If `mode == local`: moves video to final destination. Updates DB to `COMPLETED`.
   - If `mode == rclone`: `router` gets the current active remote. If file size > `available_space` (checked via `rclone about`), marks remote as inactive and tries the next. Uploads video via Rclone and updates DB.
9. **Reconciliation**: State changes sync to Local, Neon, and Nhost.
10. **Cleanup**: Removes temporary downloaded file if uploaded via Rclone.
