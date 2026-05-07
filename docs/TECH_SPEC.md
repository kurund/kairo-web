# Kairo Web — Technical Specification

**Version:** 0.1 (draft)
**Companion to:** `DESIGN.md`
**Date:** 2026-05-05

---

## 1. Stack

| Layer                  | Choice                                     | Why                                                                                                                                             |
| ---------------------- | ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| Language               | Python 3.12+                               | Already in use for Kairo v1; familiar                                                                                                           |
| Web framework          | FastAPI                                    | Async-friendly, type-hinted, minimal boilerplate, auto-OpenAPI                                                                                  |
| Templating             | Jinja2 (server-rendered)                   | No build step, works with HTMX                                                                                                                  |
| Frontend interactivity | HTMX + Alpine.js                           | ~30KB total; partial-page swaps without an SPA                                                                                                  |
| CSS                    | Tailwind CSS (CLI build, not CDN)          | Small footprint, consistent design system                                                                                                       |
| Database               | SQLite (WAL mode)                          | Single user, low write volume; trivial backup                                                                                                   |
| Migrations             | Alembic                                    | Standard, plays well with SQLAlchemy                                                                                                            |
| ORM                    | SQLModel (on SQLAlchemy 2.x, sync)         | Tiangolo's wrapper — one class for DB + API model, type-safe, native FastAPI integration. Alembic still works since it's SQLAlchemy underneath. |
| Background jobs        | APScheduler in-process                     | Single-process app, no need for Celery/Redis                                                                                                    |
| Email                  | Resend (or Postmark)                       | Free tier covers personal volume; better deliverability than SMTP                                                                               |
| Auth                   | Magic-link via signed token (itsdangerous) | No passwords, no third-party identity provider                                                                                                  |
| Reverse proxy          | Caddy 2                                    | Auto-HTTPS via Let's Encrypt, single-line config                                                                                                |
| Process manager        | systemd                                    | Native on Hostinger VPS; no extra deps                                                                                                          |

Runtime footprint: one Python process, one SQLite file, one Caddy process. Memory under 200MB at rest.

---

## 2. Repository layout

```
kairo-web/
  pyproject.toml
  README.md
  DESIGN.md
  TECH_SPEC.md
  alembic.ini
  alembic/
    env.py
    versions/
  src/kairo_web/
    __init__.py
    main.py              # FastAPI app entry
    config.py            # pydantic-settings: env-driven config
    db.py                # engine + session factory
    models.py            # SQLAlchemy models
    auth.py              # magic-link login, session middleware
    routes/
      __init__.py
      pages.py           # HTML routes (week view, login, settings)
      tasks.py           # task CRUD endpoints (return HTML fragments for HTMX)
      workspaces.py      # workspace switching
      digest.py          # one-click action links from email
    services/
      capture.py         # parse "#tag @project ~Nh" syntax
      rollover.py        # Sunday-night rollover logic
      digest.py          # build morning/evening email bodies
    templates/
      base.html
      week.html
      partials/
        task_row.html
        today_strip.html
        capture_bar.html
        inbox.html
        emails/
          morning.html
          evening.html
    static/
      app.css            # Tailwind output
      app.js             # tiny Alpine bootstrap
  scripts/
    backup.sh            # cron-friendly SQLite backup to /backups
    seed_dev.py          # populate dev DB with sample tasks
    migrate_v1.py        # one-off importer from ~/.kairo/tasks.db (Kairo v1)
  tests/
    test_capture.py
    test_rollover.py
    test_digest.py
  deploy/
    Caddyfile
    kairo-web.service    # systemd unit
    kairo-web-worker.service  # (only if scheduler is split out later)
```

---

## 3. Data model

SQLite database at `/var/lib/kairo-web/kairo.db` (production) or `./dev.db` (local).

### 3.1 Tables

