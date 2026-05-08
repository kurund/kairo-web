# Kairo Web — Design Document

**Version:** 0.1 (draft)
**Date:** 2026-05-05

---

## 1. Background

Kairo v1 is a terminal-based weekly task manager (Python, Textual TUI + Click CLI, SQLite at `~/.kairo/tasks.db`). It is well-featured — ISO-week planning, inbox, tags, projects, time estimates, position-based ordering, auto-rollover, weekly reports — but it is not being used in practice.

The root cause is **visibility**, not features. A terminal app requires the user to remember it exists; tasks instead pile up in head, paper, Slack, and email because those surfaces are already in front of the user.

Kairo Web rebuilds the same conceptual model on a surface that intrudes on attention without being annoying: a pinned browser tab and a daily email digest.

---

## 2. Goals

- Make Kairo unmissable in the user's day without adding nag-app friction.
- Support three life contexts (Full-time work, Consulting, Personal) with clean separation but a single login.
- Preserve the planning model the user already likes (ISO weeks, inbox, position ordering, auto-rollover, tags/projects/estimates).
- Keep the stack small enough that a single person can build, host, and evolve it on weekends.
- Make capture friction near-zero from inside the app; defer cross-channel capture (Slack, email) until v1.1.

## 3. Non-goals (for MVP)

- Multi-user / team features.
- Native mobile apps. The web app should be mobile-friendly enough to serve as a PWA, but no separate iOS/Android binaries.
- Calendar sync (Google/Outlook). Tempting, but a v2 problem.
- AI-powered task generation, summarization, or auto-prioritization. Add only after the core habit forms.
- Real-time multi-device sync via WebSockets. Server-render + page reload is fine for one user.

---

## 4. User profile

A single user with three concurrent contexts:

- **Full-time work** (engineering / leadership tasks at the day job)
- **Consulting** (client work, separate streams)
- **Personal / life admin** (errands, family, household, recurring chores)

Tasks originate everywhere — Slack/email, meetings, while coding, while away from desk — but the user only needs to *access* tasks from the **browser** (desktop primarily; mobile via the same web app for occasional checks). No need for terminal, IDE, or native-app surfaces.

The dominant failure mode is "I forgot the app existed." The dominant success criterion is "I check Kairo without thinking about it."

---

## 5. Product principles

1. **Visibility > features.** Every design decision should make the app harder to forget.
2. **Workspaces are walls, not filters.** Switching contexts should feel like switching apps, not toggling a checkbox.
3. **Capture is a single keystroke.** If adding a task takes more than two seconds, the user will write it on paper instead.
4. **Weekly is the unit of planning. Daily is the unit of doing.** The week view is the home screen; the Today strip is the daily commitment.
5. **The email digest is a feature, not a notification.** Treat it like a small, well-designed daily product surface.
6. **Boring tech.** Server-rendered HTML, minimal JS. The app should be debuggable from `curl`.

---

## 6. Workspaces

Workspaces are user-defined and unbounded in number. **`kairo-web init` seeds a single `personal` workspace**; users add others (`work`, `consulting`, `side-project`, etc.) via `kairo-web add-workspace --slug=<slug> --name="<name>"`. Each workspace is a fully isolated namespace — its own tasks, projects, tags, weekly plans, statistics — selected via a top-bar switcher and reflected in the URL (`/w/<slug>/...`).

Workspaces do **not** share tasks. If a user wants a "global today" view across workspaces, that is an explicit v1.1 feature (see §11), not the default.

Each workspace has an accent color (a single hex stored on `workspace.color`) used for its tab underline, today-card left border, and "★ today" indicator. The `add-workspace` CLI auto-picks a color from a built-in palette by current workspace count, with a `--color=#hex` override. The badge background and text color are derived from the accent via HSL math, so any hex input produces a coherent set of three.

The workspace switcher shows badge counts: "Work · 4 due this week", "Personal · 2 overdue". This nudges users to switch when something needs attention.

A planned keyboard shortcut maps `1`–`9` to the first nine workspaces by display order; with arbitrary workspace counts the shortcut is no longer guaranteed to cover everything (see §11.2 open questions).

