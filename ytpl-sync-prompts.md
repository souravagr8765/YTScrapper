# ytpl-sync — Vibe Coder Prompts
> Feed these prompts **in order**, one at a time. Verify each module runs/imports cleanly before moving to the next.

---

## PROMPT 1 — Project scaffold, models, and config system

```
Create a Python project called `ytpl-sync`. Use Python 3.11+. Structure it as a proper installable package.

Directory layout:
  ytpl_sync/
    __init__.py              # version = "1.0.0"
    main.py
    config.py
    models.py
    run_context.py
    lock.py
    utils/
      __init__.py
      disk.py
      time_window.py
      cleanup.py
      ytdlp_check.py
      subprocess_runner.py
    db/
      __init__.py
      manager.py
      sqlite_backend.py
      neon_backend.py
      reconciler.py
    sources/
      __init__.py
      resolver.py
      playlist.py
      channel.py
    downloader.py
    encoder.py
    storage/
      __init__.py
      router.py
      local_storage.py
      gdrive_storage.py
    notifications/
      __init__.py
      mailer.py
      telegram.py
      reporter.py
  config.yaml               # fully commented example config
  .env.example              # all required env vars with comments
  .gitignore                # include .env, *.db, *.lock, __pycache__, .venv
  requirements.txt
  pyproject.toml            # entry point: ytpl-sync = ytpl_sync.main:cli
  VERSION                   # contains string "1.0.0"
  README.md

--- models.py ---

Use Python dataclasses and enums. Define:

VideoStatus enum (str):
  PENDING, DOWNLOADING, DOWNLOADED, ENCODING, ENCODED, UPLOADING, UPLOADED, FAILED, ABANDONED, DELETED

FailedStage enum (str):
  DOWNLOAD, ENCODE, UPLOAD

SourceType enum (str):
  PLAYLIST, CHANNEL

Video dataclass with ALL these fields:
  video_id: str
  source_name: str
  source_type: str
  source_url: str
  run_id: str

  # YouTube metadata
  title: Optional[str]
  description: Optional[str]
  channel_name: Optional[str]
  channel_id: Optional[str]
  upload_date: Optional[str]          # YYYY-MM-DD
  duration_seconds: Optional[int]
  view_count: Optional[int]
  like_count: Optional[int]
  thumbnail_url: Optional[str]
  tags: Optional[list[str]]
  categories: Optional[list[str]]
  youtube_url: Optional[str]

  # Status & resume
  status: str = VideoStatus.PENDING
  failed_stage: Optional[str] = None
  failed_reason: Optional[str] = None
  retry_count: int = 0

  # Deletion
  deleted: bool = False
  deleted_detected_at: Optional[str] = None

  # File info
  original_filename: Optional[str] = None
  original_size_bytes: Optional[int] = None
  final_filename: Optional[str] = None
  final_size_bytes: Optional[int] = None
  encoding_savings_pct: Optional[float] = None

  # Paths
  temp_path: Optional[str] = None
  local_path: Optional[str] = None

  # Drive info
  rclone_remote: Optional[str] = None
  rclone_path: Optional[str] = None

  # Timestamps (ISO strings)
  discovered_at: Optional[str] = None
  download_started_at: Optional[str] = None
  downloaded_at: Optional[str] = None
  encode_started_at: Optional[str] = None
  encoded_at: Optional[str] = None
  upload_started_at: Optional[str] = None
  uploaded_at: Optional[str] = None
  updated_at: Optional[str] = None

  # Sync flag
  pending_neon_sync: bool = False

--- config.py ---

Use pydantic v2. Define nested models matching this exact config.yaml structure:

```yaml
settings:
  ffmpeg_path: null           # null = auto-detect from PATH
  rclone_path: null
  temp_dir: null              # null = system temp
  lock_file: "~/.ytpl-sync.lock"
  log_file: "~/.ytpl-sync.log"
  min_free_gb: 5
  only_run_between: null      # "HH:MM-HH:MM" or null
  ytdlp_auto_update: false
  cookies_file: null
  max_retries: 3
  dry_run: false

encoding:
  enabled: true
  encoder: "software"         # software | nvenc | vaapi | videotoolbox
  preset: "medium"
  crf: 28
  audio_bitrate: "96k"

quality:
  max_resolution: 1080        # 480 | 720 | 1080 | 1440 | 2160
  prefer_format: "webm"       # webm | mp4 | any

destination:
  mode: "local"               # local | gdrive
  local:
    path: "~/ytpl-downloads"
  gdrive:
    accounts:
      - name: "drive-account-1"
        rclone_remote: "gdrive1"
        quota_gb: 15
        upload_folder: "YT-Lectures"

notifications:
  email:
    enabled: true
    send_report_on_activity: true
    send_on_failure: true
  telegram:
    enabled: true
    send_report_on_activity: true
    send_on_failure: true

