from dataclasses import replace

import plotly.express as px
import streamlit as st

from . import components as UI, data as D, maps

MODES = ["Density heatmap", "Grid cells", "Geographical clusters", "Category-specific"]


def render(ctx):
    f, L = ctx.filters, ctx.loader
    UI.hero("Interactive Crime Map", "Aggregated grid cells of recorded incidents · zoom, pan and hover for details · "
            "no individual records are plotted")
    mode = st.radio("Map mode", MODES, horizontal=True, key=f"{ctx.tag}:mapmode")
    ff = f
    if mode == "Category-specific":
        cat = st.selectbox("Crime category", ctx.categories, key=f"{ctx.tag}:mapcat")
        ff = replace(f, categories=(cat,))
        UI.note(f"Showing only <b>{cat}</b>; the sidebar category filter is overridden on this page in this mode.")
    cells, exact = L.cells(ff)
    if cells is None:
        return UI.empty_state("This dataset has no map cube. Re-run the pipeline.")
    if cells.empty:
        return UI.empty_state()
    if not exact:
        UI.note(f"The map stores hours in {ctx.hour_block}-hour blocks, so your hour range is widened to whole blocks "
                f"(e.g. {f.hour_min // ctx.hour_block * ctx.hour_block:02d}:00-{(f.hour_max // ctx.hour_block + 1) * ctx.hour_block - 1:02d}:59).")
    total = D.total_incidents(cells)
    left, right = st.columns([3.2, 1.35])
    with left:
        if mode == "Density heatmap":
            deck, g = maps.heatmap_deck(cells, 600)
            st.markdown('<div class="cs-legend"><span>low</span><div class="cs-grad"></div><span>high</span>'
                        '<span>· intensity = weighted density of recorded incidents (relative, not an absolute rate)</span></div>',
                        unsafe_allow_html=True)
        elif mode in ("Grid cells", "Category-specific"):
            deck, g, cap = maps.grid_deck(cells, ctx.cell_deg, 600)
            maps.legend(cap)
        else:
            assign, summ = L.table("cell_clusters"), L.table("cluster_summary")
            if assign is None or summ is None:
                return UI.empty_state("Clustering output is not available (too few eligible cells, or pipeline not re-run).")
            deck, g = maps.cluster_deck(cells, assign, summ, ctx.cell_deg, 600)
            st.markdown('<div class="cs-legend"><span>Colour = K-Means cluster of <b>nearby cells</b>. '
                        'Cluster numbers are labels ordered west→east and carry <b>no</b> ranking or risk meaning.</span></div>',
                        unsafe_allow_html=True)
        st.pydeck_chart(deck, height=600)
        st.caption(f"{len(g):,} grid cells · {total:,} recorded incidents · cell size {ctx.cell_deg}° (~{ctx.cell_deg * 111:.1f} km). "
                   "Base map tiles load from the internet; if you are offline the data layers still draw on a plain background.")
    with right:
        if mode == "Geographical clusters":
            m = g.groupby(["cluster_no", "cluster_label"], as_index=False).agg(cells=("cell_id", "nunique"), incidents=("incidents", "sum"))
            m["share_pct"] = (100 * m.incidents / m.incidents.sum()).round(1)
            fig = px.bar(m, x="cluster_label", y="incidents", color="cluster_label", custom_data=["cells", "share_pct"],
                         color_discrete_sequence=UI.QUAL)
            fig.update_traces(hovertemplate="%{x}<br>%{y:,} incidents (%{customdata[1]}%)<br>%{customdata[0]} cells<extra></extra>")
            fig.update_xaxes(title=None); fig.update_yaxes(title="Incidents")
            UI.style_fig(fig, "Cluster sizes", "Sizes describe grouping, not danger", 320, legend=False)
            UI.show(fig, "map_cl")
            st.dataframe(m[["cluster_label", "cells", "incidents", "share_pct"]].rename(
                columns={"cluster_label": "Cluster", "cells": "Cells", "incidents": "Incidents", "share_pct": "Share %"}),
                hide_index=True, width="stretch")
            info = ctx.meta.get("cluster", {})
            if info.get("chosen_k"):
                st.caption(f"K = {info['chosen_k']} chosen automatically by silhouette ({info.get('silhouette')}) from "
                           f"{[s['k'] for s in info['scan']]}. Clusters are computed on the full dataset, sizes here follow your filters.")
        else:
            st.markdown("**Highest-count cells in view**")
            top = D.rank_hotspots(cells, 1).head(10)
            st.dataframe(top[["rank", "location", "incidents", "share_pct", "top_category"]].rename(
                columns={"rank": "#", "location": "Cell centre", "incidents": "Incidents", "share_pct": "Share %", "top_category": "Top category"}),
                hide_index=True, width="stretch")
            st.caption("Raw counts, not rates: busier places (more people, more reporting) naturally record more incidents.")
