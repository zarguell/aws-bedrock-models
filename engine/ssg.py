#!/usr/bin/env python3
"""AWS Bedrock models FedRAMP/DoD tracker — static site generator.

Architecture twin of carmens-names' engine/ssg.py: all markup lives in
templates/, this file is logic only. Reads the committed data store
(data/inventory.json + data/changes.json + data/source.json) and renders
the Jinja2 templates into the repository root (GitHub Pages serves the
root via the site-deploy workflow).

Data store (committed by the cronman bedrock-models job; git history of
data/ is the audit trail):
  data/source.json     {source_url, source_last_updated, baseline_date, checked_at}
  data/inventory.json  {models: [{family, model,
                          envs: {<slug>: {available: bool, first_seen: YYYY-MM-DD|null}}}]}
  data/changes.json    [{date, type, ...}] oldest first; the first entry is
                       always the baseline event, later entries are per-model
                       per-environment additions (and removals).

Outputs:
  index.html                   latest changes + per-environment counts
  env/<slug>/index.html        per-environment inventory (available models only)
  history/index.html           full change log, newest first
  feeds/index.html             subscribe page for the four feeds
  feeds/feed-all.xml           every addition + baseline
  feeds/feed-<slug>.xml        per-environment feed (baseline + that env's additions)
  models.json                  machine-readable dump (inventory + changes + source)
  about/index.html             methodology, in website form
  404.html, robots.txt, sitemap.xml, style.css

Usage: python3 engine/ssg.py   (from the repo root; also importable —
       build(repo_root, out_dir) is used by engine/test_ssg.py)
"""
import html
import json
import os
import re
import sys
from datetime import date, datetime

from jinja2 import Environment, FileSystemLoader, select_autoescape

ENGINE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(ENGINE)                       # repo root = Pages root
TMPL_DIR = os.path.join(ENGINE, "templates")
DATA_DIR = os.path.join(ROOT, "data")

BASE_URL = "https://zarguell.github.io/aws-bedrock-models"
SITE_NAME = "AWS Bedrock Models — FedRAMP & DoD Tracker"
SOURCE_URL = "https://aws.amazon.com/compliance/services-in-scope/FedRAMP/amazon-bedrock-models/"
MANIFEST_NAME = ".build-manifest"          # rendered-path ledger for stale pruning

ENVS = (
    ("us-ew", "U.S. E/W — FedRAMP Class C", "U.S. East/West"),
    ("govcloud", "U.S. GovCloud — FedRAMP Class D", "GovCloud"),
    ("dod", "DoD — CSP SRG IL4/IL5", "DoD"),
)
ENV_LABEL = dict((s, l) for s, l, _ in ENVS)
FEED_MAX_ITEMS = 100
HISTORY_ON_INDEX = 30


# ── store ────────────────────────────────────────────────────────────────────
def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def load_store(repo_root=None):
    repo_root = repo_root or ROOT
    data = os.path.join(repo_root, "data")
    with open(os.path.join(data, "source.json")) as f:
        source = json.load(f)
    with open(os.path.join(data, "inventory.json")) as f:
        inventory = json.load(f)
    changes = load_json(os.path.join(data, "changes.json"), [])
    frontier = load_json(os.path.join(data, "frontier.json"), [])
    models = sorted(inventory.get("models", []),
                    key=lambda m: (m.get("family", ""), m.get("model", "")))
    return source, models, changes, frontier


def env_models(models, slug):
    """Available models in one environment, family/model sorted."""
    return [m for m in models if m.get("envs", {}).get(slug, {}).get("available")]


def env_counts(models):
    return {slug: len(env_models(models, slug)) for slug, _, _ in ENVS}


def drought_per_env(counts, changes):
    """Days-since-last-authorization per environment + latest additions.

    The baseline batch anchors environments with no later additions (it is
    the last known authorization batch, not a gap in tracking).
    """
    baseline = changes[0] if changes and changes[0].get("type") == "baseline" else None
    anchor = baseline["date"] if baseline else None
    out = {}
    for slug, _, _ in ENVS:
        added = [c for c in changes
                 if c.get("type") == "added" and c.get("env") == slug]
        out[slug] = {
            "since": added[-1]["date"] if added else anchor,
            "latest": list(reversed(added[-5:])),
            "count": counts.get(slug, 0),
        }
    return out


