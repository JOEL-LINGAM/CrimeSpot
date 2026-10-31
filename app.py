"""CrimeScope dashboard entry point:  streamlit run app.py
The dashboard only READS Parquet written by the Spark pipeline (scripts/run_pipeline.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import streamlit as st

st.set_page_config(page_title="CrimeScope", page_icon="🛰️", layout="wide", initial_sidebar_state="expanded")
from dashboard.router import run_page, PAGE_TITLES  # noqa: E402


def _page(key):
    def _run():
        run_page(key)
    _run.__name__ = f"page_{key}"
    return _run


ICONS = {"overview": "📊", "map": "🗺️", "temporal": "⏱️", "category": "🧩", "hotspots": "🔥",
         "compare": "⚖️", "perf": "⚙️", "quality": "🧪"}
pages = [st.Page(_page(k), title=t, icon=ICONS[k], url_path=k, default=(k == "overview")) for k, t in PAGE_TITLES.items()]
st.navigation(pages).run()