sources:
  - type: "playlist"
    name: "Example Playlist"
    url: "https://youtube.com/playlist?list=..."
    # optional per-source overrides:
    destination:
      mode: "local"
      local:
        path: "~/lectures/mit"
    encoding:
      enabled: false
    quality:
      max_resolution: 720
      crf: 30
      preset: "fast"

  - type: "channel"
    name: "Example Channel"
    url: "https://youtube.com/@example"
    filters:
      after_date: "2023-01-01"       # only videos uploaded on/after this date
      keywords: ["lecture", "math"]  # title must contain at least one keyword (case-insensitive)
      exclude_keywords: ["shorts", "livestream"]
      min_duration_seconds: 300
      max_duration_seconds: 7200
    encoding:
      crf: 24
      preset: "slow"
```

Rules for config.py:
- All tilde paths must be expanded with Path.expanduser() when accessed.
- Per-source encoding/quality/destination fields are optional and override globals when present.
- Expose a method get_effective_config(source) that returns the merged encoding+quality+destination for a given source.
- Raise clear pydantic ValidationError with field path on any invalid value.
- Load .env file automatically using python-dotenv before reading env vars.

--- .env.example ---

# Database
NEON_DSN=postgres://user:password@host/dbname

# Gmail (use App Password, not main password)
GMAIL_SENDER=you@gmail.com
GMAIL_APP_PASSWORD=xxxx_xxxx_xxxx_xxxx
GMAIL_RECIPIENT=you@gmail.com

# Telegram
TELEGRAM_BOT_TOKEN=123456789:AAxxxxxx
TELEGRAM_CHAT_ID=123456789

--- requirements.txt ---

yt-dlp>=2024.1.1
pydantic>=2.0.0
python-dotenv>=1.0.0
psycopg2-binary>=2.9.0
requests>=2.31.0

--- run_context.py ---

Define a RunContext dataclass that accumulates stats for the current run:
  run_id: str            # UUID4, generated at startup
  started_at: datetime
  dry_run: bool
  discovered: int = 0
  skipped: int = 0
  downloaded: int = 0
  encoded: int = 0
  uploaded: int = 0
  failed: int = 0
  abandoned: int = 0
  newly_deleted: int = 0
  encoding_savings_mb: float = 0.0
  videos_this_run: list[Video]   # all videos touched this run

Include method summary_dict() that returns a plain dict of all stats.
```

---

## PROMPT 2 — Utilities (disk, time window, cleanup, yt-dlp check, subprocess runner)

```
Implement all files inside ytpl_sync/utils/. Do not touch any other file.

--- utils/subprocess_runner.py ---

Implement run_command(cmd: list[str], description: str, timeout: int = 3600) -> tuple[int, str, str]:
- Runs the command using subprocess.run with stdout/stderr captured.
- Logs the command at DEBUG level before running.
- Logs stdout at DEBUG level and stderr at WARNING level after running.
- Returns (returncode, stdout, stderr).
- Raises RuntimeError with a clear message if returncode != 0 and raise_on_error=True (default True).

Implement find_executable(name: str, config_override: Optional[str]) -> str:
- If config_override is not None, check that path exists and is executable, return it.
- Otherwise use shutil.which(name).
- Raises RuntimeError with a helpful message if not found (include install hint for ffmpeg and rclone).

--- utils/disk.py ---

Implement check_free_space(path: str, min_free_gb: float) -> None:
- Uses shutil.disk_usage() on the given path (expand ~ first).
- If free space < min_free_gb * 1024**3, raises DiskSpaceError(available_gb, required_gb) with a clear message.
- Logs available space at DEBUG level.

DiskSpaceError must be a custom exception with attributes available_gb and required_gb.

--- utils/time_window.py ---

Implement is_within_time_window(window: Optional[str]) -> bool:
- window is "HH:MM-HH:MM" string or None.
- If None, return True.
- Parse start and end times. If end < start, the window wraps midnight.
- Return True if current local time is within the window.
- Raise ValueError with clear message if format is invalid.

Implement assert_time_window(window: Optional[str]) -> None:
- Calls is_within_time_window. If False, raises TimeWindowError with message "Outside configured run window HH:MM-HH:MM, exiting."

TimeWindowError must be a custom exception.

--- utils/cleanup.py ---

Implement cleanup_orphan_files(temp_dir: str, max_age_hours: int = 24) -> int:
- Scans temp_dir for files matching *.part, *.ytdl, *.temp, *.tmp.
- Deletes files older than max_age_hours.
- Returns count of files deleted.
- Logs each deleted file at INFO level.
- Never raises — catches and logs any deletion errors.

--- utils/ytdlp_check.py ---

Implement check_ytdlp(auto_update: bool) -> str:
- Runs: yt-dlp --version and captures output to get current version string.
- Parses the version date (yt-dlp versions are YYYY.MM.DD format).
- If version is older than 30 days, logs a WARNING: "yt-dlp version X is over 30 days old. Consider updating."
- If auto_update is True, runs: yt-dlp -U and logs the output at INFO level.
- Returns the version string.
- Wraps everything in try/except — if yt-dlp is not found, raises RuntimeError with install instructions.
```

