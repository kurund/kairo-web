# CLAUDE.md

Guidance for Claude Code (and other AI assistants) working in this repository.

## Project overview

Kairo Web is a single-user weekly task manager — a web evolution of the v1 terminal app at `~/src/kairo/kairo`. It's a server-rendered FastAPI + SQLite + HTMX app that the user keeps as a pinned browser tab plus daily email digest.

**Always read these before non-trivial changes:**

- [`docs/DESIGN.md`](./docs/DESIGN.md) — product motivation, workspace model, primary screen, email digest, MVP/v1.1/v2 feature breakdown.
- [`docs/TECH_SPEC.md`](./docs/TECH_SPEC.md) — full stack, schema, route inventory, auth flow, capture-parser grammar, Hostinger VPS deploy recipe.

These are the source of truth. If a change contradicts them, update the docs in the same change.

## Development commands

```bash
# Install (Python 3.10+; production targets 3.12).
uv sync --all-extras

# First-time: configure env, set up DB, seed default workspace + owner user.
cp .env.example .env  # then set KAIRO_SECRET_KEY
uv run alembic upgrade head
uv run kairo-web init
# Optionally add more workspaces:
uv run kairo-web add-workspace --slug=work --name="Work"

# Run.
uv run uvicorn kairo_web.main:app --reload --port 8001

# Tests.
uv run pytest                 # 32 tests (19 capture parser + 13 routes)

# CLI.
uv run kairo-web --help
uv run kairo-web init                                  # idempotent (seeds 'personal')
uv run kairo-web add-workspace --slug=work --name="Work"
uv run kairo-web list-workspaces
uv run kairo-web migrate-v1 --workspace personal       # import from ~/.kairo/tasks.db
uv run kairo-web migrate-v1 --workspace personal --dry-run

# Lint / format.
uv run ruff check src tests
uv run ruff format src tests
```

The `Makefile` has shortcuts (`make dev`, `make test`, `make migrate`, `make init`, `make clean`).

## Architecture

### Layout

```
src/kairo_web/
  main.py            # FastAPI app factory, /healthz, static + router wiring
  config.py          # pydantic-settings, .env-driven
  db.py              # SQLModel engine + get_session dependency
  models.py          # SQLModel data classes (table=True)
  paths.py           # PACKAGE_DIR, TEMPLATE_DIR, STATIC_DIR
  utils.py           # iso-week math, tag color picker, hour formatting
  workspace_meta.py  # color palette + HSL math (derive bg/fg from accent hex)
  cli.py             # Click CLI: init, migrate-v1, rollover
  routes/
    pages.py         # GET /, /login, /w/{slug}/week/{ywk}, /w/{slug}/inbox
    tasks.py         # POST mutation endpoints (HTMX, return partial)
    workspaces.py    # stub
    digest.py        # stub
  services/
    capture.py       # parse_capture() — inline syntax parser
    queries.py       # DB query helpers (get_workspace, get_week_tasks, …)
    rollover.py      # stub (milestone 4)
    digest.py        # stub (milestone 5)
  templates/
    base.html        # Tailwind CDN + htmx + Alpine
    week.html        # full page (header + capture bar + include partial)
    login.html       # stubbed login screen
    partials/
      week_main.html # swappable body — today strip + grid + stats footer
  static/
    app.js           # minimal page-level shortcuts (`/` focuses capture)
    app.css          # placeholder (real Tailwind build deferred)

alembic/             # migrations — env.py uses SQLModel.metadata
deploy/              # Caddyfile + systemd unit
scripts/             # backup.sh + seed_dev.py
docs/                # DESIGN.md + TECH_SPEC.md
tests/               # pytest — capture parser + route smoke tests
```

### Routing pattern

The app has **two peer pages per workspace**: a week view and an inbox view. Each has its own swappable partial (`#week-main` / `#inbox-main`) and its own paired set of mutation endpoints. They share the topbar (`partials/_topbar.html`) and capture bar (`partials/_capture.html`), differing only in which tab is active and what URL the capture form posts to.

