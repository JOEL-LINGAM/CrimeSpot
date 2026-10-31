from dataclasses import replace

import pandas as pd
import plotly.express as px
import streamlit as st

from . import components as UI, data as D, maps

MAX_SLICES = 12


def render(ctx):
    f, L = ctx.filters, ctx.loader
    UI.hero("Crime Category Explorer", "Rank, compare and locate recorded crime categories")
    t = L.time(f)
    if t is None or t.empty:
        return UI.empty_state()
    share = D.share_table(t, "category")
    top_n = st.slider("Categories shown in rankings", 5, max(5, min(30, len(share))), min(15, max(5, len(share))), key=f"{ctx.tag}:c_topn") \
        if len(share) > 5 else len(share)
    a, b = st.columns([3, 2])
    with a:
        r = share.head(top_n).iloc[::-1]
        fig = px.bar(r, x="incidents", y="category", orientation="h", custom_data=["share_pct"])
        fig.update_traces(marker_color=UI.C["accent"], hovertemplate="%{y}<br>%{x:,} incidents (%{customdata[0]:.2f}%)<extra></extra>")
        fig.update_xaxes(title="Incidents"); fig.update_yaxes(title=None)
        UI.style_fig(fig, "Categories ranked by recorded incidents", f"Top {len(r)} of {len(share)} categories", max(340, 24 * len(r) + 100), legend=False)
        UI.show(fig, "ct_rank")
    with b:
        tm = share.head(MAX_SLICES).copy()
        rest = share.iloc[MAX_SLICES:]
        if len(rest):
            tm.loc[len(tm)] = [f"Other ({len(rest)} categories)", rest.incidents.sum(), rest.share_pct.sum()]
        fig = px.treemap(tm, path=["category"], values="incidents", custom_data=["share_pct"], color="incidents", color_continuous_scale=UI.SEQ)
        fig.update_traces(hovertemplate="%{label}<br>%{value:,} incidents (%{customdata[0]:.2f}%)<extra></extra>", textinfo="label+percent root")
        fig.update_coloraxes(showscale=False)
        UI.style_fig(fig, "Category share", f"Top {MAX_SLICES} shown; the rest grouped as 'Other' (documented, not hidden)", max(340, 24 * len(r) + 100), legend=False)
        UI.show(fig, "ct_tree")

    st.markdown("##### Compare categories")
    default = share.category.head(5).tolist()
    sel = st.multiselect("Categories to compare", share.category.tolist(), default=default, key=f"{ctx.tag}:c_sel")
    if not sel:
        return UI.empty_state("Select one or more categories to compare.")
    ts = t[t.category.isin(sel)]
    monthly = ts.groupby(["year_month", "category"], as_index=False)["incidents"].sum()
    fig = px.line(monthly, x="year_month", y="incidents", color="category")
    fig.update_xaxes(title=None, type="category", nticks=14); fig.update_yaxes(title="Incidents per month", rangemode="tozero")
    fig.update_traces(hovertemplate="%{x}<br>%{y:,}<extra></extra>")
    UI.style_fig(fig, "Category trends over time", "Months with no records for a category are absent from its line", 360)
    UI.show(fig, "ct_trend")

    c, d = st.columns(2)
    with c:
        norm = st.toggle("Normalise each category (share of its own incidents)", value=True, key=f"{ctx.tag}:c_norm")
        m = ts.groupby(["category", "hour"])["incidents"].sum().unstack("hour").reindex(columns=range(24)).fillna(0)
        m = m.reindex(sel)
        if norm:
            m = (100 * m.div(m.sum(axis=1).replace(0, 1), axis=0)).round(2)
            UI.heatmap(m, "Category × hour heatmap", "Each row sums to 100%: compares the SHAPE of daily patterns", "Hour", "Category", fmt="%{z:.1f}%", key="ct_hh")
        else:
            UI.heatmap(m.astype(int), "Category × hour heatmap", "Raw counts: busy categories dominate", "Hour", "Category", key="ct_hh")
    with d:
        w = ts.groupby(["category", "weekday_num"], as_index=False)["incidents"].sum()
        w["day"] = w.weekday_num.map(lambda i: D.DAY_ORDER[i - 1])
        w["share"] = 100 * w.incidents / w.groupby("category").incidents.transform("sum")
        fig = px.bar(w, x="day", y="share", color="category", barmode="group", custom_data=["incidents"])
        fig.update_traces(hovertemplate="%{x}<br>%{y:.1f}% of this category (%{customdata[0]:,} incidents)<extra></extra>")
        fig.update_xaxes(title=None, categoryorder="array", categoryarray=D.DAY_ORDER); fig.update_yaxes(title="% of category's incidents")
        UI.style_fig(fig, "Category × weekday comparison", "Percent of each category's own incidents", 380)
        UI.show(fig, "ct_wd")

    st.markdown("##### Geographic distribution of one category")
    one = st.selectbox("Category on map", sel, key=f"{ctx.tag}:c_map")
    cells, exact = L.cells(replace(f, categories=(one,)))
    if cells is None or cells.empty:
        UI.empty_state("No geolocated incidents for this category and filters.")
    else:
        deck, g, cap = maps.grid_deck(cells, ctx.cell_deg, 460)
        maps.legend(cap)
        st.pydeck_chart(deck, height=460)

    st.markdown("##### Detailed table")
    pk_h = t.groupby(["category", "hour"])["incidents"].sum().reset_index().sort_values(["category", "incidents", "hour"], ascending=[True, False, True]).drop_duplicates("category")
    pk_d = t.groupby(["category", "weekday_num"])["incidents"].sum().reset_index().sort_values(["category", "incidents", "weekday_num"], ascending=[True, False, True]).drop_duplicates("category")
    tab = share.merge(pk_h[["category", "hour"]].rename(columns={"hour": "peak_hour"}), on="category") \
               .merge(pk_d.assign(peak_weekday=pk_d.weekday_num.map(lambda i: D.DAY_ORDER[i - 1]))[["category", "peak_weekday"]], on="category")
    tab["cumulative_share_pct"] = tab.share_pct.cumsum().round(2)
    st.dataframe(tab, hide_index=True, width="stretch", column_config={
        "category": "Category", "incidents": st.column_config.NumberColumn("Incidents", format="%d"),
        "share_pct": st.column_config.ProgressColumn("Share %", format="%.2f", min_value=0, max_value=float(max(tab.share_pct.max(), 1))),
        "cumulative_share_pct": st.column_config.NumberColumn("Cumulative %", format="%.2f"),
        "peak_hour": st.column_config.NumberColumn("Peak hour", format="%02d:00"), "peak_weekday": "Peak weekday"})