---

## PROMPT 3 — Lock file system

```
Implement ytpl_sync/lock.py. Do not touch any other file.

Implement a LockFile class:

  __init__(self, lock_path: str):
    - Expands ~ in lock_path.
    - Stores path as self.path (pathlib.Path).

  acquire(self) -> None:
    - If lock file does not exist: write current PID to it, register atexit handler to release, register SIGTERM and SIGINT handlers to release then exit. Done.
    - If lock file exists:
        - Read PID from file.
        - Check if that process is alive using os.kill(pid, 0) inside try/except.
        - If process is NOT alive (stale lock): log a warning "Stale lock file found (PID X not running). Removing.", delete file, write current PID, register handlers. Done.
        - If process IS alive: raise LockAcquireError(f"Another instance is already running (PID {pid}). Exiting.")
    - Handle file read errors gracefully — if the file is unreadable or contains non-integer content, treat it as stale.

  release(self) -> None:
    - Delete the lock file if it exists.
    - Log at DEBUG level.
    - Never raises.

LockAcquireError must be a custom exception.

The SIGTERM/SIGINT handlers must call self.release() then re-raise the signal (use signal.raise_signal or os.kill(os.getpid(), sig)) so the process exits properly.

Works on Linux, macOS, Windows, and Termux (Android). On Windows, os.kill(pid, 0) raises PermissionError (not ProcessLookupError) if process exists — handle both cases correctly.
```

---

## PROMPT 4 — Database layer (SQLite + Neon + reconciler)

```
Implement all files inside ytpl_sync/db/. Do not touch any other file.

--- db/sqlite_backend.py ---

Implement SQLiteBackend class:

  __init__(self, db_path: str):
    - Expand ~ in path.
    - Create parent directories if needed.

  connect(self) -> None:
    - Opens a sqlite3 connection with WAL journal mode enabled.
    - Stores as self.conn.

  initialize(self) -> None:
    - Creates the `videos` table if not exists with ALL columns from the Video dataclass in models.py.
    - tags and categories columns store JSON text (list serialized with json.dumps).
    - Creates index on (status, pending_neon_sync) for fast querying.

  upsert(self, video: Video) -> None:
    - INSERT OR REPLACE into videos table.
    - Serialize tags/categories to JSON strings.
    - Set updated_at to current UTC ISO timestamp.

  upsert_many(self, videos: list[Video]) -> None:
    - Batch upsert using executemany. Single transaction.

  get(self, video_id: str) -> Optional[Video]:
    - Returns Video or None.

  get_all(self) -> list[Video]:
    - Returns all rows as Video objects.

  get_by_status(self, *statuses: str) -> list[Video]:
    - Returns all Videos matching any of the given statuses.

  get_pending_neon_sync(self) -> list[Video]:
    - Returns Videos where pending_neon_sync = TRUE.

  count(self) -> int:

  max_updated_at(self) -> Optional[str]:
    - Returns the latest updated_at as ISO string, or None if table is empty.

  get_since(self, updated_at: str) -> list[Video]:
    - Returns Videos where updated_at > given timestamp.

  close(self) -> None:

--- db/neon_backend.py ---

Implement NeonBackend class:

  __init__(self, dsn: Optional[str]):
    - If dsn is None, all methods are no-ops (Neon is disabled).

  connect(self) -> bool:
    - Connects using psycopg2 with connect_timeout=10.
    - Enables autocommit = False.
    - Returns True on success, False on failure (logs warning, does not raise).

  initialize(self) -> None:
    - Creates the same `videos` table schema as SQLite if not exists.
    - No-op if not connected.

  upsert_many(self, videos: list[Video]) -> bool:
    - Batch upsert all videos in a single transaction using INSERT ... ON CONFLICT (video_id) DO UPDATE SET ...
    - Returns True on success, False on failure (logs error, does not raise).
    - No-op if not connected.

  count(self) -> Optional[int]:
    - Returns count or None if not connected/failed.

  max_updated_at(self) -> Optional[str]:
    - Returns latest updated_at or None.

  get_since(self, updated_at: str) -> list[Video]:
    - Returns Videos updated after given timestamp.
    - Returns empty list on failure.

  close(self) -> None:

  IMPORTANT: Use a single connection per run. Maximum 2 concurrent connections.
  IMPORTANT: All methods must be wrapped in try/except and never crash the caller.

--- db/manager.py ---

Implement DatabaseManager class:

  __init__(self, sqlite: SQLiteBackend, neon: NeonBackend):

  initialize(self) -> None:
    - Calls initialize() on both backends.

  upsert_video(self, video: Video) -> None:
    - Always writes to SQLite immediately.
    - Marks video.pending_neon_sync = True.
    - Queues for Neon batch write (does NOT write to Neon on each individual call).

  flush_to_neon(self) -> None:
    - Batch-upserts all queued videos to Neon.
    - If Neon succeeds: clears pending_neon_sync flags in SQLite.
    - If Neon fails: leaves pending_neon_sync = True in SQLite for next run.
    - Clears the internal queue after attempting.

  get_video(self, video_id: str) -> Optional[Video]:
    - Reads from SQLite only.

  list_all_video_ids(self) -> set[str]:
    - Returns set of all video_ids from SQLite.

  get_resumable(self) -> list[Video]:
    - Returns videos with status in: PENDING, DOWNLOADING, DOWNLOADED, ENCODING, ENCODED, UPLOADING, FAILED
    - Excludes UPLOADED, ABANDONED, DELETED.

  get_pending_neon_sync(self) -> list[Video]:
    - Delegates to SQLite.

--- db/reconciler.py ---

Implement Reconciler class:

  async run(self, sqlite: SQLiteBackend, neon: NeonBackend, dry_run: bool) -> dict:

  Logic:
    1. Get local_count = sqlite.count(), local_max = sqlite.max_updated_at()
    2. Try Neon: neon_count = neon.count(), neon_max = neon.max_updated_at(). If fails, neon_available = False.
    3. If neon_available and neon_max > local_max:
       - Fetch delta: neon.get_since(local_max) — only records newer than local max.
       - If not dry_run: sqlite.upsert_many(delta).
       - Log: f"Pulled {len(delta)} records from Neon into SQLite."
    4. If neon_available and local_max > neon_max:
       - Fetch delta: sqlite.get_since(neon_max).
       - If not dry_run: neon.upsert_many(delta).
       - Log: f"Pushed {len(delta)} records from SQLite to Neon."
    5. Retry any sqlite.get_pending_neon_sync() records: push to Neon if available, clear flag on success.
    6. Return dict with keys: neon_available, pulled_from_neon, pushed_to_neon, pending_synced.
```

