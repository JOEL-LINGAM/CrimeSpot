import json

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from . import components as UI
from src.config import resolve, load_config

STAGE_LABELS = {"ingest_and_map_s": "Ingest + column mapping (lazy)", "clean_and_dedup_s": "Read + clean + de-duplicate",
                "features_and_write_clean_s": "Features + write clean Parquet", "aggregations_s": "14 Spark SQL aggregates → Parquet",
                "cubes_s": "Filter cubes → Parquet", "hotspots_and_clustering_s": "Hotspot ranking + K-Means"}


def render(ctx):
    m = ctx.meta["metrics"]
    UI.hero("Big Data Performance Lab", "Measured pipeline metrics from the Spark run that produced this dataset")
    if not m:
        return UI.empty_state("No pipeline metrics file found for this dataset.")
    if m.get("is_synthetic"):
        UI.banner("These timings were measured on <b>synthetic</b> data and are only a development smoke test.")
    tot = m["total_seconds"]
    UI.kpi_cards([
        dict(label="Input records", value=UI.fmt_int(m["input_records"]), sub="rows in the raw CSV processed"),
        dict(label="Retained records", value=UI.fmt_int(m["retained_records"]), sub="after cleaning and de-duplication"),
        dict(label="Input file size", value=f"{m['input_file_bytes'] / 1e6:,.1f} MB", sub="raw CSV on disk"),
        dict(label="Total pipeline time", value=f"{tot:,.1f} s", sub=f"run at {m['run_at_utc']}"),
        dict(label="Throughput (end-to-end)", value=f"{m['records_per_second']:,.0f} rec/s", sub="input records ÷ total seconds"),
        dict(label="Spark partitions", value=f"{m['input_partitions']} in · {m['output_partitions']} out", sub=f"default parallelism {m['default_parallelism']}"),
        dict(label="Output size (Parquet)", value=f"{m['output_bytes_total'] / 1e6:,.1f} MB", sub=f"clean data: {m['output_bytes_clean'] / 1e6:,.1f} MB"),
        dict(label="Spark mode", value=m["master"], small=True, sub=f"Spark {m['spark_version']} · single machine"),
    ])
    st.write("")
    a, b = st.columns(2)
    stages = pd.DataFrame([{"stage": STAGE_LABELS.get(k, k), "seconds": v, "pct": 100 * v / tot} for k, v in m["stage_seconds"].items()])
    with a:
        fig = px.bar(stages.iloc[::-1], x="seconds", y="stage", orientation="h", custom_data=["pct"])
        fig.update_traces(marker_color=UI.C["accent"], hovertemplate="%{y}<br>%{x:.1f} s (%{customdata[0]:.0f}% of runtime)<extra></extra>")
        fig.update_xaxes(title="Seconds (wall-clock)"); fig.update_yaxes(title=None)
        UI.style_fig(fig, "Stage-wise runtime", "Measured with a wall-clock timer around each stage", 360, legend=False)
        UI.show(fig, "pf_stage")
        st.caption("Spark is lazy: the ingest stage only builds the plan, so the real CSV read cost appears in the cleaning stage.")
    with b:
        rows = pd.DataFrame([{"output": k.replace("agg_", ""), "rows": v} for k, v in m["aggregate_row_counts"].items()]).sort_values("rows")
        fig = px.bar(rows, x="rows", y="output", orientation="h")
        fig.update_traces(marker_color=UI.C["violet"], hovertemplate="%{y}: %{x:,} rows<extra></extra>")
        fig.update_xaxes(title="Output rows", type="log"); fig.update_yaxes(title=None)
        UI.style_fig(fig, "Rows in each aggregate output", "Raw records are reduced to compact Parquet tables (log scale)", 360, legend=False)
        UI.show(fig, "pf_rows")

    st.markdown("##### Runtime vs input size")
    p = resolve(load_config()["paths"]["metrics_dir"]) / f"benchmarks_{ctx.tag}.json"
    if not p.exists():
        UI.empty_state(f"No benchmark experiments recorded for '{ctx.tag}'. Run: python scripts\\run_benchmarks.py --sizes 100000 500000 --name {ctx.tag}")
    else:
        bm = json.loads(p.read_text(encoding="utf-8"))
        df = pd.DataFrame(bm["runs"])
        if bm.get("is_synthetic"):
            UI.banner("Benchmark runs below used <b>synthetic</b> data.")
        mach = bm["machine"]
        st.caption(f"Recorded {bm['recorded_at_utc']} on {mach['platform']} · {mach['logical_cpus']} logical CPU(s) · Spark {mach['spark_master']} · "
                   f"driver memory {mach['driver_memory']} · cold start for every run (includes JVM start-up).")
        c, d = st.columns(2)
        with c:
            fig = px.line(df, x="input_records", y="total_seconds", markers=True)
            fig.update_traces(line=dict(color=UI.C["amber"], width=3), hovertemplate="%{x:,} records<br>%{y:.1f} s<extra></extra>")
            fig.update_xaxes(title="Input records"); fig.update_yaxes(title="Total seconds", rangemode="tozero")
            UI.style_fig(fig, "Runtime by input size", "Measured; fixed start-up costs dominate small inputs", 330, legend=False)
            UI.show(fig, "pf_rt")
        with d:
            fig = px.line(df, x="input_records", y="records_per_second", markers=True)
            fig.update_traces(line=dict(color=UI.C["green"], width=3), hovertemplate="%{x:,} records<br>%{y:,.0f} records/s<extra></extra>")
            fig.update_xaxes(title="Input records"); fig.update_yaxes(title="Records per second", rangemode="tozero")
            UI.style_fig(fig, "Throughput by input size", "Throughput can rise with size as fixed costs are amortised", 330, legend=False)
            UI.show(fig, "pf_tp")
        st.dataframe(df[["requested_rows", "repeat", "input_records", "retained_records", "total_seconds", "records_per_second"]],
                     hide_index=True, width="stretch")
        st.caption(bm["note"] + " Run order matters: the first run in a session can include one-time warm-up costs (file cache, class loading), "
                   "so runtime may not rise smoothly with size; use --repeats for stabler numbers.")

    st.markdown("##### What is measured, and what is not")
    st.dataframe(pd.DataFrame([
        ["Input / retained records, file sizes, partitions, total + stage runtime, throughput", "Measured directly in this run"],
        ["Runtime at different input sizes", "Measured only if scripts/run_benchmarks.py was run (see above)"],
        ["Per-task / shuffle / executor metrics", "Not captured (would need the Spark UI or event logs)"],
        ["Multi-machine cluster speed-up", "Not measured: Spark runs in local mode on one computer"],
        ["Spark vs Pandas comparison", "Not measured; no claim is made that either is always faster"]],
        columns=["Metric", "Status"]), hide_index=True, width="stretch")
    with st.expander("Why PySpark, and what local mode does and does not show"):
        st.markdown("""
**Why Spark:** the raw file can exceed what is comfortable to hold in a Pandas DataFrame. Spark reads it in partitions, applies cleaning and
aggregation as a lazily-built query plan, and writes compact Parquet tables so the dashboard never touches the raw records.
**Local mode:** here Spark's executors are threads on one computer. This demonstrates the *programming model* (DataFrames, Spark SQL, partitions,
shuffles, MLlib) and out-of-core style processing, but **not** the speed-up or fault tolerance of a multi-machine cluster. The same code could run
on a cluster by changing the master URL, but that was not tested. For small data, Spark's start-up overhead can make it slower than Pandas.""")
