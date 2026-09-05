"""Contract tests for the Bedrock FedRAMP/DoD tracker static site generator.

Run: python3 engine/test_ssg.py   (runs standalone — every test_* function
executes; also collectable by pytest)
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ssg


def _write(root, rel, content):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write(content)


def _store(tmp, models=None, changes=None, source=None):
    source = source or {"source_url": ssg.SOURCE_URL,
                        "source_last_updated": "August 25, 2026",
                        "baseline_date": "2026-08-25", "checked_at": "2026-09-04T12:00:00Z"}
    models = models if models is not None else [
        {"family": "Anthropic", "model": "Claude 3 Haiku",
         "envs": {"us-ew": {"available": True, "first_seen": "2026-08-25"},
                  "govcloud": {"available": True, "first_seen": "2026-08-25"},
                  "dod": {"available": True, "first_seen": "2026-08-25"}}},
        {"family": "Meta", "model": "Llama 3.3 70B Instruct",
         "envs": {"us-ew": {"available": True, "first_seen": "2026-08-25"},
                  "govcloud": {"available": False, "first_seen": None},
                  "dod": {"available": False, "first_seen": None}}},
    ]
    changes = changes if changes is not None else [
        {"date": "2026-08-25", "type": "baseline", "total_models": 2,
         "env_count": 3, "source_last_updated": "August 25, 2026"},
        {"date": "2026-09-04", "type": "added", "family": "xAI",
         "model": "Grok 4.3", "env": "govcloud",
         "env_label": "U.S. GovCloud — FedRAMP Class D"},
    ]
    _write(tmp, "data/source.json", json.dumps(source))
    _write(tmp, "data/inventory.json", json.dumps({"models": models}))
    _write(tmp, "data/changes.json", json.dumps(changes))


def test_slugify_deterministic_and_safe():
    assert ssg.slugify("Claude 3.5 Sonnet v2") == "claude-3-5-sonnet-v2"
    assert ssg.slugify("Llama 3 70B Instruct") == "llama-3-70b-instruct"
    assert ssg.slugify("") == "model"


def test_env_models_filters_unavailable():
    with tempfile.TemporaryDirectory() as tmp:
        _store(tmp)
        _, models, _, _ = ssg.load_store(tmp)
        assert [m["model"] for m in ssg.env_models(models, "us-ew")] == [
            "Claude 3 Haiku", "Llama 3.3 70B Instruct"]
        assert [m["model"] for m in ssg.env_models(models, "govcloud")] == ["Claude 3 Haiku"]
        assert ssg.env_counts(models) == {"us-ew": 2, "govcloud": 1, "dod": 1}


def test_feed_items_newest_first_and_per_env():
    with tempfile.TemporaryDirectory() as tmp:
        _store(tmp)
        _, _, changes, _ = ssg.load_store(tmp)
        all_items = ssg.feed_items(changes)
        assert [c["type"] for c in all_items] == ["added", "baseline"]
        assert [c["type"] for c in ssg.feed_items(changes, "govcloud")] == ["added", "baseline"]
        assert [c["type"] for c in ssg.feed_items(changes, "dod")] == ["baseline"]


def test_item_guid_unique_per_event():
    a = {"date": "2026-09-04", "type": "added", "family": "xAI",
         "model": "Grok 4.3", "env": "govcloud"}
    b = {"date": "2026-08-25", "type": "baseline"}
    assert ssg.item_guid(a, 0) != ssg.item_guid(b, 1)
    assert "govcloud" in ssg.item_guid(a, 0) and "grok-4-3" in ssg.item_guid(a, 0)


def test_build_end_to_end():
    with tempfile.TemporaryDirectory() as tmp:
        _store(tmp)
        out = os.path.join(tmp, "_site")
        written = ssg.build(repo_root=tmp, out_dir=out)
        rel = {os.path.relpath(p, out) for p in written}
        for expected in ("index.html", "models.json", "style.css", "404.html",
                         "robots.txt", "sitemap.xml",
                         "env/us-ew/index.html", "env/govcloud/index.html",
                         "env/dod/index.html", "history/index.html",
                         "gaps/index.html",
                         "feeds/index.html", "feeds/feed-all.xml",
                         "feeds/feed-us-ew.xml", "feeds/feed-govcloud.xml",
                         "feeds/feed-dod.xml", "about/index.html"):
            assert expected in rel, f"missing {expected}; got {sorted(rel)}"
        idx = open(os.path.join(out, "index.html")).read()
        assert "2 models tracked" in idx, "baseline change entry missing from index"
        assert "Grok 4.3" in idx, "addition change entry missing from index"
        ew = open(os.path.join(out, "env", "us-ew", "index.html")).read()
        assert "Claude 3 Haiku" in ew and "Llama 3.3 70B Instruct" in ew
        gov = open(os.path.join(out, "env", "govcloud", "index.html")).read()
        assert "Claude 3 Haiku" in gov and "Llama 3.3 70B Instruct" not in gov
        rss = open(os.path.join(out, "feeds", "feed-govcloud.xml")).read()
        assert "Grok 4.3" in rss and "Baseline" in rss
        dod_rss = open(os.path.join(out, "feeds", "feed-dod.xml")).read()
        assert "Grok 4.3" not in dod_rss and "Baseline" in dod_rss
        dump = json.load(open(os.path.join(out, "models.json")))
        assert dump["total_models"] == 2 and len(dump["changes"]) == 2
        # stale pruning: rebuild minus one env model still prunes nothing structural,
        # but a removed feed item must vanish from the feed
        _store(tmp, changes=[{"date": "2026-08-25", "type": "baseline",
                              "total_models": 2, "env_count": 3,
                              "source_last_updated": "August 25, 2026"}])
        ssg.build(repo_root=tmp, out_dir=out)
        rss2 = open(os.path.join(out, "feeds", "feed-govcloud.xml")).read()
        assert "Grok 4.3" not in rss2


def test_note_events_render_but_never_enter_feeds():
    with tempfile.TemporaryDirectory() as tmp:
        _store(tmp, changes=[
            {"date": "2026-08-25", "type": "baseline", "total_models": 2,
             "env_count": 3, "source_last_updated": "August 25, 2026"},
            {"date": "2026-09-05", "type": "note", "text": "Backfilled dates."},
        ])
        _, _, changes, _ = ssg.load_store(tmp)
        assert ssg.feed_items(changes) == [changes[0]]  # note excluded
        out = os.path.join(tmp, "_site")
        ssg.build(repo_root=tmp, out_dir=out)
        hist = open(os.path.join(out, "history", "index.html")).read()
        assert "Backfilled dates." in hist and "removed" not in hist.split("Backfilled")[0][-500:]
        idx = open(os.path.join(out, "index.html")).read()
        assert "Backfilled dates." in idx


def test_about_carries_prior_history_context():
    with tempfile.TemporaryDirectory() as tmp:
        _store(tmp)
        out = os.path.join(tmp, "_site")
        ssg.build(repo_root=tmp, out_dir=out)
        about = open(os.path.join(out, "about", "index.html")).read()
        assert "June 6, 2024" in about and "March 2024" in about
        assert "May 2025" in about and "not backdated" in about


def test_lag_days_and_days_between():
    assert ssg.lag_days("2026-07-09", "2026-08-25") == 47
    assert ssg.lag_days(None, "2026-08-25") is None
    assert ssg.lag_days("2026-08-25", None) is None
    assert ssg.days_between("2026-09-05", "2026-08-25") == 11
    assert ssg.days_between(None, "2026-08-25") is None


def test_drought_baseline_anchors_with_no_later_additions():
    changes = [{"date": "2026-08-25", "type": "baseline", "total_models": 2,
                "env_count": 3, "source_last_updated": "August 25, 2026"}]
    d = ssg.drought_per_env({"us-ew": 2, "govcloud": 1, "dod": 1}, changes)
    assert d["us-ew"] == {"since": "2026-08-25", "latest": [], "count": 2}
    changes.append({"date": "2026-09-04", "type": "added", "family": "xAI",
                    "model": "Grok 4.3", "env": "govcloud",
                    "env_label": "U.S. GovCloud — FedRAMP Class D"})
    d2 = ssg.drought_per_env({"us-ew": 2, "govcloud": 2, "dod": 1}, changes)
    assert d2["govcloud"]["since"] == "2026-09-04"
    assert d2["govcloud"]["latest"][0]["model"] == "Grok 4.3"
    assert d2["us-ew"]["since"] == "2026-08-25"  # still anchored on baseline


def _frontier_store(tmp):
    _store(tmp, changes=[
        {"date": "2026-08-25", "type": "baseline", "total_models": 2,
         "env_count": 3, "source_last_updated": "August 25, 2026"},
        {"date": "2026-09-04", "type": "added", "family": "Anthropic",
         "model": "Claude 3 Haiku", "env": "us-ew", "env_label": "E/W"},
    ])
    _write(tmp, "data/frontier.json", json.dumps([
        {"provider": "anthropic", "llm_key": "anthropic/claude-fable-5",
         "display": "Claude Fable 5", "released": "2026-06-07", "bedrock": None,
         "envs": {s: {"available": False, "first_seen": None}
                   for s in ("us-ew", "govcloud", "dod")}},
        {"provider": "openai", "llm_key": "openai/gpt-5.6", "display": "GPT-5.6",
         "released": "2026-07-09",
         "bedrock": {"family": "OpenAI", "model": "GPT 5.6"},
         "envs": {"us-ew": {"available": False, "first_seen": None},
                   "govcloud": {"available": True, "first_seen": "2026-08-25"},
                   "dod": {"available": True, "first_seen": "2026-08-25"}}},
    ]))


def test_gaps_page_renders_gaps_lags_droughts_and_live_counters():
    with tempfile.TemporaryDirectory() as tmp:
        _frontier_store(tmp)
        out = os.path.join(tmp, "_site")
        written = ssg.build(repo_root=tmp, out_dir=out)
        assert os.path.join(out, "gaps", "index.html") in written
        gaps = open(os.path.join(out, "gaps", "index.html")).read()
        assert "Claude Fable 5" in gaps and "GPT-5.6" in gaps
        assert "Why the wait?" in gaps
        assert "15425996-data-retention-practices-for-covered-models" in gaps
        assert "fedramp.gov/20x" in gaps
        assert "+47d" in gaps  # Jul 9 -> Aug 25 lag, static
        assert 'data-days-since="2026-06-07"' in gaps  # live waiting counter
        assert 'data-days-since="2026-09-04"' in gaps  # live drought counter
        assert "querySelectorAll" in gaps  # the updater script ships
        assert "Claude 3 Haiku" in gaps  # drought shortlist
        dump = json.load(open(os.path.join(out, "models.json")))
        assert len(dump["frontier"]) == 2 and dump["drought"]["us-ew"]["since"] == "2026-09-04"


def test_timer_pages_exist_only_for_gaps_with_meta_share_and_sitemap():
    with tempfile.TemporaryDirectory() as tmp:
        _frontier_store(tmp)
        out = os.path.join(tmp, "_site")
        written = ssg.build(repo_root=tmp, out_dir=out)
        rel = {os.path.relpath(p, out) for p in written}
        # fable: 3 gaps; gpt: us-ew gap only (govcloud/dod authorized)
        for expected in ("gaps/claude-fable-5/us-ew/index.html",
                         "gaps/claude-fable-5/govcloud/index.html",
                         "gaps/claude-fable-5/dod/index.html",
                         "gaps/gpt-5-6/us-ew/index.html"):
            assert expected in rel, f"missing {expected}"
        assert "gaps/gpt-5-6/govcloud/index.html" not in rel
        timer = open(os.path.join(out, "gaps", "claude-fable-5", "us-ew", "index.html")).read()
        assert 'property="og:title"' in timer and "claude-fable-5" in timer
        assert 'name="twitter:card"' in timer
        assert 'rel="canonical"' in timer
        assert 'id="share-btn"' in timer and "setInterval(tick, 1000)" in timer
        assert "data-released=" in timer and 'id="t-secs"' in timer
        assert "without authorization in" in timer
        gaps = open(os.path.join(out, "gaps", "index.html")).read()
        assert "gaps/claude-fable-5/us-ew/" in gaps
        sitemap = open(os.path.join(out, "sitemap.xml")).read()
        assert "gaps/claude-fable-5/dod/" in sitemap
        assert "gaps/gpt-5-6/govcloud/" not in sitemap


def test_build_refuses_empty_inventory():
    with tempfile.TemporaryDirectory() as tmp:
        _store(tmp, models=[])
        try:
            ssg.build(repo_root=tmp, out_dir=os.path.join(tmp, "_site"))
        except SystemExit:
            return
        raise AssertionError("build should refuse an empty inventory")


def main():
    fns = [globals()[k] for k in sorted(globals())
             if k.startswith("test_") and callable(globals()[k])]
    failed = 0
    for fn in fns:
        try:
            fn()
        except Exception as e:  # noqa: BLE001 — report, don't stop
            print(f"FAIL {fn.__name__}: {e}")
            failed += 1
        else:
            print(f"ok {fn.__name__}")
    print(f"{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