---

## PROMPT 5 — Source resolvers (playlist + channel)

```
Implement all files inside ytpl_sync/sources/. Do not touch any other file.

--- sources/playlist.py ---

Implement PlaylistResolver class:

  resolve(self, source_config, cookies_file: Optional[str]) -> list[dict]:
    - Uses yt-dlp Python API (import yt_dlp) with extract_flat=True to get playlist entries without downloading.
    - ydl_opts:
        quiet=True, no_warnings=True, extract_flat='in_playlist'
        cookiefile=cookies_file if provided
    - For each entry, extract: id, title, url, duration, upload_date, view_count, like_count, channel, channel_id, thumbnails, tags, categories, description.
    - Return list of dicts with these keys (use None for missing fields, never raise KeyError).
    - Log count of videos found at INFO level.
    - Catches yt_dlp.utils.DownloadError — logs error and returns empty list.

--- sources/channel.py ---

Implement ChannelResolver class:

  resolve(self, source_config, cookies_file: Optional[str]) -> list[dict]:
    - Same yt-dlp extraction approach as PlaylistResolver but targets the channel URL.
    - After extracting, applies filters from source_config.filters if present:
        after_date: skip videos where upload_date < filter value (YYYYMMDD comparison)
        keywords: skip videos where title does not contain any keyword (case-insensitive)
        exclude_keywords: skip videos where title contains any exclude keyword (case-insensitive)
        min_duration_seconds: skip videos where duration < value
        max_duration_seconds: skip videos where duration > value
    - Log how many videos were found before and after filtering.
    - Returns filtered list of dicts.

--- sources/resolver.py ---

Implement resolve_source(source_config, cookies_file) -> list[dict]:
  - Inspects source_config.type.
  - Routes to PlaylistResolver or ChannelResolver accordingly.
  - Returns the list of video metadata dicts.

For each returned video dict, also include:
  source_name: source_config.name
  source_type: source_config.type
  source_url: source_config.url
```

---

## PROMPT 6 — Downloader

```
Implement ytpl_sync/downloader.py. Do not touch any other file.

Implement Downloader class:

  __init__(self, ffmpeg_path: str, cookies_file: Optional[str]):

  download(self, video_meta: dict, output_dir: str, quality_config, run_id: str) -> Video:
    """
    Downloads a single video. Returns a Video object with status DOWNLOADED or FAILED.
    """
    Steps:
    1. Build a Video object from video_meta with status=DOWNLOADING, run_id=run_id, download_started_at=now().
    2. Build yt-dlp format selector based on quality_config:
       - prefer_format=webm: "bestvideo[ext=webm][height<={res}]+bestaudio[ext=webm]/bestvideo[height<={res}]+bestaudio[ext=webm]/bestvideo[height<={res}]+bestaudio/best[height<={res}]"
       - prefer_format=mp4: "bestvideo[ext=mp4][height<={res}]+bestaudio[ext=m4a]/best[ext=mp4][height<={res}]/best[height<={res}]"
       - prefer_format=any: "bestvideo[height<={res}]+bestaudio/best[height<={res}]"
       Where {res} = quality_config.max_resolution.
    3. ydl_opts:
       - format: the selector above
       - outtmpl: output_dir/%(id)s.%(ext)s
       - quiet: True, no_warnings: True
       - concurrent_fragment_downloads: 4
       - cookiefile: cookies_file if provided
       - noprogress: True
    4. Run yt_dlp.YoutubeDL(ydl_opts).download([video_meta['url']]).
    5. Find the downloaded file (glob output_dir/video_id.*).
    6. On success: set video.status=DOWNLOADED, video.original_filename, video.original_size_bytes, video.downloaded_at=now(), video.temp_path.
    7. On yt_dlp.utils.DownloadError or any exception: set video.status=FAILED, video.failed_stage=DOWNLOAD, video.failed_reason=str(e). Log error.
    8. Return video.

  IMPORTANT: Never re-download a video whose video_id already has status DOWNLOADED, ENCODED, UPLOADING, UPLOADED. This check is done by the caller (main.py), but add an assertion here as a safety net.
```

