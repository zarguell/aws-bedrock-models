# AGENTS.md

Notes for anyone (AI agent or human) changing this repo. Read this first:
it covers the things that cost someone time already.

## What this is

An unofficial tracker of which Amazon Bedrock models are certified for
FedRAMP Class C (U.S. East/West), FedRAMP Class D (U.S. GovCloud), and
DoD CSP SRG IL4/IL5. A private daily scraper (cronman `bedrock-models`
job — **not** in this repo) commits data changes; the scraper itself lives
in the cronman repo. Data arrives as git commits to `data/`.
`engine/ssg.py` (small Jinja2 SSG) renders the entire site into the repo
root; GitHub Actions tests + builds on every push and a daily cron, then
deploys to GitHub Pages.

## Layout

- `data/source.json`: source URL, the AWS "Last updated" string, baseline date.
- `data/inventory.json`: every tracked model with per-environment
  `{available, first_seen}`. `first_seen` is the date availability was first
  detected (baseline models carry the baseline date); `null` means not available.
- `data/changes.json`: oldest-first event log. Entry 0 is always the baseline
  event; later entries are `added` (one per model per environment) and `removed`.
  The RSS feeds carry the baseline + additions only.
- `engine/ssg.py`: all build logic. **All markup lives in
  `engine/templates/`**; this file should stay logic-only.
- Rendered output sits in the repo ROOT (`index.html`, `env/`, `feeds/`,
  `history/`, `about/`, `models.json`, …) and is
  **gitignored build output. Never hand-edit it**; edit templates and rebuild.

## Commands

```bash
python3 -m venv .venv && .venv/bin/pip install jinja2   # once
.venv/bin/python engine/test_ssg.py   # contract tests (CI gate)
.venv/bin/python engine/ssg.py        # renders site into repo root
python3 -m http.server 8000           # then browse localhost:8000
```

## Gotchas

- **Tests really execute.** `engine/test_ssg.py` has a `main()` that runs every
  `test_*` function. Keep it dependency-light (no pytest requirement) and make sure
  new tests actually fail when they should.
- **Relative links need the `{{ r }}` prefix** (e.g. `{{ r }}env/us-ew/index.html`).
  It's computed per page from path depth in `render()`. Feeds use absolute URLs.
- **Feed GUIDs must be stable and unique per event** (`item_guid()` in ssg.py):
  feed readers dedupe on GUID, so a reused GUID silently hides a new model.
  Never change the GUID scheme without a comment explaining why.
- **Stale outputs are pruned** via `.build-manifest` (gitignored): remove a data
  entry and the old row vanishes on the next build.
- **Absolute URLs are hardcoded** (`BASE_URL` in ssg.py) for RSS/sitemap
  links; update there if the site ever moves.
- **Removals are history-only**: the feeds intentionally exclude `removed`
  events. If that policy ever changes, update `feed_items()` AND the contract
  tests AND the about page in the same commit.
- **Date helpers**: user-facing dates always include the year → use `fmt_med`.

## Data policy

`first_seen` is a detection date (the morning the scraper saw it), not an AWS
release date — AWS publishes no per-model dates. Never backfill a `first_seen`
you didn't observe; blanks over incorrect.
