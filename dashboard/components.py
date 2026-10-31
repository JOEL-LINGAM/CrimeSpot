"""Shared UI pieces: theme CSS, KPI cards, Plotly styling, cached loaders, explanatory helpers."""
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from . import data as D

C = {"bg": "#0b1220", "card": "#111a2e", "line": "#1e2b45", "text": "#e5e7eb", "muted": "#94a3b8",
     "accent": "#22d3ee", "amber": "#f59e0b", "red": "#ef4444", "green": "#34d399", "violet": "#a78bfa"}
SEQ = [[0, "#0f172a"], [0.2, "#1e3a8a"], [0.45, "#0891b2"], [0.7, "#fde047"], [1, "#ef4444"]]
QUAL = ["#22d3ee", "#f59e0b", "#a78bfa", "#34d399", "#f472b6", "#60a5fa", "#fb923c", "#a3e635", "#e879f9", "#94a3b8"]

CSS = """
<style>
.block-container {padding-top: 1.4rem; padding-bottom: 3rem; max-width: 1500px;}
footer {visibility: hidden;}
.cs-hero {border:1px solid #1e2b45; border-radius:16px; padding:18px 22px; margin-bottom:14px;
  background: radial-gradient(1200px 200px at 0% 0%, rgba(34,211,238,.14), transparent 60%), #0f172a;}
.cs-hero h1 {margin:0; font-size:1.7rem; letter-spacing:.2px; color:#f8fafc;}
.cs-hero p {margin:.25rem 0 0 0; color:#94a3b8; font-size:.95rem;}
.cs-card {border:1px solid #1e2b45; border-radius:14px; padding:13px 16px; min-height:108px;
  background: linear-gradient(150deg,#111a2e,#0d1526);}
.cs-card .l {font-size:.72rem; text-transform:uppercase; letter-spacing:.09em; color:#94a3b8;}
.cs-card .v {font-size:1.75rem; font-weight:700; color:#f8fafc; line-height:1.25; word-break:break-word;}
.cs-card .v.sm {font-size:1.12rem; padding-top:.35rem;}
.cs-card .s {font-size:.78rem; color:#94a3b8;}
.cs-card .s.up {color:#f59e0b;} .cs-card .s.down {color:#34d399;}
.cs-banner {border:1px solid #b45309; background:rgba(245,158,11,.10); color:#fcd34d; border-radius:10px;
  padding:8px 14px; font-size:.85rem; margin-bottom:10px;}
.cs-note {border-left:3px solid #22d3ee; background:rgba(34,211,238,.06); padding:8px 12px; border-radius:6px;
  color:#cbd5e1; font-size:.86rem; margin:6px 0 10px 0;}
.cs-legend {display:flex; align-items:center; gap:10px; font-size:.8rem; color:#94a3b8; margin:4px 0 8px 0;}
.cs-grad {height:10px; width:220px; border-radius:6px; background:linear-gradient(90deg,#0f172a,#1e3a8a,#0891b2,#fde047,#ef4444);}
</style>
"""


def inject_css():
    st.markdown(CSS, unsafe_allow_html=True)


def hero(title, subtitle):
    st.markdown(f'<div class="cs-hero"><h1>{title}</h1><p>{subtitle}</p></div>', unsafe_allow_html=True)


def note(text):
    st.markdown(f'<div class="cs-note">{text}</div>', unsafe_allow_html=True)


def banner(text):
    st.markdown(f'<div class="cs-banner">{text}</div>', unsafe_allow_html=True)


def fmt_int(n):
    return "n/a" if n is None else f"{int(n):,}"


def fmt_pct(p, signed=False):
    return "n/a" if p is None else (f"{p:+.1f}%" if signed else f"{p:.1f}%")


def kpi_cards(items, cols=4):
    """items: list of dicts {label, value, sub, tone('up'|'down'|''), small(bool)}"""
    for i in range(0, len(items), cols):
        row = st.columns(cols)
        for col, it in zip(row, items[i:i + cols]):
            cls = "v sm" if it.get("small") else "v"
            col.markdown(f'<div class="cs-card"><div class="l">{it["label"]}</div><div class="{cls}">{it["value"]}</div>'
                         f'<div class="s {it.get("tone", "")}">{it.get("sub", "&nbsp;")}</div></div>', unsafe_allow_html=True)