---

## PROMPT 7 — Encoder

```
Implement ytpl_sync/encoder.py. Do not touch any other file.

Implement Encoder class:

  __init__(self, ffmpeg_path: str):

  encode(self, video: Video, encoding_config) -> Video:
    """
    Encodes a video using ffmpeg. Returns updated Video with status ENCODED or FAILED.
    Skips encoding if encoding_config.enabled is False — in that case just remux to MKV losslessly and return.
    """

    If encoding_config.enabled is False:
      - Run lossless remux: ffmpeg -i input -c copy -map 0:v:0 -map 0:a:0 -map_metadata -1 output.mkv
      - Delete original file on success.
      - Update video fields and set status=ENCODED. Return.

    If encoding_config.enabled is True:
      - Determine encoder:
          software  → libx265
          nvenc     → hevc_nvenc
          vaapi     → hevc_vaapi
          videotoolbox → hevc_videotoolbox
      - Build ffmpeg command:
          [ffmpeg, -i, input_path,
           -c:v, {encoder}, -crf, {crf}, -preset, {preset},  (for software)
           -c:a, libopus, -b:a, {audio_bitrate},
           -map 0:v:0, -map 0:a:0,
           -map_metadata -1,
           output.mkv]
        For hardware encoders replace -crf with -qp (same value) and omit -preset (use -preset quality for nvenc).
      - Set video.status=ENCODING, video.encode_started_at=now() before running.
      - Run command via utils.subprocess_runner.run_command with raise_on_error=False.
      - On success (returncode 0):
          - Delete original file.
          - Set video.final_filename, video.final_size_bytes, video.encoded_at=now(), video.status=ENCODED.
          - Calculate video.encoding_savings_pct = (1 - final_size/original_size) * 100. Round to 1 decimal.
          - Log savings at INFO level.
      - On failure:
          - Set video.status=FAILED, video.failed_stage=ENCODE, video.failed_reason=stderr.
          - Do NOT delete original file.
          - Log error.
      - Return video.

    Output file path: same directory as input, same stem, .mkv extension.
    Temporary output: write to stem.mkv.tmp first, rename to stem.mkv on success (atomic-ish).
```

---

## PROMPT 8 — Storage (local + rclone Drive + router)

```
Implement all files inside ytpl_sync/storage/. Do not touch any other file.

--- storage/local_storage.py ---

Implement LocalStorage class:

  store(self, video: Video, dest_path: str) -> Video:
    - Expand ~ in dest_path.
    - Create dest_path / source_name subdirectory (use video.source_name, sanitize for filesystem).
    - Move video's file (video.final_filename or video.temp_path) to dest directory.
    - Set video.local_path = final destination path.
    - Set video.status = UPLOADED (local storage counts as "uploaded" / done).
    - Set video.uploaded_at = now().
    - Return video.

--- storage/gdrive_storage.py ---

Implement GDriveStorage class:

  __init__(self, accounts: list, rclone_path: str):
    Where accounts is the list of DriveAccount configs.

  _get_used_quota(self, rclone_remote: str) -> Optional[float]:
    - Runs: rclone about {rclone_remote}: --json
    - Parses JSON output. Fields: used (bytes), total (bytes).
    - Returns used_gb as float.
    - Returns None on failure (logs warning).

  _select_account(self) -> Optional[dict]:
    - Iterates accounts in order.
    - For each, calls _get_used_quota.
    - Selects first account where used_gb < quota_gb * 0.90 (never fill above 90%).
    - Returns the account config dict, or None if all are full.

  upload(self, video: Video) -> Video:
    - Calls _select_account(). If None: raise StorageFullError("All Google Drive accounts are at 90% capacity.").
    - Get source file path from video.final_filename (or temp_path fallback).
    - Remote destination: {rclone_remote}:{upload_folder}/{source_name}/{filename}
    - Run: rclone copy {source_file} {remote_dest_dir} --progress=false --stats=0
    - Set video.status = UPLOADING before running.
    - On success (returncode 0):
        - Set video.rclone_remote, video.rclone_path, video.status=UPLOADED, video.uploaded_at=now().
        - Delete local temp file.
    - On failure: set video.status=FAILED, video.failed_stage=UPLOAD, video.failed_reason=stderr.
    - Return video.

StorageFullError must be a custom exception.

--- storage/router.py ---

Implement StorageRouter class:

  __init__(self, app_config, rclone_path: str):

  store(self, video: Video, effective_dest_config) -> Video:
    - Reads effective_dest_config.mode ("local" or "gdrive").
    - Routes to LocalStorage or GDriveStorage accordingly.
    - Returns updated video.
```

