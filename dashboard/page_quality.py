import pandas as pd
import plotly.express as px
import streamlit as st

from . import components as UI

REASON_TEXT = {
    "missing_timestamp": "Timestamp is empty", "malformed_or_out_of_range_timestamp": "Timestamp could not be parsed with any configured format, or year outside the allowed range",
    "missing_category": "Crime category empty or blank", "missing_coordinates": "Latitude and/or longitude missing or non-numeric",
    "invalid_coordinates": "Coordinates outside ±90/±180 or exactly (0, 0)", "outside_study_area": "Coordinates outside the configured study-area bounding box"}

DOT = """digraph G { rankdir=LR; bgcolor="transparent"; node [shape=box, style="rounded,filled", fillcolor="#111a2e", color="#22d3ee", fontcolor="#e5e7eb", fontname="Helvetica", fontsize=11];
edge [color="#64748b"]; raw [label="Raw CSV"]; ing [label="Ingest\\n+ column mapping"]; cln [label="Clean\\n(6 rules + dedup)"]; feat [label="Features\\n(time + grid cell)"];
agg [label="Spark SQL\\naggregates + cubes"]; hot [label="Hotspot ranking\\n+ K-Means"]; pq [label="Parquet\\noutputs", fillcolor="#0b3b4a"]; dash [label="Streamlit\\ndashboard", fillcolor="#3b2f0b", color="#f59e0b"];
raw -> ing -> cln -> feat -> agg -> pq; feat -> hot -> pq; pq -> dash; }"""