```sql
-- Workspaces are user-defined. `kairo-web init` seeds 'personal'; users add
-- more via `kairo-web add-workspace`. Schema is open: any slug is allowed.
CREATE TABLE workspace (
  id INTEGER PRIMARY KEY,
  slug TEXT UNIQUE NOT NULL,        -- e.g. 'personal', 'work', 'consulting'
  name TEXT NOT NULL,
  color TEXT NOT NULL,              -- hex, used in UI accents
  morning_digest_enabled INTEGER NOT NULL DEFAULT 1,
  morning_digest_time TEXT NOT NULL DEFAULT '07:00',
  evening_digest_enabled INTEGER NOT NULL DEFAULT 1,
  evening_digest_time TEXT NOT NULL DEFAULT '18:00',
  created_at TEXT NOT NULL
);

CREATE TABLE task (
  id INTEGER PRIMARY KEY,
  workspace_id INTEGER NOT NULL REFERENCES workspace(id),
  title TEXT NOT NULL,
  description TEXT,
  project TEXT,
  estimate_hours REAL,              -- nullable
  status TEXT NOT NULL DEFAULT 'open',  -- 'open' | 'completed'
  position INTEGER NOT NULL,
  is_today INTEGER NOT NULL DEFAULT 0,  -- 1 if on the Today strip
  iso_year INTEGER,                 -- NULL = inbox
  iso_week INTEGER,                 -- NULL = inbox
  created_at TEXT NOT NULL,
  completed_at TEXT,
  CONSTRAINT inbox_or_scheduled CHECK (
    (iso_year IS NULL AND iso_week IS NULL) OR
    (iso_year IS NOT NULL AND iso_week IS NOT NULL)
  )
);
CREATE INDEX idx_task_ws_week ON task(workspace_id, iso_year, iso_week, position);
CREATE INDEX idx_task_ws_inbox ON task(workspace_id) WHERE iso_year IS NULL;

CREATE TABLE tag (
  id INTEGER PRIMARY KEY,
  workspace_id INTEGER NOT NULL REFERENCES workspace(id),
  name TEXT NOT NULL,
  UNIQUE (workspace_id, name)
);

CREATE TABLE task_tag (
  task_id INTEGER NOT NULL REFERENCES task(id) ON DELETE CASCADE,
  tag_id INTEGER NOT NULL REFERENCES tag(id) ON DELETE CASCADE,
  PRIMARY KEY (task_id, tag_id)
);

-- Single-user auth: one row, basically.
CREATE TABLE user (
  id INTEGER PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE login_token (
  token TEXT PRIMARY KEY,           -- signed random string
  user_id INTEGER NOT NULL REFERENCES user(id),
  expires_at TEXT NOT NULL,
  used_at TEXT
);

CREATE TABLE session (
  id TEXT PRIMARY KEY,              -- random session id, set as httpOnly cookie
  user_id INTEGER NOT NULL REFERENCES user(id),
  active_workspace_id INTEGER REFERENCES workspace(id),
  created_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL
);

-- For one-click email action links (e.g., "Roll the rest to tomorrow").
CREATE TABLE digest_action_token (
  token TEXT PRIMARY KEY,
  workspace_id INTEGER NOT NULL REFERENCES workspace(id),
  action TEXT NOT NULL,             -- 'roll_to_tomorrow' | 'roll_to_next_week' | 'noop'
  expires_at TEXT NOT NULL,
  used_at TEXT
);
```

### 3.2 Notes on the schema

- `is_today` is a flag, not a separate location. A task with `is_today=1` still lives in its assigned week. Cleared automatically at midnight local.
- Position numbering is per `(workspace_id, iso_year, iso_week)` group, with a separate sequence per workspace's inbox (`iso_year IS NULL`).
- Tags are scoped per-workspace (the user's "urgent" in Personal shouldn't pollute Full-time autocomplete).
- Project is a free-text string for MVP. Promote to its own table if/when the user wants project-level features.

---

## 4. Routing

Two flavors: **HTML pages** (full document) and **HTMX endpoints** (HTML fragments). Both content-type `text/html`.

### 4.1 Pages