---

## PROMPT 9 — Notifications (Gmail + Telegram + reporter)

```
Implement all files inside ytpl_sync/notifications/. Do not touch any other file.

ALL notification code must be wrapped in try/except. A notification failure must NEVER crash the application. Log errors at ERROR level and return gracefully.

--- notifications/reporter.py ---

Implement ReportBuilder class:

  build_email_report(self, ctx: RunContext) -> str:
    Builds a detailed plain-text email body with:
    - Run timestamp, duration (formatted as Xh Ym Zs), run_id
    - Summary table: discovered, skipped, downloaded, encoded, uploaded, failed, abandoned, newly deleted
    - Average encoding savings % (if any encoding happened)
    - Section "Downloaded this run": for each uploaded video — title, source_name, size reduction (original → final MB), destination (local path or rclone remote:path)
    - Section "Failed": for each failed/abandoned video — title, failed_stage, failed_reason, retry_count
    - Section "Newly deleted on YouTube": video titles flagged as deleted this run
    - Footer: "ytpl-sync v{version} | Run ID: {run_id}"

  build_telegram_message(self, ctx: RunContext) -> str:
    Builds a concise Telegram message (plain text, no markdown):
    - First line: "ytpl-sync run complete"
    - Stats: Discovered: X | Downloaded: X | Encoded: X | Uploaded: X | Failed: X | Deleted: X
    - If any failed: list failed video titles (max 5, then "+ N more")
    - If encoding happened: "Avg encoding savings: X%"

  build_failure_alert_email(self, video: Video) -> str:
    - Short email for when a video hits max_retries and is marked ABANDONED.
    - Includes: title, video_id, youtube_url, failed_stage, failed_reason, retry_count.

  build_failure_alert_telegram(self, video: Video) -> str:
    - One-liner: "ABANDONED: {title} | Stage: {failed_stage} | {failed_reason[:80]}"

--- notifications/mailer.py ---

Implement Mailer class:

  __init__(self):
    - Reads GMAIL_SENDER, GMAIL_APP_PASSWORD, GMAIL_RECIPIENT from environment.
    - If any are missing, logs a warning and sets self.enabled = False.

  send(self, subject: str, body: str) -> bool:
    - Uses smtplib.SMTP_SSL('smtp.gmail.com', 465).
    - Logs in with GMAIL_SENDER + GMAIL_APP_PASSWORD.
    - Sends plain text email.
    - Returns True on success, False on failure.
    - MUST be wrapped in try/except. Never raises.
    - Logs success at INFO, failure at ERROR.

--- notifications/telegram.py ---

Implement TelegramNotifier class:

  __init__(self):
    - Reads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from environment.
    - If missing, sets self.enabled = False.

  send(self, message: str) -> bool:
    - Uses requests.post to https://api.telegram.org/bot{token}/sendMessage with chat_id and text.
    - Timeout = 10 seconds.
    - Returns True on success, False on failure.
    - MUST be wrapped in try/except. Never raises.
    - Logs success at INFO, failure at ERROR.
```

---

## PROMPT 10 — Main orchestrator