| Method | Path | Returns |
|---|---|---|
| GET | `/` | redirect to `/w/<default-workspace>/week/<current>` |
| GET | `/login` | login page (stub) |
| GET | `/w/{slug}/week/{YYYY-WNN}` | week page |
| GET | `/w/{slug}/inbox` | inbox page |
| POST | `/w/{slug}/week/{YYYY-WNN}/tasks` | create — week partial |
| POST | `/w/{slug}/week/{YYYY-WNN}/tasks/{id}/complete\|today\|schedule\|move\|delete\|edit` | mutate — week partial |
| POST | `/w/{slug}/week/{YYYY-WNN}/rollover` | move open tasks to next week — week partial |
| POST | `/w/{slug}/inbox/tasks` | create in inbox — inbox partial |
| POST | `/w/{slug}/inbox/tasks/{id}/complete\|edit\|delete` | mutate — inbox partial |
| POST | `/w/{slug}/inbox/tasks/{id}/schedule` | move to current ISO week — inbox partial |
| GET | `/healthz` | `{"ok": true, "db": true}` |

**Week endpoints embed `ywk` in the path; inbox endpoints don't have a week to embed.** Mutation endpoints reuse the path context to know which partial to re-render. Filters (and inbox sort) are extracted from the `HX-Current-URL` header so HTMX mutations preserve them automatically.

### HTMX flow

Mutations return either `partials/week_main.html` (replacing `#week-main`) or `partials/inbox_main.html` (replacing `#inbox-main`), depending on which page the user is on. The shared **topbar** (`partials/_topbar.html`) and **capture bar** (`partials/_capture.html`) live **outside** the swappable region so they stay stable + the input stays focused across swaps.

Context builders in `view_context.py`:

- `build_week_context(...)` — feeds `week.html` and `partials/week_main.html`
- `build_inbox_context(...)` — feeds `inbox.html` and `partials/inbox_main.html`

Both produce a dict with the same shape keys consumed by the topbar (`active_tab`, `inbox_count`, `inbox_url`, `week_url_for_tab`, `workspaces`, etc.) so the shared partials don't care which page is rendering.

## Key patterns and conventions

### Workspaces are walls, not filters

Each workspace is a fully isolated namespace — its own tasks, tags, projects, weekly plans. Cross-workspace queries should be rare and explicit (only the badge-count query in `queries.get_workspace_badges` aggregates across workspaces). Workspace count is unbounded — `init` seeds 'personal'; the user adds more via `kairo-web add-workspace`.

### Position-based ordering — NOT priority

Tasks have a `position` integer field, auto-assigned `MAX(position) + 1` per `(workspace_id, iso_year, iso_week)` bucket. The inbox uses a separate sequence (where `iso_year IS NULL`). Manual reordering swaps positions via `tasks.py::move_task`. **Do not add a `priority` field.**

### Inbox vs scheduled

- Inbox: `iso_year IS NULL AND iso_week IS NULL` (both NULL together; enforced by check constraint `inbox_or_scheduled`).
- Scheduled: both fields set to a valid ISO year/week.
- Toggle: `tasks.py::toggle_schedule` — moves between the two states. Inbox tasks always have `is_today = false`.

### Today is a flag

`Task.is_today` is a boolean flag on the existing row, not a separate location. A "today" task still lives in its assigned week. Cleared automatically when the task is moved to inbox or deleted. (A scheduled job to clear `is_today` at midnight local is a future addition — not yet wired.)

### Tag scope is per-workspace

Tags are scoped per workspace — `personal/urgent ≠ work/urgent`. Enforced by `UNIQUE (workspace_id, name)`. The `_ensure_tags` helper in `routes/tasks.py` does find-or-create.

### Tag colors