def empty_state(msg="No recorded incidents match the current filters. Widen the date range or clear the category / hour filters."):
    st.info(msg, icon="🔎")


def style_fig(fig, title, subtitle=None, height=360, legend=True):
    t = f"<b>{title}</b>" + (f"<br><span style='font-size:12px;color:{C['muted']}'>{subtitle}</span>" if subtitle else "")
    fig.update_layout(
        title=dict(text=t, x=0.01, xanchor="left", y=0.97), height=height, margin=dict(l=8, r=8, t=74 if subtitle else 52, b=8),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color=C["text"], size=12),
        colorway=QUAL, showlegend=legend, legend=dict(orientation="h", y=-0.18, font=dict(size=11)),
        hoverlabel=dict(bgcolor="#0f172a", bordercolor=C["line"], font=dict(color=C["text"])))
    fig.update_xaxes(gridcolor=C["line"], zerolinecolor=C["line"], linecolor=C["line"])
    fig.update_yaxes(gridcolor=C["line"], zerolinecolor=C["line"], linecolor=C["line"])
    return fig


def show(fig, key=None):
    st.plotly_chart(fig, width="stretch", key=key, config={"displaylogo": False})


def heatmap(matrix: pd.DataFrame, title, subtitle, xlab, ylab, height=380, fmt="%{z:,}", key=None):
    fig = go.Figure(go.Heatmap(z=matrix.values, x=[str(c) for c in matrix.columns], y=list(matrix.index),
                               colorscale=SEQ, hovertemplate=f"{ylab}: %{{y}}<br>{xlab}: %{{x}}<br>Incidents: {fmt}<extra></extra>",
                               colorbar=dict(title="Incidents", thickness=12)))
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(title=xlab, type="category")
    style_fig(fig, title, subtitle, height, legend=False)
    show(fig, key)


def explain(text, title="How to read this"):
    with st.expander(title):
        st.markdown(text)


# --------------------------------------------------------------------- cached loaders
# Files are keyed by the pipeline output's modification time so a re-run of the pipeline invalidates caches.
def _mt(ds_dir):
    p = Path(ds_dir) / "pipeline_metrics.json"
    return p.stat().st_mtime if p.exists() else 0.0


@st.cache_data(show_spinner="Loading aggregated data…", max_entries=48)
def c_time(ds_dir, mtime, fkey):
    return D.load_time(ds_dir, D.Filters(*fkey))


@st.cache_data(show_spinner="Loading map data…", max_entries=32)
def c_cells(ds_dir, mtime, fkey, hour_block):
    return D.load_cells(ds_dir, D.Filters(*fkey), hour_block)


@st.cache_data(show_spinner="Loading area data…", max_entries=32)
def c_area_months(ds_dir, mtime, fkey, areas):
    return D.load_area_months(ds_dir, D.Filters(*fkey), areas)


@st.cache_data(show_spinner="Loading area data…", max_entries=32)
def c_area_time(ds_dir, mtime, fkey, areas):
    return D.load_area_time(ds_dir, D.Filters(*fkey), areas)


@st.cache_data(show_spinner=False)
def c_table(ds_dir, mtime, name):
    return D.read_parquet(ds_dir, name)


class Loader:
    """Thin per-run helper that binds ds_dir + mtime so pages stay readable."""

    def __init__(self, ctx):
        self.d, self.m, self.hb = str(ctx.ds_dir), _mt(ctx.ds_dir), ctx.hour_block

    def time(self, f): return c_time(self.d, self.m, f.key())
    def cells(self, f): return c_cells(self.d, self.m, f.key(), self.hb)
    def area_months(self, f, areas=()): return c_area_months(self.d, self.m, f.key(), tuple(areas))
    def area_time(self, f, areas=()): return c_area_time(self.d, self.m, f.key(), tuple(areas))
    def table(self, name): return c_table(self.d, self.m, name)