---

## 7. The primary screen (week view)

A single page, reachable at `/w/<workspace>/week/<year>-W<week>`. Loaded when the pinned tab is opened. Top to bottom:

### 7.1 Header

- Workspace switcher (left)
- Current week label with prev / today / next navigation (center)
- Account menu (right)

### 7.2 Capture bar

A single text input pinned below the header. Always focusable with `/` from anywhere on the page.

Supports inline syntax for power-typing:

```
Fix login bug #urgent #auth @auth-rewrite ~2h
```

Parses to: title=`Fix login bug`, tags=`[urgent, auth]`, project=`auth-rewrite`, estimate=`2h`.

**Default destination is the inbox**, not the viewed week. Two submit buttons sit next to the input:

- **`+ Inbox`** (primary, dark) — Enter on the input also triggers this. The new task lands unscheduled in the workspace inbox for triage. This is the GTD-friendly default: capture cheaply now, decide where it belongs later.
- **`This week`** (secondary, outlined) — schedules the new task directly into the viewed ISO week. Use when you already know it belongs in this week.

This default reflects a deliberate choice to nudge a triage habit rather than letting the active week become a dumping ground. Tasks in the inbox are easy to move into a week later (one click in the inbox panel).

### 7.3 Today strip

A horizontal row of 3–7 tasks the user has explicitly committed to today. Tasks are added to Today with `t` (or drag). They remain in their assigned week — Today is a flag, not a separate location.

Why a strip, not a list: visual constraint forces a small daily commitment. Crossing them off mid-day feels good. Empty Today → soft prompt: "Pick today's plan."

### 7.4 Week table

Reuses the v1 table layout: position-ordered list with checkbox, title, tags, project, estimate. Inline edit on click. Keyboard navigation matches v1 (`j`/`k`, `J`/`K`, `c`, `e`, `d`, `v`).

Filter chips above the table: tag filter, project filter, status filter. Filter state persists per-workspace in localStorage.

### 7.5 Inbox panel

A collapsible right sidebar (or slide-in on narrow viewports). Shows unscheduled tasks for the current workspace. Press `i` to toggle. Drag-drop or keyboard `s` schedules an inbox task into the current week.

### 7.6 Stats footer

Open count, completed count, estimated hours, completed hours, completion percentage. Same as v1 left panel, simplified.

---

## 8. Daily email digest

Two opt-in emails per workspace. Configurable times; defaults below.

### 8.1 Morning digest (default 7:00 local)

Subject: `Tuesday May 5 — 6 open this week (8.5h)`

Body:

- Greeting + date
- Today's plan (the Today strip)
- Rest of the week (titles + estimates)
- One-click link back to the app

Designed to fit in a phone preview pane. No images, plaintext-friendly fallback.

### 8.2 Evening review (default 18:00 local)

Subject: `How'd today go? — 4/6 done`

Body:

- What got completed today
- What's still open from Today
- One-click links: "Roll the rest to tomorrow" / "Roll to next week" / "Leave as-is"

The evening email is the keystone habit-builder. Even a user who never opens the app gets a 10-second daily check-in.

### 8.3 Implementation notes

- Per-workspace toggle (user may want morning emails for Full-time only, etc.)
- Single sender domain, distinct `From` per workspace (`fulltime@kairo.example.com`, etc.) so they thread separately in the inbox
- One-click action links are signed magic-token URLs (no password needed)

---

## 9. Feature list

### 9.1 MVP (must-have)