`utils.tag_color_for(name)` returns one of `red | teal | indigo | amber | pink | slate`. Hand-picked overrides for common semantic tags (`urgent` → red, `family` → pink, `bills` → amber); fallback is a deterministic char-sum hash so the same tag always renders the same color across page loads.

### Capture-bar grammar

See `services/capture.py` and the spec in [`docs/TECH_SPEC.md`](./docs/TECH_SPEC.md) §6.

```
Fix login bug #urgent #auth @auth-rewrite ~2h
```

- `#word` → tag (lowercased; only `[A-Za-z0-9_-]+` allowed; invalid tag silently dropped).
- `@word` → project (last `@token` wins; `_` becomes space).
- `~Nh` / `~N.Nh` / `~Nm` → estimate (always normalized to hours, float).
- Doubled marker (`##`, `@@`, `~~`) is a literal `#`/`@`/`~` in the title.
- Marker order is irrelevant.

19 unit tests in `tests/test_capture.py`. **Add a test for any new escape rule or syntax extension.**

### Capture default: follows the active tab

The POST `/w/{slug}/week/{ywk}/tasks` and `/w/{slug}/inbox/tasks` endpoints both read a `destination` form field:

- `"inbox"` — task is created with `iso_year=NULL, iso_week=NULL` and lands in the workspace inbox for triage.
- `"week"` — task is scheduled directly into the viewed ISO week.

If `destination` is missing, the server defaults to `"inbox"` (defensive fallback for non-UI clients). In the UI, the **primary submit button matches the active tab**:

- **Week page** renders `+ This week` first (gets Enter) and `+ Inbox` second.
- **Inbox page** renders only `+ Inbox`.

This is driven by the `primary_destination` field in the view context (`"week"` or `"inbox"`). Each context also supplies its own `capture_placeholder` so the input hint reflects what Enter will do.

### Workspace switcher links

Workspace tabs in `week.html` are real `<a href="/w/{slug}/week/{ywk}">` — they preserve the viewed week when switching workspaces. Active tab uses an underline accent (`border-color: {{ ws.color_hex }}`).

### Models — no `from __future__ import annotations`

**Critical:** do NOT add `from __future__ import annotations` to `models.py`. SQLAlchemy 2.x relationship resolution needs type hints evaluated at class-creation time; PEP 563 string-evaluation breaks `list["Task"]` Relationship targets. Other modules can use it freely. Use `Optional[X]` and `List[X]` from `typing` rather than `X | None` / `list[X]` in the model fields.

### Migrations

Alembic with `render_as_batch=True` (required for SQLite ALTER TABLE support). `env.py` reads `KAIRO_DATABASE_URL` from env, falls back to `alembic.ini`. Target metadata is `SQLModel.metadata`.

When adding a new table or column:

1. Update `models.py`.
2. Generate: `uv run alembic revision --autogenerate -m "add foo"`.
3. **Inspect** the generated file — autogenerate is not perfect with SQLModel; it sometimes misses defaults or constraints.
4. Apply: `uv run alembic upgrade head`.

### Testing

- `tests/test_capture.py` — pure function tests.
- `tests/test_routes.py` — FastAPI `TestClient` against an in-memory SQLite. The `fresh_db` fixture drops + recreates schema per test using `SQLModel.metadata` (skipping Alembic) and seeds three workspaces (fulltime/consulting/personal) — purely so the tests can exercise multi-workspace behavior; production seeds only 'personal' via `kairo-web init`.
- Run a single test: `uv run pytest tests/test_routes.py::test_capture_creates_task_with_tags_project_estimate -v`
- No async tests yet (`asyncio_mode = "auto"` is set but unused; harmless warning).

### CLI

`cli.py` exposes:

