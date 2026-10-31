import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from . import components as UI, data as D, maps
from src.metrics_utils import safe_pct_change


def render(ctx):
    f, L = ctx.filters, ctx.loader
    UI.hero("Executive Overview", f"Recorded incidents from <b>{f.start}</b> to <b>{f.end}</b> · "
            f"{ctx.info.get('name', '')} · descriptive historical analytics, not predictions")
    t = L.time(f)
    cells, exact = L.cells(f)
    if t is None or D.total_incidents(t) == 0:
        return UI.empty_state()
    area = L.area_months(f) if ctx.has_area else None
    k = D.kpi_summary(t, cells, area)

    # period-over-period change: only when an equal-length previous period exists and is comparable
    pf = D.previous_period_filters(f, ctx.months[0])
    delta_txt, tone = "Previous period is not covered by the data (or filters make it invalid).", ""
    if pf is not None:
        prev = D.total_incidents(L.time(pf))
        ch = safe_pct_change(k["total"], prev)
        if ch is None:
            delta_txt = f"No valid baseline: previous equal-length period ({pf.start} to {pf.end}) has {prev:,} incidents."
        else:
            delta_txt, tone = f"vs {pf.start} to {pf.end} ({prev:,})", "up" if ch > 0 else "down"
        chg_val = UI.fmt_pct(ch, signed=True)
    else:
        chg_val = "n/a"
    UI.kpi_cards([
        dict(label="Recorded incidents", value=UI.fmt_int(k["total"]), sub=f"{D.n_months_label(f)}"),
        dict(label="Change vs previous period", value=chg_val, sub=delta_txt, tone=tone),
        dict(label="Crime categories", value=UI.fmt_int(k["categories"]), sub="with ≥1 incident in selection"),
        dict(label="Grid cells with incidents", value=UI.fmt_int(k["cells"]), sub=f"{ctx.cell_deg}° cells (~{ctx.cell_deg * 111:.1f} km)"),
        dict(label="Most frequent category", value=k["top_category"], small=True, sub=f"{k['top_category_share']:.1f}% of incidents"),
        dict(label="Highest-count grid cell", value=k["top_cell"] or "n/a", small=True,
             sub=f"{UI.fmt_int(k['top_cell_incidents'])} incidents" if k["top_cell"] else ""),
        dict(label="Highest-count area", value=k["top_area"] or "n/a", small=True,
             sub=(f"{UI.fmt_int(k['top_area_incidents'])} incidents (date+category filters only)" if k["top_area"] else "no area field in dataset")),
        dict(label="Data coverage", value=f"{ctx.info.get('date_min', '')[:10]} → {ctx.info.get('date_max', '')[:10]}", small=True,
             sub=f"{UI.fmt_int(ctx.meta['quality'].get('retained_records'))} retained records"),
    ])
    st.write("")
    c1, c2 = st.columns([3, 2])
    with c1:
        m = D.monthly_series(t, f.start, f.end)
        fig = px.line(m, x="year_month", y="incidents", markers=len(m) <= 48)
        fig.update_traces(line=dict(color=UI.C["accent"], width=2.4), fill="tozeroy", fillcolor="rgba(34,211,238,.10)",
                          hovertemplate="%{x}<br>Incidents: %{y:,}<extra></extra>")
        pm = [x for x in ctx.partial if x in set(m.year_month)]
        if pm:
            fig.add_trace(go.Scatter(x=pm, y=m.set_index("year_month").loc[pm, "incidents"], mode="markers", name="Possibly incomplete month",
                                     marker=dict(color=UI.C["amber"], size=10, symbol="diamond"), hovertemplate="%{x}: possibly partial month<extra></extra>"))
        fig.update_xaxes(title=None, type="category", nticks=14); fig.update_yaxes(title="Incidents per month", rangemode="tozero")
        UI.style_fig(fig, "Monthly incident trend", "Axis starts at zero · amber markers = edge months that may be incomplete", 380, legend=bool(pm))
        UI.show(fig, "ov_trend")
    with c2:
        cats = D.share_table(t, "category").head(10)
        fig = px.bar(cats.iloc[::-1], x="incidents", y="category", orientation="h", custom_data=["share_pct"])
        fig.update_traces(marker_color=UI.C["accent"], hovertemplate="%{y}<br>%{x:,} incidents (%{customdata[0]:.1f}%)<extra></extra>")
        fig.update_xaxes(title="Incidents"); fig.update_yaxes(title=None)
        UI.style_fig(fig, "Top crime categories", "Ranked by recorded incidents", 380, legend=False)
        UI.show(fig, "ov_cats")
    c3, c4, c5 = st.columns([3, 2, 2])
    with c3:
        st.markdown("**Geographic density preview**")
        if cells is None or cells.empty:
            UI.empty_state("No geolocated incidents for these filters.")
        else:
            deck, _ = maps.heatmap_deck(cells, 330)
            st.pydeck_chart(deck, height=330)
            st.caption("Brightness = recorded incidents per grid cell. Open the Interactive Crime Map page for more modes." +
                       ("" if exact else " Hour filter is applied in 3-hour blocks on map data."))
    with c4:
        ww = D.weekday_weekend(t)
        fig = px.bar(ww, x="day_type", y="avg_per_day_of_week", custom_data=["incidents", "days_in_week"])
        fig.update_traces(marker_color=[UI.C["accent"], UI.C["amber"]],
                          hovertemplate="%{x}<br>Total: %{customdata[0]:,}<br>Average per day of week: %{y:,.0f}<extra></extra>")
        fig.update_xaxes(title=None); fig.update_yaxes(title="Avg incidents per day of the week", rangemode="tozero")
        UI.style_fig(fig, "Weekday vs weekend", "Normalised per day (5 vs 2 days)", 330, legend=False)
        UI.show(fig, "ov_ww")
    with c5:
        st.markdown("**Automatic summary**")
        for s in D.auto_summary(t, cells, ctx.partial):
            st.markdown(f"- {s}")
    UI.explain("All figures come from the Spark pipeline's Parquet cubes and respond to the sidebar filters. "
               "Counts are *recorded incidents*; they depend on reporting and enforcement practices and are not per-capita rates.")