def render(ctx):
    q, info = ctx.meta["quality"], ctx.info
    UI.hero("Data Quality & Methodology", "Transparent account of what went into every chart")
    if not q:
        return UI.empty_state("No quality report found.")
    inp, ret, exc, dup = q["input_records"], q["retained_records"], q["excluded_total"], q["duplicates_removed"]
    UI.kpi_cards([dict(label="Input records", value=UI.fmt_int(inp)), dict(label="Retained", value=UI.fmt_int(ret), sub=f"{100 * ret / max(inp, 1):.2f}% of input"),
                  dict(label="Excluded (validation)", value=UI.fmt_int(exc), sub=f"{100 * exc / max(inp, 1):.2f}% of input"),
                  dict(label="Duplicates removed", value=UI.fmt_int(dup), sub=q["dedup_rule"], tone="")])
    ok = q["reconciles"]
    st.markdown(f"{'✅' if ok else '❌'} **Reconciliation:** {inp:,} input = {exc:,} excluded + {dup:,} duplicates + {ret:,} retained "
                f"→ {'balances exactly' if ok else 'DOES NOT BALANCE - investigate'}.")
    a, b = st.columns(2)
    with a:
        r = pd.DataFrame([{"reason": k.replace("_", " "), "records": v, "rule": REASON_TEXT.get(k, "")} for k, v in q["excluded_by_reason"].items()])
        fig = px.bar(r.sort_values("records"), x="records", y="reason", orientation="h", custom_data=["rule"])
        fig.update_traces(marker_color=UI.C["amber"], hovertemplate="%{y}: %{x:,}<br>%{customdata[0]}<extra></extra>")
        fig.update_xaxes(title="Records excluded"); fig.update_yaxes(title=None)
        UI.style_fig(fig, "Why records were excluded", "Each record gets exactly ONE reason (the first rule it breaks)", 340, legend=False)
        UI.show(fig, "dq_reasons")
    with b:
        mv = pd.DataFrame([{"column": k, "missing": v["missing"], "pct": v["pct"]} for k, v in q["raw_missing_values"].items()])
        fig = px.bar(mv.sort_values("pct"), x="pct", y="column", orientation="h", custom_data=["missing"])
        fig.update_traces(marker_color=UI.C["violet"], hovertemplate="%{y}: %{x:.2f}% (%{customdata[0]:,} rows)<extra></extra>")
        fig.update_xaxes(title="% missing/blank in raw input"); fig.update_yaxes(title=None)
        UI.style_fig(fig, "Missing values by column (raw)", "Measured before any cleaning", 340, legend=False)
        UI.show(fig, "dq_missing")
    st.markdown("##### Pipeline")
    st.graphviz_chart(DOT, width="stretch")

    c, d = st.columns(2)
    with c:
        st.markdown("##### Data source")
        st.markdown(f"- **Dataset:** {info.get('name')}\n- **Source:** {info.get('source_url')}\n- **Attribution / licence:** {info.get('attribution')}\n"
                    f"- **Synthetic?** {'**YES - not real crime data**' if info.get('is_synthetic') else 'No (real open data)'}\n"
                    f"- **Date coverage:** {info.get('date_min')} → {info.get('date_max')}\n- **Categories:** {info.get('n_categories')} · **Grid cells with incidents:** {info.get('n_cells')}\n"
                    f"- **Time handling:** {info.get('timestamp_note')}")
        st.markdown("**Column mapping used**")
        st.dataframe(pd.DataFrame(list(info.get("column_mapping", {}).items()), columns=["Canonical field", "Source column"]), hide_index=True, width="stretch")
    with d:
        st.markdown("##### Cleaning rules")
        st.dataframe(pd.DataFrame([[k.replace("_", " "), v] for k, v in REASON_TEXT.items()], columns=["Rule (applied in this order)", "Definition"]), hide_index=True, width="stretch")
        st.markdown("**De-duplication:** one row per incident id (earliest timestamp kept). Rows are never merged because they merely look similar; without an id only exact full-row duplicates are removed. "
                    "**Category names** are trimmed, whitespace-collapsed and case-normalised.")
    st.markdown("##### Metric definitions")
    st.markdown(f"""
- **Recorded incident:** one retained record. **Share %:** incidents ÷ incidents in the current selection.
- **Grid cell:** floor(lat/{ctx.cell_deg}), floor(lon/{ctx.cell_deg}); the centre is shown. **Hotspot rank:** by recorded incidents, ties by cell id, minimum count applied.
- **Change %:** (current − baseline) ÷ baseline, blank when the baseline is 0. **Half-period change:** second half vs first half of the selected months.
- **Weekday vs weekend:** shown per day of the week (÷5 and ÷2) because totals are not comparable.
- **Map hour filter:** map data stores {ctx.hour_block}-hour blocks, so map hour ranges are widened to whole blocks.""")
    ci = ctx.meta.get("cluster", {})
    st.markdown("##### Hotspot & clustering methodology")
    if ci.get("chosen_k"):
        st.markdown(f"K-Means (Spark MLlib, weighted by incident count) on cell centres, longitude scaled by cos(mean latitude); {ci['cells_used']:,} cells with ≥ {ci['min_cell_incidents']} incidents; "
                    f"**K = {ci['chosen_k']}** chosen by best silhouette ({ci['silhouette']}) among K = {[s['k'] for s in ci['scan']]}; seed {ci['seed']}. "
                    "Silhouette on geographic positions measures spatial compactness only; it says nothing about crime. Cluster numbers are west→east labels, **not** risk levels.")
        st.dataframe(pd.DataFrame(ci["scan"]), hide_index=True, width="content")
    else:
        st.info(ci.get("note", "Clustering output not available."))
    st.markdown("##### Limitations and possible biases")
    st.markdown("""
- Recorded crime reflects **reporting and policing practices**, not every incident that occurred; categories and definitions can change over time.
- Counts are **not rates**: there is no population, visitor or exposure denominator, so busy places naturally record more.
- Grid cells ignore neighbourhood boundaries; coordinates may be deliberately generalised (e.g. to block level) by the data publisher.
- Edge months of the dataset may be incomplete; they are flagged on trend charts.
- Rows without usable coordinates are excluded from all analyses, which can bias spatial results if missingness is not random.
- This is a **historical, descriptive** tool: it does not predict individual behaviour or future crime and must not be used for law-enforcement decisions.""")