```
Implement ytpl_sync/main.py. This is the final integration point. Import and wire together all modules built so far.

Implement cli() as the entry point (called by pyproject.toml).

--- CLI arguments ---

Use argparse:
  --config       Path to config.yaml (default: ./config.yaml)
  --dry-run      Override config dry_run to True
  --version      Print version from VERSION file and exit
  --source       Run only the source with this name (for testing a single source)

--- Logging setup ---

Set up Python logging at the start of cli():
- Root logger at DEBUG level.
- Console handler at INFO level (StreamHandler with simple format: "HH:MM:SS | LEVEL | message").
- File handler at DEBUG level writing to config.settings.log_file (RotatingFileHandler, maxBytes=10MB, backupCount=3).
- Log format for file: "YYYY-MM-DD HH:MM:SS | LEVEL | module:line | message".

--- Main flow ---

async def run(config, args) -> RunContext:

  1. Generate run_id = str(uuid.uuid4())[:8]
  2. Create RunContext(run_id=run_id, started_at=now(), dry_run=dry_run)
  3. Log: f"=== ytpl-sync started | run_id={run_id} | dry_run={dry_run} ==="

  4. LOCK: Acquire LockFile(config.settings.lock_file). On LockAcquireError: log and sys.exit(1).

  5. TIME WINDOW: Call assert_time_window(config.settings.only_run_between). On TimeWindowError: log and sys.exit(0). (Exit 0 — not an error, just outside window.)

  6. DISK CHECK: Call check_free_space(config.settings.temp_dir or tempfile.gettempdir(), config.settings.min_free_gb). On DiskSpaceError: log, send failure notification, sys.exit(1).

  7. CLEANUP: Call cleanup_orphan_files(config.settings.temp_dir or tempfile.gettempdir()).

  8. YTDLP CHECK: Call check_ytdlp(config.settings.ytdlp_auto_update).

  9. EXECUTABLES: Resolve ffmpeg_path and rclone_path via find_executable(). If either is not found and will be needed (based on config), log error and exit.

  10. DB INIT: Initialize SQLiteBackend and NeonBackend. Call manager.initialize().

  11. RECONCILE: Run Reconciler.run(sqlite, neon, dry_run). Log summary.

  12. For each source in config.sources (filtered by --source if provided):
      a. Log: f"Processing source: {source.name} ({source.type})"
      b. Resolve video list via resolve_source(source, config.settings.cookies_file).
      c. ctx.discovered += len(videos)
      d. For each video_meta in videos:
           - Check if video_id already in DB:
               - Status UPLOADED: ctx.skipped++, continue.
               - Status ABANDONED: ctx.skipped++, continue.
               - Status DELETED: ctx.skipped++, continue.
               - Partial status (DOWNLOADED, ENCODED etc.): resume from that stage.
               - Not in DB: start fresh from PENDING.
           - If dry_run: log what would happen, continue.
           - DOWNLOAD stage (if needed):
               video = downloader.download(video_meta, temp_dir, effective_quality, run_id)
               manager.upsert_video(video)
               if video.status == FAILED: handle_failure(video, ctx, config, mailer, telegram); continue
               ctx.downloaded++
           - ENCODE stage (if needed):
               video = encoder.encode(video, effective_encoding)
               manager.upsert_video(video)
               if video.status == FAILED: handle_failure(video, ctx, config, mailer, telegram); continue
               if encoding was done: ctx.encoded++; ctx.encoding_savings_mb += savings
           - UPLOAD stage:
               video = storage_router.store(video, effective_destination)
               manager.upsert_video(video)
               if video.status == FAILED: handle_failure(video, ctx, config, mailer, telegram); continue
               ctx.uploaded++
           - ctx.videos_this_run.append(video)
      e. After all videos in source: manager.flush_to_neon()

  13. Log run summary to console and file.
  14. Send notifications (if activity or failures).
  15. Release lock.
  16. Return ctx.

--- handle_failure function ---

def handle_failure(video: Video, ctx: RunContext, config, mailer: Mailer, telegram: TelegramNotifier) -> None:
  video.retry_count += 1
  if video.retry_count >= config.settings.max_retries:
    video.status = VideoStatus.ABANDONED
    ctx.abandoned++
    log WARNING: f"Video ABANDONED after {video.retry_count} retries: {video.title}"
    # Send alert notifications (wrapped in try/except already inside mailer/telegram)
    if config.notifications.email.send_on_failure:
      mailer.send(f"[ytpl-sync] ABANDONED: {video.title}", reporter.build_failure_alert_email(video))
    if config.notifications.telegram.send_on_failure:
      telegram.send(reporter.build_failure_alert_telegram(video))
  else:
    log WARNING: f"Video failed at stage {video.failed_stage} (attempt {video.retry_count}/{config.settings.max_retries}): {video.title} — {video.failed_reason}"
  ctx.failed++

--- Notification send at end of run ---

After the run loop:
  report = ReportBuilder()
  had_activity = ctx.downloaded > 0 or ctx.uploaded > 0 or ctx.failed > 0 or ctx.newly_deleted > 0

  if had_activity:
    if config.notifications.email.enabled and config.notifications.email.send_report_on_activity:
      duration = format_duration(now() - ctx.started_at)
      mailer.send(f"[ytpl-sync] Run complete — {ctx.uploaded} uploaded, {ctx.failed} failed", report.build_email_report(ctx))
    if config.notifications.telegram.enabled and config.notifications.telegram.send_report_on_activity:
      telegram.send(report.build_telegram_message(ctx))

--- Deletion detection ---

During source resolution, for any video_id already in DB that is NOT returned by yt-dlp (i.e. it was previously discovered from this source but is now missing from the playlist/channel):
  - Set video.deleted = True, video.deleted_detected_at = now(), video.status = DELETED.
  - Upsert to DB.
  - ctx.newly_deleted++
  - Do NOT delete any local files — just flag in DB.

--- Entry point ---

def cli():
  args = parse_args()
  if args.version: print version; sys.exit(0)
  config = load_config(args.config)
  if args.dry_run: config.settings.dry_run = True
  try:
    asyncio.run(run(config, args))
  except KeyboardInterrupt:
    log INFO "Interrupted by user."
    sys.exit(0)
  except Exception as e:
    log CRITICAL f"Unhandled error: {e}" with traceback
    sys.exit(1)
```

