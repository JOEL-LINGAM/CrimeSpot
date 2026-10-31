import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from . import components as UI, data as D, maps


def render(ctx):
    f, L = ctx.filters, ctx.loader
    UI.hero("Hotspot Intelligence", "Where recorded incidents are historically concentrated · descriptive, not predictive")
    with st.expander("Method, unit and limitations (read before interpreting)", expanded=False):
        st.markdown(f"""
- **Geographic unit:** square grid cells of **{ctx.cell_deg}°** (~{ctx.cell_deg * 111:.1f} km north-south). A grid gives equal-sized, comparable units and is cheap to aggregate in Spark.
- **Period:** {f.start} → {f.end} (sidebar filters apply; ranking recomputes for any category / hour / day-type selection).
- **Ranking method:** cells are ranked by **recorded incident count**; ties are broken by cell id. Only cells with at least the chosen **minimum number of incidents** are ranked.
- **Not a risk score.** There is no High/Medium/Low label: no documented, defensible threshold exists for this data. Counts ignore population, visitors, reporting and policing practices, so a high count does not mean a place is dangerous, and history is not a guarantee about the future.
- **Clusters** (K-Means) group nearby cells; cluster numbers are only labels (west→east) and have no ranking.""")
    cells, exact = L.cells(f)
    if cells is None or cells.empty:
        return UI.empty_state()
    min_inc = st.slider("Minimum incidents for a cell to be ranked", 1, 200, 10, key=f"{ctx.tag}:h_min")
    ranked = D.rank_hotspots(cells, min_inc)
    if ranked.empty:
        return UI.empty_state("No grid cell reaches the minimum incident count. Lower the minimum or widen the filters.")
    top_n = st.slider("Hotspots shown", 5, min(100, len(ranked)) if len(ranked) > 5 else 5, min(20, len(ranked)), key=f"{ctx.tag}:h_n") if len(ranked) > 5 else len(ranked)
    top = ranked.head(top_n)
    k = max(1, int(round(len(ranked) * 0.1)))
    UI.kpi_cards([
        dict(label="Ranked cells", value=UI.fmt_int(len(ranked)), sub=f"≥ {min_inc} incidents each"),
        dict(label="Highest-count cell", value=top.location.iloc[0], small=True, sub=f"{UI.fmt_int(top.incidents.iloc[0])} incidents ({top.share_pct.iloc[0]:.2f}%)"),
        dict(label=f"Top {top_n} cells hold", value=f"{top.share_pct.sum():.1f}%", sub="of all geolocated incidents in selection"),
        dict(label="Top 10% of ranked cells hold", value=f"{ranked.head(k).share_pct.sum():.1f}%", sub=f"{k} of {len(ranked)} cells"),
    ])
    st.write("")
    a, b = st.columns([3, 2])
    with a:
        deck, g, cap = maps.grid_deck(cells, ctx.cell_deg, 470, highlight_ids=top.cell_id.tolist())
        st.markdown("**Grid cells; white outline = the selected top hotspots**")
        maps.legend(cap)
        st.pydeck_chart(deck, height=470)
    with b:
        fig = go.Figure(go.Scatter(x=ranked["rank"], y=ranked.cumulative_share_pct, mode="lines", line=dict(color=UI.C["accent"], width=3),
                                   hovertemplate="Top %{x} cells hold %{y:.1f}% of incidents<extra></extra>"))
        fig.update_xaxes(title="Cell rank (by recorded incidents)"); fig.update_yaxes(title="Cumulative share of incidents (%)", range=[0, 100])
        UI.style_fig(fig, "Concentration curve", "How quickly incidents accumulate across ranked cells", 470, legend=False)
        UI.show(fig, "hs_pareto")

    st.markdown("##### Ranked hotspot table")
    halves = D.half_period_change(cells, f.start, f.end)
    tbl = top.copy()
    if halves is not None:
        tbl = tbl.merge(halves[["cell_id", "first_half", "second_half", "pct_change"]], on="cell_id", how="left")
        (a0, a1), (b0, b1) = halves.attrs["halves"]
        UI.note(f"Trend columns compare the first half ({a0}→{a1}) with the second half ({b0}→{b1}) of the selected period. "
                "% change is blank where the first half has zero incidents.")
    st.dataframe(tbl.drop(columns=["cell_id", "cell_lat", "cell_lon"]).rename(columns={
        "rank": "#", "location": "Cell centre", "incidents": "Incidents", "share_pct": "Share %", "cumulative_share_pct": "Cum. %",
        "top_category": "Top category", "top_category_share_pct": "Top cat. %", "first_half": "1st half", "second_half": "2nd half",
        "pct_change": "% change"}), hide_index=True, width="stretch")

    c, d = st.columns(2)
    with c:
        fig = px.bar(top.iloc[::-1], x="incidents", y="location", orientation="h", custom_data=["share_pct"])
        fig.update_traces(marker_color=UI.C["amber"], hovertemplate="%{y}<br>%{x:,} incidents (%{customdata[0]:.2f}%)<extra></extra>")
        fig.update_xaxes(title="Incidents"); fig.update_yaxes(title=None, type="category")
        UI.style_fig(fig, "Incident count by hotspot", f"Top {len(top)} grid cells", max(340, 22 * len(top) + 110), legend=False)
        UI.show(fig, "hs_bar")
    with d:
        summ, assign = L.table("cluster_summary"), L.table("cell_clusters")
        if summ is None or assign is None:
            UI.empty_state("No cluster output available for this dataset.")
        else:
            gg = maps.by_cell(cells).merge(assign, on="cell_id")
            cs = gg.groupby("cluster_label", as_index=False).agg(cells=("cell_id", "nunique"), incidents=("incidents", "sum"))
            fig = px.bar(cs, x="cluster_label", y="incidents", custom_data=["cells"], color="cluster_label", color_discrete_sequence=UI.QUAL)
            fig.update_traces(hovertemplate="%{x}<br>%{y:,} incidents · %{customdata[0]} cells<extra></extra>")
            fig.update_xaxes(title=None); fig.update_yaxes(title="Incidents")
            UI.style_fig(fig, "Cluster distribution", "K-Means groups of nearby cells · numbers are labels, not ranks", max(340, 22 * len(top) + 110), legend=False)
            UI.show(fig, "hs_cl")

    st.markdown("##### Explore one hotspot")
    opts = {f"#{r['rank']} · {r['location']} · {r['incidents']:,} incidents": r["cell_id"] for _, r in top.iterrows()}
    choice = st.selectbox("Hotspot", list(opts), key=f"{ctx.tag}:h_pick")
    cid = opts[choice]
    sel = cells[cells.cell_id == cid]
    overall = D.share_table(cells, "category").set_index("category").share_pct
    mine = D.share_table(sel, "category").set_index("category").share_pct
    comp = (overall.to_frame("overall").join(mine.rename("hotspot"), how="outer").fillna(0))
    comp["diff"] = comp.hotspot - comp.overall
    comp = comp.sort_values("hotspot", ascending=False).head(10).reset_index().rename(columns={"index": "category"})
    e1, e2, e3 = st.columns(3)
    with e1:
        fig = go.Figure([go.Bar(name="This hotspot", x=comp.category, y=comp.hotspot, marker_color=UI.C["accent"]),
                         go.Bar(name="All cells (selection)", x=comp.category, y=comp.overall, marker_color="#475569")])
        fig.update_layout(barmode="group"); fig.update_yaxes(title="% of incidents"); fig.update_xaxes(title=None, tickangle=-35)
        UI.style_fig(fig, "Category composition vs overall", "Percentage points differ → local mix differs", 380)
        UI.show(fig, "hs_comp")
    with e2:
        mm = D.monthly_series(sel, f.start, f.end)
        fig = px.line(mm, x="year_month", y="incidents"); fig.update_traces(line=dict(color=UI.C["amber"], width=2.4))
        fig.update_xaxes(title=None, type="category", nticks=10); fig.update_yaxes(title="Incidents / month", rangemode="tozero")
        UI.style_fig(fig, "Temporal pattern: monthly", None, 380, legend=False)
        UI.show(fig, "hs_month")
    with e3:
        hb = sel.groupby("hour_block")["incidents"].sum().reindex(range(24 // ctx.hour_block), fill_value=0).reset_index()
        hb["label"] = [f"{b * ctx.hour_block:02d}-{(b + 1) * ctx.hour_block - 1:02d}h" for b in hb.hour_block]
        fig = px.bar(hb, x="label", y="incidents"); fig.update_traces(marker_color=UI.C["violet"], hovertemplate="%{x}<br>%{y:,}<extra></extra>")
        fig.update_xaxes(title=None); fig.update_yaxes(title="Incidents")
        UI.style_fig(fig, "Time of day", f"{ctx.hour_block}-hour blocks", 380, legend=False)
        UI.show(fig, "hs_hour")