def lag_days(released, first_seen):
    """Release-to-authorization lag in days (both historical dates; static)."""
    if not released or not first_seen:
        return None
    return (date.fromisoformat(first_seen) - date.fromisoformat(released)).days


def feed_items(changes, slug=None):
    """Newest-first feed items: baseline anchor + additions (optionally one env)."""
    items = [c for c in changes
             if c.get("type") in ("baseline", "added")
             and (slug is None or c.get("type") == "baseline" or c.get("env") == slug)]
    return list(reversed(items))[:FEED_MAX_ITEMS]
    """Newest-first feed items: baseline anchor + additions (optionally one env)."""
    items = [c for c in changes
             if c.get("type") in ("baseline", "added")
             and (slug is None or c.get("type") == "baseline" or c.get("env") == slug)]
    return list(reversed(items))[:FEED_MAX_ITEMS]


# ── presentation helpers (exposed to templates) ─────────────────────────────
def slugify(s):
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "model"


def frontier_slug(display):
    """URL slug for a frontier model (shared by gaps links, timer routes, sitemap)."""
    return slugify(display)


def model_slug(family, model):
    return slugify(f"{family}-{model}")


def fmt_date(iso, fmt="%B %-d, %Y"):
    return datetime.strptime(iso, "%Y-%m-%d").strftime(fmt) if iso else ""


def fmt_med(iso):
    """Short date that always carries the year: 'Jan 3, 2026'."""
    return fmt_date(iso, "%b %-d, %Y")


def esc(s):
    return html.escape(s or "", quote=True)


def item_title(item):
    if item.get("type") == "baseline":
        return f"Baseline: {item.get('total_models', '?')} tracked models ({fmt_med(item['date'])})"
    env = ENV_LABEL.get(item.get("env"), item.get("env", ""))
    return f"New in {env}: {item.get('model')} ({item.get('family')})"


def item_guid(item, index):
    if item.get("type") == "baseline":
        return f"{BASE_URL}/history/#baseline-{item['date']}"
    return (f"{BASE_URL}/history/#added-{item['date']}-"
            f"{item.get('env')}-{model_slug(item.get('family', ''), item.get('model', ''))}")


def prune_stale(out, manifest_path, current):
    """Delete files the previous build rendered but this one didn't.

    The manifest (.build-manifest) lists every file the last build wrote.
    Anything listed there but absent from `current` is a stale artifact
    (e.g. a removed env page). Empty parent directories are removed up to
    `out`. First build after adoption has no manifest, so this is a no-op.
    """
    try:
        with open(manifest_path) as f:
            previous = [ln.strip() for ln in f if ln.strip()]
    except FileNotFoundError:
        return 0
    current_set = set(current)
    out_abs = os.path.abspath(out)
    removed = 0
    for rel in previous:
        if rel in current_set:
            continue
        p = os.path.abspath(os.path.join(out_abs, rel))
        if not p.startswith(out_abs + os.sep):
            continue                      # path escape guard, never touch outside out
        if os.path.isfile(p):
            os.unlink(p)
            removed += 1
        d = os.path.dirname(p)
        while d != out_abs and d.startswith(out_abs + os.sep):
            try:
                os.rmdir(d)               # succeeds only when empty
            except OSError:
                break
            d = os.path.dirname(d)
    return removed


