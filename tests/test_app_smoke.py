"""Headless smoke tests: render every dashboard page with Streamlit's AppTest against REAL pipeline output.
They need data/processed/sample (run the pipeline on the synthetic sample first); otherwise they are SKIPPED.
They prove the pages run without exceptions, not that they look right in a browser."""
import json
from pathlib import Path
import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "data" / "processed" / "sample"
pytestmark = pytest.mark.skipif(not (SAMPLE / "cube_time").exists(), reason="run the pipeline with --tag sample first")
PAGES = ["overview", "map", "temporal", "category", "hotspots", "compare", "perf", "quality"]


def _page(key):
    from dashboard.router import run_page
    run_page(key)


def app(key):
    return AppTest.from_function(_page, args=(key,), default_timeout=180).run()


def clean(at):
    assert not at.exception, [e.value for e in at.exception]
    assert not at.error, [e.value for e in at.error]


@pytest.mark.parametrize("key", PAGES)
def test_every_page_renders_and_is_labelled_synthetic(key):
    at = app(key)
    clean(at)
    assert any("SYNTHETIC" in m.value for m in at.markdown)          # synthetic banner must always be visible


@pytest.mark.parametrize("mode", ["Density heatmap", "Grid cells", "Geographical clusters", "Category-specific"])
def test_map_modes(mode):
    at = app("map")
    at.radio(key="sample:mapmode").set_value(mode).run()
    clean(at)


def test_filters_apply_across_pages_and_reset():
    at = app("overview")
    at.multiselect(key="sample:cats").set_value(["Theft"]).run()
    at.slider(key="sample:hours").set_value((18, 23)).run()
    at.radio(key="sample:day").set_value("Weekend").run()
    clean(at)
    sidebar_text = " ".join(c.value for c in at.sidebar.caption)
    assert "categories" in sidebar_text and "hours" in sidebar_text and "weekend" in sidebar_text
    at.sidebar.button[0].click().run()                                  # reset
    clean(at)
    assert "none (full dataset)" in " ".join(c.value for c in at.sidebar.caption)


def test_narrow_filters_still_render_every_page():
    for key in PAGES:
        at = app(key)
        at.select_slider(key="sample:months").set_value(("2020-03", "2020-03")).run()
        at.multiselect(key="sample:cats").set_value(["Robbery"]).run()
        clean(at)


def test_pipeline_outputs_are_internally_consistent():
    q = json.loads((SAMPLE / "quality_report.json").read_text())
    m = json.loads((SAMPLE / "pipeline_metrics.json").read_text())
    assert q["reconciles"] and q["input_records"] == sum(q["excluded_by_reason"].values()) + q["duplicates_removed"] + q["retained_records"]
    assert m["retained_records"] == q["retained_records"]
    assert 0 < sum(m["stage_seconds"].values()) <= m["total_seconds"] + 0.5
    assert abs(m["records_per_second"] - m["input_records"] / m["total_seconds"]) < 1.0
    import pandas as pd
    for cube in ["cube_time", "cube_cell"]:
        assert pd.read_parquet(SAMPLE / cube).incidents.sum() == q["retained_records"]
    hot = pd.read_parquet(SAMPLE / "hotspots")
    assert hot["rank"].tolist() == list(range(1, len(hot) + 1)) and hot.incidents.is_monotonic_decreasing
    cl = pd.read_parquet(SAMPLE / "cell_clusters"); cells = pd.read_parquet(SAMPLE / "agg_cell")
    assert set(cl.cell_id) <= set(cells.cell_id)
