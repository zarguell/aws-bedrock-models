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
        _, models, _ = ssg.load_store(tmp)
        assert [m["model"] for m in ssg.env_models(models, "us-ew")] == [
            "Claude 3 Haiku", "Llama 3.3 70B Instruct"]
        assert [m["model"] for m in ssg.env_models(models, "govcloud")] == ["Claude 3 Haiku"]
        assert ssg.env_counts(models) == {"us-ew": 2, "govcloud": 1, "dod": 1}


def test_feed_items_newest_first_and_per_env():
    with tempfile.TemporaryDirectory() as tmp:
        _store(tmp)
        _, _, changes = ssg.load_store(tmp)
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
        _, _, changes = ssg.load_store(tmp)
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