# ── build ────────────────────────────────────────────────────────────────────
def build(repo_root=None, out_dir=None):
    repo_root = repo_root or ROOT
    out = os.path.abspath(out_dir or repo_root)
    env = Environment(
        loader=FileSystemLoader(TMPL_DIR),
        autoescape=select_autoescape(["html", "xml"]),
    )
    env.globals.update(
        site_name=SITE_NAME, base_url=BASE_URL, source_url=SOURCE_URL,
        envs=ENVS, env_label=ENV_LABEL,
        fmt_date=fmt_date, fmt_med=fmt_med,
        slugify=slugify, model_slug=model_slug, esc=esc,
        frontier_slug=frontier_slug,
        item_title=item_title, item_guid=item_guid,
        lag_days=lag_days, days_between=days_between,
        generated=iso_now(), rss_pubdate=rss_pubdate,
    )

    source, models, changes, frontier = load_store(repo_root)
    if not models:
        raise SystemExit("no model inventory found — nothing to build")
    counts = env_counts(models)
    changes_desc = list(reversed(changes))
    per_env = {slug: env_models(models, slug) for slug, _, _ in ENVS}
    feeds = {"all": feed_items(changes)}
    feeds.update({slug: feed_items(changes, slug) for slug, _, _ in ENVS})

    ctx = {
        "source": source,
        "models": models,
        "total_models": len(models),
        "counts": counts,
        "changes": changes_desc,
        "per_env": per_env,
        "feeds": feeds,
        "baseline": changes[0] if changes and changes[0].get("type") == "baseline" else None,
        "frontier": frontier,
        "drought": drought_per_env(counts, changes),
        "today": today_iso(),
        "timer_pages": [],
    }

    def url(rel):
        return f"{BASE_URL}/{rel.lstrip('/')}"

    def render(template, path, **extra):
        c = dict(ctx)
        c["r"] = "../" * path.count("/")
        c.update(extra)
        dest = os.path.join(out, path)
        os.makedirs(os.path.dirname(dest) or out, exist_ok=True)
        with open(dest, "w") as f:
            f.write(env.get_template(template).render(**c))
        return dest

    written = []
    written.append(render("index.html", "index.html",
                          latest_changes=changes_desc[:HISTORY_ON_INDEX]))
    for slug, label, short in ENVS:
        written.append(render("env.html", os.path.join("env", slug, "index.html"),
                              env_slug=slug, env_label=label, env_short=short,
                              env_list=per_env[slug]))
    written.append(render("history.html", os.path.join("history", "index.html")))
    written.append(render("gaps.html", os.path.join("gaps", "index.html")))
    timer_pages = []
    for e in frontier:
        mslug = frontier_slug(e["display"])
        for slug, label, short in ENVS:
            if e.get("envs", {}).get(slug, {}).get("available"):
                continue  # timers are for gaps only; closures retire the page
            rel = os.path.join("gaps", mslug, slug, "index.html")
            written.append(render(
                "timer.html", rel, e=e,
                env_slug=slug, env_label=label, env_short=short,
                page_url=url(f"gaps/{mslug}/{slug}/"),
                wait_days=days_between(today_iso(), e["released"])))
            timer_pages.append(f"gaps/{mslug}/{slug}/")
    ctx["timer_pages"] = timer_pages
    written.append(render("feeds_index.html", os.path.join("feeds", "index.html")))
    for slug, items in [("all", feeds["all"])] + [(s, feeds[s]) for s, _, _ in ENVS]:
        c = dict(ctx, r="", feed_items_list=items,
                 feed_url=url(f"feeds/feed-{slug}.xml"),
                 feed_title=("All environments" if slug == "all"
                             else ENV_LABEL[slug]))
        dest = os.path.join(out, "feeds", f"feed-{slug}.xml")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w") as f:
            f.write(env.get_template("feed.xml").render(**c))
        written.append(dest)
    written.append(render("models.json", "models.json"))
    written.append(render("about.html", os.path.join("about", "index.html")))
    written.append(render("style.css", "style.css"))
    written.append(render("404.html", "404.html"))
    written.append(render("robots.txt", "robots.txt"))
    written.append(render("sitemap.xml", "sitemap.xml"))

    # Prune artifacts of previous builds that this one didn't render, then
    # record this build's manifest for the next run.
    rel_written = sorted(os.path.relpath(p, out) for p in written)
    pruned = prune_stale(out, os.path.join(out, MANIFEST_NAME), rel_written)
    with open(os.path.join(out, MANIFEST_NAME), "w") as f:
        f.write("\n".join(rel_written) + "\n")

    print(f"rendered {len(written)} files, pruned {pruned} stale "
          f"({len(models)} models, {len(changes)} change events) -> {out}")
    return written


def today_iso():
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("America/New_York")).date().isoformat()


def days_between(later_iso, earlier_iso):
    """Whole days between two YYYY-MM-DD dates (server-side fallback; JS refreshes)."""
    if not later_iso or not earlier_iso:
        return None
    return (date.fromisoformat(later_iso) - date.fromisoformat(earlier_iso)).days


def iso_now():
    from email.utils import format_datetime
    from zoneinfo import ZoneInfo
    return format_datetime(datetime.now(ZoneInfo("America/New_York")))


def rss_pubdate(date_iso):
    """RFC-822 pubDate anchored to the morning check, 08:00 US/Eastern."""
    from email.utils import format_datetime
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    dt = datetime.strptime(date_iso, "%Y-%m-%d").replace(hour=8, minute=0, tzinfo=et)
    return format_datetime(dt)


def main():
    build()
    return 0


if __name__ == "__main__":
    sys.exit(main())
