import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from . import components as UI, data as D


def render(ctx):
    f, L = ctx.filters, ctx.loader
    UI.hero("Temporal Pattern Analysis", "When are incidents recorded? Monthly, yearly, hourly and weekday structure")
    years = sorted({int(m[:4]) for m in D.month_range_safe(f.start, f.end)})
    c1, c2 = st.columns(2)
    sel_years = c1.multiselect("Years", years, default=years, key=f"{ctx.tag}:t_years")
    areas = []
    if ctx.has_area:
        area_opts = sorted(L.table("agg_area").area.astype(str).tolist(), key=lambda x: (len(x), x))
        areas = c2.multiselect("Area (optional)", area_opts, key=f"{ctx.tag}:t_areas", placeholder="All areas")
    if not sel_years:
        return UI.empty_state("Select at least one year.")
    use_area = bool(areas)
    if use_area:
        UI.note("Area view: monthly trend honours date and category filters; hour/weekday charts use the area×hour cube, which "
                "honours years, hours and day type but <b>not</b> the category filter. Month×hour heatmap is unavailable for areas.")
        mdf = L.area_months(f, areas)
        tdf = L.area_time(f, areas)
        mdf = mdf[mdf.year_month.str[:4].astype(int).isin(sel_years)]
        tdf = tdf[tdf.year.isin(sel_years)]
        month_src = mdf.rename(columns={})
    else:
        t = L.time(f)
        if t is None or t.empty:
            return UI.empty_state()
        t = t[t.year_month.str[:4].astype(int).isin(sel_years)]
        tdf, month_src = t, t
    if tdf is None or tdf.empty or D.total_incidents(tdf) == 0:
        return UI.empty_state()

    # monthly trend
    m = D.monthly_series(month_src, f.start, f.end) if not use_area else None
    if use_area:
        mm = month_src.groupby(["area", "year_month"], as_index=False)["incidents"].sum()
        fig = px.line(mm, x="year_month", y="incidents", color="area")
    else:
        m = m[m.year_month.str[:4].astype(int).isin(sel_years)]
        fig = px.line(m, x="year_month", y="incidents")
        fig.update_traces(line=dict(color=UI.C["accent"], width=2.4))
        pm = [x for x in ctx.partial if x in set(m.year_month)]
        if pm:
            fig.add_trace(go.Scatter(x=pm, y=m.set_index("year_month").loc[pm, "incidents"], mode="markers", name="Possibly incomplete month",
                                     marker=dict(color=UI.C["amber"], size=10, symbol="diamond")))
    fig.update_xaxes(title=None, type="category", nticks=16); fig.update_yaxes(title="Incidents per month", rangemode="tozero")
    fig.update_traces(hovertemplate="%{x}<br>%{y:,} incidents<extra></extra>", selector=dict(mode="lines"))
    UI.style_fig(fig, "Monthly trend", "Edge months marked with amber diamonds may be partial and not comparable to full months", 360)
    UI.show(fig, "tp_month")

    a, b = st.columns(2)
    with a:
        yoy = D.year_over_year(month_src if not use_area else mdf, ctx.partial)
        if yoy.empty or yoy.year.nunique() < 2:
            UI.empty_state("Year-over-year comparison needs at least two years of complete months in the selection.")
        else:
            fig = px.line(yoy, x="month", y="incidents", color=yoy.year.astype(str), markers=True)
            fig.update_xaxes(tickmode="array", tickvals=list(range(1, 13)), ticktext=D.MONTH_NAMES, title=None)
            fig.update_yaxes(title="Incidents", rangemode="tozero")
            fig.update_traces(hovertemplate="%{x}: %{y:,}<extra></extra>")
            UI.style_fig(fig, "Year-over-year comparison", "One line per year · partial edge months excluded", 360)
            UI.show(fig, "tp_yoy")
    with b:
        s = D.seasonality(month_src if not use_area else mdf, ctx.partial)
        if s is None:
            UI.empty_state("Seasonal comparison needs at least 12 months of complete data in the selection.")
        else:
            fig = px.bar(s, x="month_name", y="avg_incidents")
            fig.update_traces(marker_color=UI.C["violet"], hovertemplate="%{x}<br>Average %{y:,.0f} incidents per month<extra></extra>")
            fig.update_xaxes(title=None, categoryorder="array", categoryarray=D.MONTH_NAMES); fig.update_yaxes(title="Avg incidents per month", rangemode="tozero")
            UI.style_fig(fig, "Seasonality", "Average per calendar month across the selected years", 360, legend=False)
            UI.show(fig, "tp_season")

    c, d, e = st.columns([3, 2, 2])
    hr = tdf.groupby("hour", as_index=False)["incidents"].sum()
    hr = hr.set_index("hour").reindex(range(24), fill_value=0).reset_index()
    hr["share"] = 100 * hr.incidents / max(hr.incidents.sum(), 1)
    with c:
        fig = px.bar(hr, x="hour", y="incidents", custom_data=["share"])
        fig.update_traces(marker_color=UI.C["accent"], hovertemplate="%{x:02d}:00<br>%{y:,} incidents (%{customdata[0]:.1f}%)<extra></extra>")
        fig.update_xaxes(title="Hour of day", dtick=2); fig.update_yaxes(title="Incidents")
        UI.style_fig(fig, "Hour-of-day distribution", "Local time as recorded in the source data", 330, legend=False)
        UI.show(fig, "tp_hour")
    wd = tdf.groupby("weekday_num")["incidents"].sum().reindex(range(1, 8), fill_value=0).reset_index()
    wd["day"] = D.DAY_ORDER
    wd["share"] = 100 * wd.incidents / max(wd.incidents.sum(), 1)
    with d:
        fig = px.bar(wd, x="day", y="incidents", custom_data=["share"])
        fig.update_traces(marker_color=UI.C["amber"], hovertemplate="%{x}<br>%{y:,} incidents (%{customdata[0]:.1f}%)<extra></extra>")
        fig.update_xaxes(title=None, categoryorder="array", categoryarray=D.DAY_ORDER); fig.update_yaxes(title="Incidents")
        UI.style_fig(fig, "Weekday distribution", None, 330, legend=False)
        UI.show(fig, "tp_wd")
    with e:
        ww = D.weekday_weekend(tdf)
        fig = px.bar(ww, x="day_type", y="avg_per_day_of_week", custom_data=["incidents"])
        fig.update_traces(marker_color=[UI.C["accent"], UI.C["amber"]], hovertemplate="%{x}<br>Total %{customdata[0]:,}<br>Avg/day-of-week %{y:,.0f}<extra></extra>")
        fig.update_xaxes(title=None); fig.update_yaxes(title="Avg per day of week", rangemode="tozero")
        UI.style_fig(fig, "Weekday vs weekend", "Normalised per day", 330, legend=False)
        UI.show(fig, "tp_ww")

    g1, g2 = st.columns(2)
    with g1:
        UI.heatmap(D.pivot_hour_weekday(tdf), "Hour × weekday heatmap", "Brighter = more recorded incidents", "Hour", "Weekday", key="tp_hw")
    with g2:
        if use_area:
            UI.empty_state("Month × hour heatmap is not available with an area selection (the area cube has no month grain).")
        else:
            UI.heatmap(D.pivot_month_hour(tdf), "Month × hour heatmap", "Summed over the selected years (years with partial coverage weigh less)", "Hour", "Month", key="tp_mh")