| Method | Path                                      | Purpose                                                  |
| ------ | ----------------------------------------- | -------------------------------------------------------- |
| GET    | `/login`                                  | Email entry form                                         |
| POST   | `/login`                                  | Send magic-link email                                    |
| GET    | `/auth/verify?token=…`                    | Consume token, set session, redirect to active workspace |
| GET    | `/`                                       | Redirect to active workspace's current week              |
| GET    | `/w/<workspace_slug>/week/<year>-W<week>` | The primary screen                                       |
| GET    | `/w/<workspace_slug>/inbox`               | Inbox-focused view (alternative entry to the same data)  |
| GET    | `/settings`                               | Workspace prefs, digest times, account                   |
| POST   | `/logout`                                 | Clear session                                            |

### 4.2 HTMX fragments

| Method | Path                           | Returns                                                                                |
| ------ | ------------------------------ | -------------------------------------------------------------------------------------- |
| POST   | `/api/tasks`                   | Single `<tr>` (or empty if sent to inbox)                                              |
| PATCH  | `/api/tasks/<id>`              | Updated `<tr>`                                                                         |
| POST   | `/api/tasks/<id>/complete`     | Updated `<tr>`                                                                         |
| POST   | `/api/tasks/<id>/reopen`       | Updated `<tr>`                                                                         |
| DELETE | `/api/tasks/<id>`              | Empty (HTMX swaps out)                                                                 |
| POST   | `/api/tasks/<id>/today`        | Toggles `is_today`; returns updated `<tr>` and refreshed Today strip via `hx-swap-oob` |
| POST   | `/api/tasks/<id>/move`         | Reorder (target_position param); returns refreshed table body                          |
| POST   | `/api/tasks/<id>/schedule`     | Move between inbox and current week                                                    |
| GET    | `/api/tasks/inbox`             | Inbox panel partial                                                                    |
| POST   | `/api/workspace/switch/<slug>` | Sets active workspace in session, returns redirect header                              |

### 4.3 Email action endpoints

| Method | Path                  | Purpose                                                           |
| ------ | --------------------- | ----------------------------------------------------------------- |
| GET    | `/digest/act/<token>` | Consume one-click token, perform action, render confirmation page |

---

## 5. Authentication

Single-user, passwordless.

1. User enters email on `/login`.
2. App creates a `login_token` (32 bytes URL-safe random, signed with app secret), expires in 15 minutes.
3. Magic-link sent via Resend: `https://kairo.example.com/auth/verify?token=…`.
4. On click, server validates signature + expiry, marks token used, creates `session` row, sets `kairo_session` cookie (`HttpOnly`, `Secure`, `SameSite=Lax`, 90-day expiry, sliding).
5. Middleware on every request: load session, attach `request.state.user` and `request.state.active_workspace`.

