# Optional SQLite database browser

This standalone Compose project runs [DB Browser for SQLite](https://github.com/sqlitebrowser/sqlitebrowser) using the maintained [LinuxServer image](https://docs.linuxserver.io/images/docker-sqlitebrowser/). It streams the desktop application into your browser. Start it separately, like `filebrowser/`; Jarvis's normal startup does not launch it.

The host database directory is mounted read-only at `/databases` by default. An explicit edit flag makes that mount writable. This is enforced by Docker, even if the GUI offers edit controls. The application settings, certificates, and exports remain writable in this directory's ignored `data/` folder, mounted at `/config`.

## Configure and start

From the repository root:

```bash
cd sqlitebrowser
cp -n .env.example .env
# Edit .env: set SQLITEBROWSER_PASSWORD and check PUID/PGID and database path.
./start
```

Use a unique password of at least 12 characters. The example's port is `8112`, with a loopback bind. Visit **https://127.0.0.1:8112/** and sign in using `SQLITEBROWSER_USER` and `SQLITEBROWSER_PASSWORD`. The image creates a self-signed certificate; use HTTPS and accept that local certificate only for your own trusted host. For another device, configure a trusted LAN or Tailscale bind IP and browse to that IP instead.

`SQLITEBROWSER_DATABASE_PATH` is the actual **host** directory, relative to this Compose file or absolute. The default `../data` works for the usual native checkout and main Docker bind mounts. Custom Docker data paths or volumes need their actual host path. A missing source path is rejected instead of creating an empty directory.

`PUID` and `PGID` must match the database-file owner; on Linux use `id` to check them. Startup does not change permissions or ownership of `/databases`. Windows and macOS users can use Docker Desktop and the direct Compose commands below; the Bash starter is optional.

## Browse databases

### Open your first database

The application runs inside the Docker container. Its **Open Database** dialog
shows the container's folders, rather than your computer's usual files. It may
start in a home folder showing **Desktop** and **SSL**; Jarvis's mounted databases
are in `/databases`.

1. In DB Browser for SQLite, click **Open Database** on the toolbar.
2. Click the **File name** field at the bottom of the dialog, type `/databases/`,
   and press **Enter** to open that folder.
3. Select a `.db` file, such as `jarvis_memory.db`, then click **Open**. You can
   also type a complete path such as `/databases/jarvis_memory.db` directly into
   the **File name** field and open it.
4. Select the **Browse Data** tab.
5. Choose a table from the **Table** dropdown to see its rows. Select another
   table from that dropdown to browse different records in the same database.

Use **Open Database** for an existing database; no import or upload is needed.
The **Database Structure** tab lists its tables and columns. **Browse Data** shows
stored records. To switch databases, click **Open Database** again and choose
another file.

### Which database should I open?

These paths assume the default Jarvis data-directory mount. Files appear only
when the corresponding feature or mode has been initialized.

| Open this path | What it contains |
| --- | --- |
| `/databases/jarvis_memory.db` | Cloud-mode memories, conversations, Tool RAG, alerts, reminders and scheduled tasks |
| `/databases/jarvis_memory_local.db` | The corresponding local-mode Memory data |
| `/databases/jarvis_intelligence.db` | Cloud-mode Intelligence state and history |
| `/databases/jarvis_intelligence_local.db` | Local-mode Intelligence state and history |
| `/databases/background_tasks.db` | Background-task state and events |
| `/databases/source_library/cloud.db` | Cloud-mode Source Library catalog |
| `/databases/source_library/local.db` | Local-mode Source Library catalog |
| `/databases/browser-use.db` | Browser automation state, where installed |

For example, to inspect local-mode conversations, open
`/databases/jarvis_memory_local.db`, select **Browse Data**, then choose the
`conversations` table.

Cloud/local switching in Jarvis does not switch the browser's open database:
choose the matching file yourself. Files under `/databases/backups/` are older
copies; open the paths above to inspect the current databases. Choose the `.db`
file itself, not a companion file ending in `-wal` or `-shm`.

### If you cannot find a database

Start by entering `/databases/` in the open dialog instead of looking under
Desktop or SSL. If a file is hidden by the dialog's file-type filter, select
**All files**. If `/databases` is empty or contains different files, check
`SQLITEBROWSER_DATABASE_PATH` in `.env`: it must point to the host directory that
contains the databases. After changing it, rerun `./start` to recreate the mount.
See [Configure and start](#configure-and-start) for host paths and file ownership.

Existing subdirectories and backups are also accessible. The mount exposes the
selected directory's other files as well, so choose a narrower host path when
needed. This browser handles SQLite files; it does not browse external database
servers. Some extension-specific tables may need their original SQLite extension
to be queried.

Changes made by Jarvis are visible when you reload/requery the database in the
application. Browsing does not require edit mode; the default read-only mount
protects the existing files.

### SQLite WAL files and snapshots

Mount a directory rather than an individual database, so SQLite can see adjacent `-wal` and `-shm` files. Do not copy a running database with an ordinary file copy: committed data may still live in the WAL.

A read-only mount can read a WAL database when its required companion files are present and readable. If opening fails because companion files need to be created, keep the read-only protection and browse a consistent snapshot made with SQLite's backup API instead. For native installations, this example creates a separate snapshot under the browser's writable settings folder:

```bash
# Run from the repository root; choose a source filename before running.
.venv/bin/python - <<'PY'
import sqlite3
from pathlib import Path

source = Path('data/background_tasks.db').resolve(strict=True)
target = Path('sqlitebrowser/data/snapshots/background_tasks.db')
target.parent.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as live:
    with sqlite3.connect(target) as snapshot:
        live.backup(snapshot)
        snapshot.execute('PRAGMA journal_mode=DELETE')
print(target)
PY
```

Open `/config/snapshots/background_tasks.db` in the GUI. A snapshot is not live; close it before rerunning the backup command to refresh it. Editing a snapshot does not edit the live database. See [SQLite's backup API](https://www.sqlite.org/backup.html) and [read-only WAL requirements](https://www.sqlite.org/wal.html#read_only_databases).

## Enable edits explicitly

For a temporary edit session:

```bash
./start --edit
```

The service is recreated with `/databases` writable. Save changes using the application's normal **Write Changes** action. Back up the affected database and stop the Jarvis processes that write it before manually editing live data: direct SQL bypasses Jarvis validation, and SQLite locking does not protect application-level invariants. No Jarvis service is automatically stopped or migrated by this setup.

Return to enforced read-only access:

```bash
./start --read-only
```

For a persistent choice, set `SQLITEBROWSER_READ_ONLY=false` in the ignored `.env`, then run `./start`. An explicit command flag takes precedence for that run but does not rewrite `.env`. A container restart retains its current mount mode; changing it requires a Compose recreation, as these commands perform when the setting changes.

Equivalent direct Compose commands, also suitable for Docker Desktop users:

```bash
mkdir -p data
docker compose up -d                         # Uses .env; read-only by default
```

For one edit-mode run without changing `.env`:

```bash
# Bash/zsh
SQLITEBROWSER_READ_ONLY=false docker compose up -d
# PowerShell
$env:SQLITEBROWSER_READ_ONLY='false'; docker compose up -d; Remove-Item Env:SQLITEBROWSER_READ_ONLY
# Command Prompt
set SQLITEBROWSER_READ_ONLY=false
docker compose up -d
set SQLITEBROWSER_READ_ONLY=
```

Replace `false` with `true` to recreate the service in read-only mode. Every user connected to this container shares its application session and mount mode; this is an operator utility, not per-user database authorization.

## Access and persistence

This service has its own login; Jarvis Web cookies do not authenticate it. Only the HTTPS port is published. The desktop's terminal, passwordless sudo, file-transfer helpers, and session sharing are disabled using LinuxServer's supported hardening settings. The container has no Docker socket, host root, provider env files, GPU device, or privileged mode mounted/enabled. Treat the database contents and exported files as private. Basic auth is intended for a trusted local network; Internet access requires a properly authenticated reverse proxy. See [LinuxServer's security guidance](https://docs.linuxserver.io/selkies/user-guide/security/).

Both `.env` and `data/` are ignored by Git, and `sqlitebrowser/` is excluded from Jarvis Docker build contexts. The tracked example contains portable defaults and no real credentials, host addresses, or personal locations. Installing this option requires Docker Compose and its own image, without changing Jarvis's Python dependencies or database schemas.

## Stop and update

```bash
docker compose down
# Explicit image update, then recreate with your chosen mode:
docker compose pull
./start --read-only
```

Stopping preserves application settings and exports in the ignored `data/` directory. Back up that folder if you want to retain them. The default image tag follows LinuxServer updates; set `SQLITEBROWSER_IMAGE` to a tested tag or digest for reproducible deployments.
