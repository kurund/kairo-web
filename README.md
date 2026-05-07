# Kairo Web

Single-user weekly task manager. FastAPI + SQLite + HTMX, server-rendered, runs on a small VPS.

The product motivation, feature scope, and architecture are documented separately:

- [`docs/DESIGN.md`](./docs/DESIGN.md) — product design, workspaces, primary screen, email digest, MVP/v1.1/v2 features.
- [`docs/TECH_SPEC.md`](./docs/TECH_SPEC.md) — stack, schema, routes, auth, capture parser, deployment.
- [`CLAUDE.md`](./CLAUDE.md) — guidance for Claude Code when working in this repo.

## Quick start (local)

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
# Install
uv sync --all-extras

# Configure
cp .env.example .env
# edit .env — at minimum, set KAIRO_SECRET_KEY

# Initialize database
uv run alembic upgrade head
uv run kairo-web init

# Run
uv run uvicorn kairo_web.main:app --reload --port 8001
```

Open http://localhost:8001/healthz — should return `{"ok": true}`.

## CLI

```bash
uv run kairo-web --help
uv run kairo-web init                                # seed default 'personal' workspace + owner user
uv run kairo-web add-workspace --slug=work --name="Work"
uv run kairo-web list-workspaces
uv run kairo-web migrate-v1 --workspace personal     # import from ~/.kairo/tasks.db
uv run kairo-web rollover                            # manual Sunday rollover
```

## Tests

```bash
uv run pytest
```

## Deployment

See [`docs/TECH_SPEC.md`](./docs/TECH_SPEC.md) §11 for the Hostinger VPS recipe (Caddy + systemd + cron backups). The relevant config files live under `deploy/`.

## License

[AGPL-3.0-or-later](./LICENSE). If you run a modified version of Kairo Web on a server and let other people use it over a network, you must make your source code available to those users.