| Area | Feature |
|---|---|
| Workspaces | User-defined; `init` seeds 'personal'; `add-workspace` CLI for more; switcher; per-workspace data isolation |
| Tasks | CRUD; title, description, tags (multi), project (single), estimate (hours), status, position |
| Planning | ISO-week view; prev/today/next navigation; inbox; Today strip |
| Ordering | Position-based, manual reorder via `J`/`K` |
| Auto-rollover | Sunday 23:59 local, incomplete tasks of the closing week move to the next week |
| Capture | Capture bar with inline syntax (`#tag`, `@project`, `~Nh`) |
| Filters | Filter by tag/project/status, persisted per workspace |
| Email | Morning digest, evening review, both opt-in per workspace |
| Auth | Single-user magic-link login with long-lived session cookie |
| Keyboard | Match v1 shortcuts: `a`/`e`/`c`/`d`/`v`/`j`/`k`/`J`/`K`/`g`/`f`/`i`/`t`/`s`/`/`/`1`/`2`/`3` |

### 9.2 v1.1 (next slice)

- **Recurring tasks** — schedule patterns: weekly / monthly / every N days. Critical for Personal.
- **Snooze** — `z` key sends a task to "tomorrow" / "next week" / "someday". (`s` is already the schedule-from-inbox shortcut.)
- **Notes per task** — markdown body, with a small editor.
- **Email-to-task** — forward to `kairo+work@yourdomain` → task in inbox.
- **Weekly review screen** — Friday afternoon view: completed, slipped, totals per project.
- **Soft streaks** — "12 days in a row you closed at least one task." No shame, no badges.

### 9.3 v2+ (explicitly deferred)

- Cross-workspace "global today" view
- Calendar (read-only) integration
- Slack capture
- Native mobile
- Multi-user / team features
- AI-assisted prioritization or generation

---

## 10. Success metrics

We are not building this to measure it, but a habit-formation product needs a few signals:

- **Daily active days per week** (target: 5+ within first month)
- **Task close-out rate** (% of tasks added that get completed within their assigned week — target: 60%+)
- **Time-to-capture** (instrumented in the capture bar — target: < 5s from `/` to Enter)
- **Email open rate** for evening review (target: 80%+ within first month — if low, the email content needs work)

---

## 11. Decisions and remaining open questions

### Decided

- **Email sending**: Resend free tier, sending from a subdomain of the deployment domain (e.g. `kairo.example.com`). SPF/DKIM/DMARC records added on that subdomain.
- **Migration from Kairo v1**: yes, migrate. A one-off CLI script (`kairo-web migrate-v1`) reads `~/.kairo/tasks.db` and imports tasks into a chosen workspace via a `--workspace` flag. The user will populate the other two workspaces manually as new tasks come in.

### Still open

1. **Which workspace receives v1 tasks?** — the migration script takes `--workspace` at runtime, so we don't need to decide until we run it. Default suggestion: `fulltime`, since v1 usage skewed toward work.
2. **Cross-workspace today view** — should v1.1 add a `/today` page that aggregates the Today strip across all workspaces? Risks blurring the workspace walls.
3. **Inbox per workspace vs global inbox** — current design has inbox per workspace. A global inbox could be the place where uncategorized captures land before being routed. Worth piloting after MVP.
4. **Mobile capture** — the web app will work on mobile, but is a true PWA install (with home-screen icon) worth the small extra build cost? Probably yes.

---

## 12. Build plan (suggested milestones)

Each milestone is roughly a weekend of focused work.

1. **Scaffold + auth + workspaces** — FastAPI app skeleton, SQLite, magic-link login, workspace switcher.
2. **Task CRUD + week view** — list, add, edit, complete, delete; week navigation; inbox.
3. **Capture bar + keyboard shortcuts + filters** — full keyboard parity with v1; capture bar parser.
4. **Today strip + auto-rollover** — Today flag, drag/keyboard, Sunday rollover job.
5. **Email digests** — morning + evening; one-click action links.
6. **Polish + deploy to Hostinger VPS** — Caddy reverse proxy, systemd service, HTTPS, backup script.

After MVP ships and the habit takes hold, evaluate v1.1 features in priority order: recurring tasks → snooze → notes → email-to-task → weekly review → streaks.

---

## 13. Naming

Keep **Kairo**. The meaning still fits and the brand has earned affection. Internally, refer to this as Kairo Web (or Kairo v2) when the distinction with the v1 terminal app matters. The v1 app stays installed and functional; Kairo Web is a fresh codebase, not an in-place upgrade.