Bootstrap: a `kairo-web init` CLI command seeds the single `user` row with the configured email. Anyone else who hits `/login` with a different email gets a generic "if your email is registered, check your inbox" response (so we don't leak the allowlist) but no token is sent.

---

## 6. Capture bar parser

Module: `services/capture.py`. Pure function, fully unit-tested.

```python
def parse_capture(text: str) -> ParsedCapture:
    """
    'Fix login bug #urgent #auth @auth-rewrite ~2h'
    -> ParsedCapture(
        title='Fix login bug',
        tags=['urgent', 'auth'],
        project='auth-rewrite',
        estimate_hours=2.0,
    )
    """
```

Rules:

- `#word` → tag (lowercase, kebab-case allowed, no spaces).
- `@word` → project (only the last `@token` wins; spaces escaped with `_`).
- `~Nh` or `~N.Nh` or `~Nm` → estimate (hours; minutes converted to fractional hours).
- Everything else, with the markers stripped, is the title (whitespace-trimmed).
- Ordering of markers is irrelevant; they can appear anywhere.
- Escape literal `#`/`@`/`~` by doubling: `##`, `@@`, `~~`.

---

## 7. Rollover

Module: `services/rollover.py`. Triggered by APScheduler at 23:59 every Sunday (server local time).

Logic, per workspace:

1. Identify the closing week (today's ISO week).
2. Select tasks where `status='open'` and `(iso_year, iso_week)` matches the closing week.
3. For each, set `(iso_year, iso_week)` to the next ISO week. Recompute `position` to append to the bottom of the destination week.
4. Clear `is_today` on all rolled tasks.
5. Log a rollover summary row (optional `rollover_log` table — defer until needed).

Manual trigger available via a button on the week view (carries over v1's "Move to Next Week" button) and via `kairo-web rollover` CLI for ad-hoc fixes.

---

## 8. Email digest

Module: `services/digest.py`. APScheduler runs two jobs per workspace, scheduled per the workspace's digest times.

Both digests use Resend's HTTP API (simpler than SMTP, better deliverability). Templates in `templates/partials/emails/`. Rendered to both HTML and plaintext via `html2text`.

### 8.1 Morning digest

Build context: today's date, Today strip tasks, rest-of-week tasks grouped by day-of-week (or just listed if no per-day metadata), totals.

Action links:

- "Open Kairo" → workspace week URL (auto-login via short-lived session token if cookie absent)

### 8.2 Evening digest

Build context: today's completions, remaining Today tasks, total today / week stats.

Action links (each = one `digest_action_token`):

- "Roll the rest to tomorrow" → marks remaining Today tasks `is_today=1` for tomorrow (also moves them to next week if tomorrow falls in next week)
- "Roll to next week" → schedules remaining Today tasks for next ISO week
- "Leave as-is" → no-op confirmation

Tokens single-use, 36-hour expiry.

---

## 9. Frontend behavior

### 9.1 HTMX patterns

- All mutations return updated HTML fragments. No JSON in the wire protocol.
- Use `hx-swap-oob="true"` to update the Today strip and stats footer alongside table mutations.
- `hx-trigger="keyup changed delay:300ms"` on filter chips for live filtering.
- A small Alpine component handles capture-bar focus management and inline-syntax highlight as the user types.

### 9.2 Keyboard

A single Alpine component listens at the document level when no input is focused. Bindings mirror Kairo v1:

| Key                   | Action                                           |
| --------------------- | ------------------------------------------------ |
| `/`                   | Focus capture bar                                |
| `a`                   | Open new-task modal (alternative to capture bar) |
| `e`                   | Edit selected row                                |
| `c`                   | Toggle complete                                  |
| `d`                   | Delete (with confirm)                            |
| `v`                   | View detail                                      |
| `t`                   | Toggle on/off Today strip                        |
| `s`                   | Toggle inbox/scheduled                           |
| `j` / `k`             | Move selection down/up                           |
| `J` / `K`             | Move task down/up in order                       |
| `h` / `l` / `←` / `→` | Prev/next week                                   |
| `g`                   | Jump to current week                             |
| `i`                   | Toggle inbox panel                               |
| `f`                   | Open filter menu                                 |
| `1` / `2` / `3`       | Switch workspace                                 |
| `?`                   | Show shortcut help                               |

### 9.3 Mobile

The week view collapses to a single column under 768px. Today strip becomes a vertical list at the top. Inbox becomes a tab rather than a sidebar. Capture bar remains pinned. Add a `manifest.json` so iOS/Android users can "Add to Home Screen" for a chromeless PWA experience.

---

## 10. Configuration

`.env` file (loaded via pydantic-settings):

```
KAIRO_SECRET_KEY=...                # signs tokens, sessions
KAIRO_DATABASE_URL=sqlite:////var/lib/kairo-web/kairo.db
KAIRO_BASE_URL=https://kairo.example.com
KAIRO_OWNER_EMAIL=you@example.com
KAIRO_TIMEZONE=Europe/London
RESEND_API_KEY=...
RESEND_FROM_DOMAIN=kairo.example.com
LOG_LEVEL=INFO
```

---

## 11. Deployment to Hostinger VPS

Assumptions: Ubuntu 22.04 LTS or 24.04 LTS on the VPS, root SSH access, a domain (e.g. `kairo.example.com`) with an A record pointed at the VPS IP.

### 11.1 One-time server setup

```bash
# As root
apt update && apt install -y python3.12 python3.12-venv git caddy sqlite3
useradd -m -s /bin/bash kairo
mkdir -p /var/lib/kairo-web /var/log/kairo-web /opt/kairo-web/backups
chown -R kairo:kairo /var/lib/kairo-web /var/log/kairo-web /opt/kairo-web
```

### 11.2 App install

```bash
# As kairo
cd /opt/kairo-web
git clone https://github.com/<your-username>/kairo-web.git app
cd app
python3.12 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/alembic upgrade head
.venv/bin/kairo-web init   # seeds workspace rows + owner user
```

### 11.3 systemd unit (`/etc/systemd/system/kairo-web.service`)

```ini
[Unit]
Description=Kairo Web
After=network.target

[Service]
Type=simple
User=kairo
WorkingDirectory=/opt/kairo-web/app
EnvironmentFile=/opt/kairo-web/app/.env
ExecStart=/opt/kairo-web/app/.venv/bin/uvicorn kairo_web.main:app --host 127.0.0.1 --port 8001
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

`systemctl enable --now kairo-web`.

### 11.4 Caddy (`/etc/caddy/Caddyfile`)

```
kairo.example.com {
    reverse_proxy 127.0.0.1:8001
    encode zstd gzip
}
```

`systemctl reload caddy`. Caddy fetches a Let's Encrypt cert automatically.

### 11.5 Backups

`/etc/cron.d/kairo-backup`:

```
0 3 * * * kairo /opt/kairo-web/app/scripts/backup.sh
```

`scripts/backup.sh` runs `sqlite3 kairo.db ".backup /opt/kairo-web/backups/kairo-$(date +\%F).db"` and rotates files older than 14 days. Optionally `rclone copy` to off-site (S3, B2, Google Drive) — strongly recommended.

### 11.6 Updates

```bash
cd /opt/kairo-web/app
git pull
.venv/bin/pip install -e .
.venv/bin/alembic upgrade head
sudo systemctl restart kairo-web
```

---

## 12. Testing

- `pytest` for the parser, rollover, digest builders, and route smoke tests (using FastAPI's `TestClient`).
- Playwright for one or two end-to-end happy-path flows (login → add task via capture bar → complete → see in evening digest preview).
- Pre-commit hooks: ruff + mypy (already familiar from v1).

Coverage target: 80% on `services/`, lower elsewhere. Don't chase coverage on view code.

---

## 13. Observability

- Structured logging via `structlog` to stdout; systemd captures into journald.
- `/healthz` endpoint returns `{ok: true}` plus DB ping.
- Optional: a single Sentry project for error tracking (free tier).
- Rotation: journald defaults are fine for a single-user app.

---

## 14. Security notes

- Magic-link tokens: 32 bytes random, signed, single-use, 15-minute expiry.
- Session cookies: `HttpOnly`, `Secure`, `SameSite=Lax`, server-side session table so revocation is possible.
- Rate-limit `/login` (e.g. 5 requests/IP/hour) via a small in-memory limiter; SlowAPI works.
- HTTPS enforced via Caddy.
- SQLite file `0600` owned by `kairo` user. Backups same.
- No PII beyond owner's email and task content; nothing here warrants encryption-at-rest beyond filesystem perms.

---

## 15. Migrating from Kairo v1

A one-off CLI command imports the existing `~/.kairo/tasks.db` into a chosen Kairo Web workspace.

```bash
kairo-web migrate-v1 \
  --source ~/.kairo/tasks.db \
  --workspace fulltime \
  [--dry-run]
```

Behavior:

- Reads all tasks from v1's `tasks` table (and any related tables for tags/projects/estimates).
- Writes them into the chosen workspace, preserving: title, description, project, estimate, status, position, iso_year/iso_week, completion timestamp.
- Tags are recreated per-workspace; if a tag with the same name already exists in the target workspace, reused.
- Inbox tasks (week IS NULL in v1) land in the workspace's inbox.
- `--dry-run` prints a summary without writing.
- Idempotent guard: imports are skipped if the target workspace already has a row in a `migration_log` table for the source DB path.

The script is intentionally narrow: it targets v1's exact schema. It does not try to be a generic importer.

---

## 16. Out-of-scope (for this spec)

- Multi-user, sharing, ACLs.
- Real-time sync.
- Calendar, Slack, third-party integrations.
- AI-assisted features.

These are addressed (or deferred) in `DESIGN.md` §11 and §9.3.