---

## PROMPT 11 — Tests

```
Add a tests/ directory to the ytpl-sync project. Use pytest and pytest-asyncio.

Create these test files:

tests/conftest.py
  - Fixture: tmp_db_path — returns a tmp sqlite path.
  - Fixture: sample_video — returns a Video object with status=PENDING, all required fields populated.
  - Fixture: sample_config — returns a minimal valid AppConfig object.

tests/test_config.py
  - test_valid_config_loads: write a valid config.yaml to a tmp file, load it, assert all fields parsed.
  - test_missing_required_field: omit 'sources', assert ValidationError raised.
  - test_per_source_override: source with encoding.enabled=False overrides global encoding.enabled=True.
  - test_tilde_expansion: paths with ~ are expanded to absolute paths.

tests/test_lock.py
  - test_acquire_and_release: acquire lock, assert file contains current PID, release, assert file gone.
  - test_stale_lock: write a lock file with a dead PID (99999999), acquire should succeed and overwrite.
  - test_concurrent_lock: acquire lock in current process, attempt to acquire again in same process, assert LockAcquireError raised.

tests/test_db.py (use tmp SQLite, mock Neon with unittest.mock.patch)
  - test_initialize_creates_table
  - test_upsert_and_get: upsert a video, get it back, assert all fields match.
  - test_upsert_updates: upsert same video twice with different status, get returns latest.
  - test_list_all_video_ids: upsert 3 videos, list_all returns correct set.
  - test_get_by_status: upsert videos with different statuses, filter returns correct ones.
  - test_flush_to_neon_on_failure: mock neon.upsert_many to return False, assert pending_neon_sync stays True in SQLite.

tests/test_reconciler.py (async tests with pytest-asyncio)
  - test_pull_delta_from_neon: mock neon with count=30, local count=25, assert 5 records upserted into SQLite.
  - test_push_delta_to_neon: mock neon with count=20, local count=25, assert 5 records pushed to Neon.
  - test_both_remotes_down: mock neon.connect returning False, reconciler runs without error.
  - test_dry_run_no_writes: dry_run=True, neon has delta, assert sqlite.upsert_many NOT called.

tests/test_utils.py
  - test_time_window_inside: current time within window returns True.
  - test_time_window_outside: current time outside window returns False.
  - test_time_window_none: None window always returns True.
  - test_time_window_midnight_wrap: window "23:00-01:00", test times on both sides.
  - test_disk_check_passes: mock shutil.disk_usage with plenty of space.
  - test_disk_check_fails: mock shutil.disk_usage with low space, assert DiskSpaceError.
  - test_cleanup_orphan_files: create .part files older than 24h in tmp dir, assert they are deleted.

tests/test_downloader.py (mock yt-dlp)
  - test_download_success: mock YoutubeDL.download, assert video status=DOWNLOADED.
  - test_download_skips_known_id: assert that a video already UPLOADED is not re-downloaded (assertion error).
  - test_download_failure: mock YoutubeDL to raise DownloadError, assert video status=FAILED, failed_stage=DOWNLOAD.

tests/test_encoder.py (mock subprocess)
  - test_encode_disabled_remux: encoding disabled, assert ffmpeg called with -c copy.
  - test_encode_software: encoding enabled, encoder=software, assert libx265 in ffmpeg command.
  - test_encode_savings_calculated: mock output file smaller than input, assert encoding_savings_pct correct.
  - test_encode_failure: mock ffmpeg returncode=1, assert video status=FAILED, original file preserved.

tests/test_notifications.py (mock smtplib and requests)
  - test_mailer_sends: mock SMTP_SSL, assert send returns True.
  - test_mailer_failure_returns_false: mock SMTP_SSL to raise, assert returns False (does not raise).
  - test_telegram_sends: mock requests.post, assert send returns True.
  - test_telegram_failure_returns_false: mock requests.post to raise, assert returns False.
  - test_report_email_contains_stats: build_email_report with known ctx, assert key strings present.
  - test_report_telegram_short: build_telegram_message, assert length under 300 chars for typical run.

Add .github/workflows/ci.yml:
  - Trigger: push and pull_request to main.
  - Job: test on ubuntu-latest with Python 3.11.
  - Steps: checkout, install dependencies (pip install -e ".[dev]"), run pytest with -v.
  - Add dev dependencies to pyproject.toml: pytest, pytest-asyncio, pytest-cov.
```

---

## Notes for the vibe coder

- Build and verify prompts 1–4 before starting prompt 5. The models and DB layer are foundational.
- After prompt 7 (encoder), do a manual test encode on a short video before continuing.
- Prompt 10 (main) pulls everything together — if any earlier module has a broken interface, fix it before starting prompt 10.
- The `.env` file must never be committed. Verify `.gitignore` covers it after prompt 1.
- On Termux: `pkg install ffmpeg` and `pkg install python`. rclone must be installed separately via the rclone install script for Android.
- Test the full run first with `--dry-run` before a live run.
