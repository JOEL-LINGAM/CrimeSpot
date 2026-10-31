from dataclasses import replace

import pandas as pd
import plotly.express as px
import streamlit as st

from . import components as UI, data as D
from src.metrics_utils import safe_pct_change, n_months


def _chg(a, b):
    p = safe_pct_change(b, a)
    return None if p is None else round(p, 1)


def render(ctx):
    f, L = ctx.filters, ctx.loader
    UI.hero("Comparative Analytics", f"Side-by-side comparison with a consistent date range ({f.start} → {f.end}) and consistent denominators")
    UI.note("Current selections: " + f"<b>{f.start} → {f.end}</b>, categories: <b>{', '.join(f.categories) if f.categories else 'all'}</b>, "
            f"hours <b>{f.hour_min:02d}-{f.hour_max:02d}</b>, day type <b>{f.day_type}</b>. Use <i>Reset filters</i> in the sidebar to clear. "
            "Percent changes are blank when the baseline is zero.")
    months_n = max(1, n_months(f.start, f.end))
    tabs = st.tabs(["📍 Areas", "🧩 Categories", "🗓️ Periods"])

    with tabs[0]:
        if not ctx.has_area:
            UI.empty_state("This dataset has no area field.")
        else:
            a = L.area_months(f)
            if a is None or a.empty:
                UI.empty_state()
            else:
                tot = a.groupby("area")["incidents"].sum().sort_values(ascending=False)
                sel = st.multiselect("Areas (2-6)", tot.index.astype(str).tolist(), default=tot.index[:3].astype(str).tolist(), max_selections=6, key=f"{ctx.tag}:cmp_a")
                if len(sel) < 2:
                    UI.empty_state("Pick at least two areas to compare.")
                else:
                    UI.note("Area data honours the date and category filters (the area cube has no hour/weekday grain).")
                    s = a[a.area.astype(str).isin(sel)]
                    summary = s.groupby("area", as_index=False)["incidents"].sum()
                    summary["per_month"] = (summary.incidents / months_n).round(1)
                    hv = D.half_period_change(s, f.start, f.end, key="area")
                    if hv is not None:
                        summary = summary.merge(hv[["area", "first_half", "second_half", "abs_change", "pct_change"]], on="area", how="left")
                    c1, c2 = st.columns(2)
                    with c1:
                        fig = px.bar(summary, x="area", y="incidents", color="area", color_discrete_sequence=UI.QUAL, custom_data=["per_month"])
                        fig.update_traces(hovertemplate="Area %{x}<br>%{y:,} incidents<br>%{customdata[0]} per month<extra></extra>")
                        fig.update_xaxes(title="Area", type="category"); fig.update_yaxes(title="Incidents")
                        UI.style_fig(fig, "Total recorded incidents", "Same date range for every area · raw counts, not rates", 340, legend=False)
                        UI.show(fig, "cp_a1")
                    with c2:
                        mix = s.groupby(["area", "category"], as_index=False)["incidents"].sum()
                        mix["share"] = 100 * mix.incidents / mix.groupby("area").incidents.transform("sum")
                        topc = mix.groupby("category").incidents.sum().nlargest(8).index
                        mix = mix[mix.category.isin(topc)]
                        fig = px.bar(mix, x="area", y="share", color="category", color_discrete_sequence=UI.QUAL, custom_data=["incidents"])
                        fig.update_traces(hovertemplate="%{x} · %{fullData.name}<br>%{y:.1f}% (%{customdata[0]:,})<extra></extra>")
                        fig.update_xaxes(title="Area", type="category"); fig.update_yaxes(title="% of the area's incidents (top 8 categories)")
                        UI.style_fig(fig, "Category mix", "Normalised so areas of different size are comparable", 340)
                        UI.show(fig, "cp_a2")
                    mm = s.groupby(["area", "year_month"], as_index=False)["incidents"].sum()
                    mm["area"] = mm.area.astype(str)
                    fig = px.line(mm, x="year_month", y="incidents", facet_col="area", facet_col_wrap=3, color="area", color_discrete_sequence=UI.QUAL)
                    fig.update_xaxes(title=None, type="category", nticks=5, matches=None); fig.update_yaxes(title=None, rangemode="tozero")
                    fig.for_each_annotation(lambda x: x.update(text=x.text.replace("area=", "Area ")))
                    UI.style_fig(fig, "Monthly trend, small multiples", "Each panel has its own scale; compare shapes, not heights", 330 if len(sel) <= 3 else 560, legend=False)
                    UI.show(fig, "cp_a3")
                    st.dataframe(summary.rename(columns={"area": "Area", "incidents": "Incidents", "per_month": "Per month", "first_half": "1st half",
                                                         "second_half": "2nd half", "abs_change": "Abs. change", "pct_change": "% change"}),
                                 hide_index=True, width="stretch")

    with tabs[1]:
        t = L.time(f)
        if t is None or t.empty:
            UI.empty_state()
        else:
            share = D.share_table(t, "category")
            sel = st.multiselect("Categories (2-6)", share.category.tolist(), default=share.category.head(3).tolist(), max_selections=6, key=f"{ctx.tag}:cmp_c")
            if len(sel) < 2:
                UI.empty_state("Pick at least two categories to compare.")
            else:
                s = t[t.category.isin(sel)]
                mm = s.groupby(["year_month", "category"], as_index=False)["incidents"].sum()
                fig = px.line(mm, x="year_month", y="incidents", color="category")
                fig.update_xaxes(title=None, type="category", nticks=14); fig.update_yaxes(title="Incidents per month", rangemode="tozero")
                UI.style_fig(fig, "Monthly trend comparison", None, 340)
                UI.show(fig, "cp_c1")
                hv = D.half_period_change(s, f.start, f.end, key="category")
                tab = share[share.category.isin(sel)].copy()
                tab["per_month"] = (tab.incidents / months_n).round(1)
                if hv is not None:
                    tab = tab.merge(hv[["category", "first_half", "second_half", "abs_change", "pct_change"]], on="category", how="left")
                    (a0, a1), (b0, b1) = hv.attrs["halves"]
                    UI.note(f"Change = second half ({b0}→{b1}) minus first half ({a0}→{a1}) of the selected period (equal lengths).")
                    fig = px.bar(tab[["category", "first_half", "second_half"]].melt(id_vars="category", var_name="half", value_name="count"),
                                 x="category", y="count", color="half", barmode="group", color_discrete_map={"first_half": "#475569", "second_half": UI.C["accent"]})
                    fig.update_xaxes(title=None); fig.update_yaxes(title="Incidents")
                    UI.style_fig(fig, "First vs second half of period", "Absolute counts side by side", 320)
                    UI.show(fig, "cp_c2")
                st.dataframe(tab.rename(columns={"category": "Category", "incidents": "Incidents", "share_pct": "Share % (selection)", "per_month": "Per month",
                                                 "first_half": "1st half", "second_half": "2nd half", "abs_change": "Abs. change", "pct_change": "% change"}),
                             hide_index=True, width="stretch")

    with tabs[2]:
        c1, c2 = st.columns(2)
        ms = ctx.months
        pa = c1.select_slider("Period A", ms, value=(ms[0], ms[max(0, len(ms) // 2 - 1)]), key=f"{ctx.tag}:cmp_pa")
        pb = c2.select_slider("Period B", ms, value=(ms[len(ms) // 2], ms[-1]), key=f"{ctx.tag}:cmp_pb")
        na, nb = n_months(*pa), n_months(*pb)
        if na != nb:
            UI.note(f"Periods differ in length ({na} vs {nb} months). Totals are not directly comparable, so <b>incidents per month</b> are shown too.")
        lo, hi = min(pa[0], pb[0]), max(pa[1], pb[1])
        t = L.time(replace(f, start=lo, end=hi))
        if t is None or t.empty:
            UI.empty_state()
        else:
            A, B = t[t.year_month.between(*pa)], t[t.year_month.between(*pb)]
            ta, tb = D.total_incidents(A), D.total_incidents(B)
            chg = safe_pct_change(tb / nb, ta / na) if ta else None
            UI.kpi_cards([dict(label=f"Period A ({pa[0]}→{pa[1]})", value=UI.fmt_int(ta), sub=f"{ta / na:,.0f} per month"),
                          dict(label=f"Period B ({pb[0]}→{pb[1]})", value=UI.fmt_int(tb), sub=f"{tb / nb:,.0f} per month"),
                          dict(label="Change in monthly rate (B vs A)", value=UI.fmt_pct(chg, True), sub="n/a when period A has no incidents", tone="" if chg is None else ("up" if chg > 0 else "down")),
                          dict(label="Absolute change per month", value=f"{(tb / nb - ta / na):+,.0f}", sub="incidents per month")], cols=4)
            ca = D.share_table(A, "category").rename(columns={"incidents": "A"})[["category", "A"]]
            cb = D.share_table(B, "category").rename(columns={"incidents": "B"})[["category", "B"]]
            cm = ca.merge(cb, on="category", how="outer").fillna(0)
            cm["A_per_month"], cm["B_per_month"] = (cm.A / na).round(1), (cm.B / nb).round(1)
            cm["abs_change"] = (cm.B_per_month - cm.A_per_month).round(1)
            cm["pct_change"] = [_chg(a, b) for a, b in zip(cm.A_per_month, cm.B_per_month)]
            cm = cm.sort_values("A", ascending=False)
            long = cm.head(12).melt(id_vars="category", value_vars=["A_per_month", "B_per_month"], var_name="period", value_name="per_month")
            fig = px.bar(long, x="category", y="per_month", color="period", barmode="group", color_discrete_map={"A_per_month": "#475569", "B_per_month": UI.C["accent"]})
            fig.update_xaxes(title=None); fig.update_yaxes(title="Incidents per month")
            UI.style_fig(fig, "Top categories: period A vs period B", "Per-month rates make unequal period lengths comparable", 360)
            UI.show(fig, "cp_p1")
            hrA = A.groupby("hour")["incidents"].sum().reindex(range(24), fill_value=0); hrB = B.groupby("hour")["incidents"].sum().reindex(range(24), fill_value=0)
            hp = pd.DataFrame({"hour": range(24), "A": 100 * hrA.values / max(hrA.sum(), 1), "B": 100 * hrB.values / max(hrB.sum(), 1)}).melt("hour", var_name="period", value_name="share")
            fig = px.line(hp, x="hour", y="share", color="period", color_discrete_map={"A": "#94a3b8", "B": UI.C["accent"]})
            fig.update_xaxes(title="Hour", dtick=2); fig.update_yaxes(title="% of period's incidents", rangemode="tozero")
            UI.style_fig(fig, "Daily pattern shape: A vs B", None, 300)
            UI.show(fig, "cp_p2")
            st.dataframe(cm.rename(columns={"category": "Category", "A": "Total A", "B": "Total B", "A_per_month": "A / month", "B_per_month": "B / month",
                                            "abs_change": "Abs. change / month", "pct_change": "% change"}), hide_index=True, width="stretch")