- `init` — seeds the default `personal` workspace and the owner user from `KAIRO_OWNER_EMAIL`. Idempotent.
- `add-workspace --slug=<slug> --name="<name>" [--color=#hex]` — create a new workspace. If `--color` is omitted, picks the next slot from `workspace_meta.DEFAULT_PALETTE` based on current workspace count.
- `list-workspaces` — print all workspaces with slugs + accent colors.
- `migrate-v1 --workspace=<slug>` — imports v1's `~/.kairo/tasks.db` into a chosen workspace (the slug must exist; create it first with `add-workspace` if needed). Defensive about column existence; preserves timestamps; reads tags via the v1 `task_tags` join table; converts integer hours → float. `--dry-run` summarizes without writing.
- `rollover` — stub (full implementation in milestone 4).

## Configuration

Loaded via `config.Settings` (pydantic-settings):

| Var | Default | Purpose |
|---|---|---|
| `KAIRO_SECRET_KEY` | (required) | Signs magic-link + digest-action tokens |
| `KAIRO_DATABASE_URL` | `sqlite:///./dev.db` | SQLAlchemy URL |
| `KAIRO_BASE_URL` | `http://localhost:8001` | Used in email links |
| `KAIRO_OWNER_EMAIL` | (required) | Single-user owner identity |
| `KAIRO_TIMEZONE` | `Europe/London` | Used for ISO-week math + digest scheduling |
| `RESEND_API_KEY` | (empty in dev) | Empty → log emails to stdout instead of sending |
| `RESEND_FROM_DOMAIN` | `kairo.example.com` | From-address domain |
| `LOG_LEVEL` | `INFO` | structlog level |

## Deployment

Hostinger VPS via Caddy (auto-HTTPS) + systemd + `sqlite3 .backup` cron. Files in `deploy/`. Full recipe in [`docs/TECH_SPEC.md`](./docs/TECH_SPEC.md) §11.

## Build status (what's done vs what's next)

**Done:**

- Schema + Alembic migration (workspace, task, tag, task_tag, user, login_token, session, digest_action_token).
- Live week view with full DB-backed read path.
- HTMX mutation endpoints: create, complete, today, schedule (inbox↔week), move, delete.
- Capture-bar inline parser with 19 tests.
- Workspace switcher with real navigation; week prev/today/next.
- v1 importer (verified against actual v1 schema).
- ISO-week + tag color helpers.
- Deploy files (Caddyfile, systemd unit, backup script).
- Test suite: 32 passing.

**Stubbed (just placeholders that return TODO):**

- `routes/pages.py::login_post` — magic-link sending (milestone: auth).
- `routes/digest.py::act` — one-click email-action token consumption (milestone: digest).
- `services/rollover.py::rollover_workspace` — Sunday-night rollover (milestone: rollover).
- `services/digest.py::build_morning_digest`, `build_evening_digest` — email body builders (milestone: digest).
- `cli.py::rollover` — manual rollover trigger.

**Deferred to v1.1:**

- Recurring tasks (critical for the Personal workspace).
- Snooze (`z` key — see DESIGN §9.2).
- Markdown notes per task.
- Email-to-task forwarding.
- Weekly review screen.
- Soft streaks.

**Known sharp edges:**

- `app.css` is a placeholder; Tailwind ships via Play CDN, which is fine for dev but should be replaced with a real Tailwind CLI build before shipping to production. The `.gitignore` no longer excludes `app.css` — when the CLI build is added, switch the build output target so it doesn't clobber the placeholder.
- Auth is not enforced on any route. The app assumes single-user, local-first usage. Before VPS deploy, add session-cookie middleware and gate `/w/...` routes.

## Working with this repo

- Match existing prose-and-code style: types annotated on public functions, terse module docstrings, no defensive `try/except` around obvious things.
- Templates use Tailwind utility classes; inline styles are reserved for dynamic accent colors that can't be computed at build time.
- The capture parser is deliberately small and self-contained — keep it that way; new syntax features need a corresponding test.
- Mutation endpoints all share the same return contract (`week_main.html` partial). Don't introduce JSON endpoints unless there's a clear reason; HTMX-and-HTML is the working principle.
- When in doubt about user-facing behavior, mirror Kairo v1's TUI conventions (the user has muscle memory for those).
