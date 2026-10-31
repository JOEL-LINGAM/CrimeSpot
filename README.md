# CrimeScope

Large-scale **historical** crime pattern analysis with PySpark and an 8-page Streamlit dashboard.
Descriptive analytics only: no prediction of individuals or future crime. No Bloom Filters, no databases, no paid services.

## Status (what is really done)
| Phase | Status |
|---|---|
| 1-2 Ingestion, cleaning, features, Spark SQL aggregates, Parquet, metrics | Done, tested |
| 3 Hotspot ranking + MLlib K-Means | Done, tested |
| 4 Streamlit dashboard, 8 pages | Done; renders headlessly; **not yet seen in a real browser by the author** |
| 5 Real-data run + benchmarks on real data | **You must do this** (no internet access to the Chicago portal here) |
| 6 docs/ (architecture, methodology, slides, viva, report) | Not written yet |

Everything so far was developed and tested on **Linux, Python 3.12, Java 21, 1 CPU / 3 GB RAM, with synthetic data only**.
Windows and real-data behaviour are untested. The ZIP includes pipeline output for the synthetic sample (`data/processed/sample/`) so the dashboard opens immediately; it is clearly bannered as SYNTHETIC.

## Windows PowerShell setup
```powershell
python --version                  # 3.10 - 3.13
java -version                     # 17 or 21 required (e.g. Eclipse Temurin)
cd CrimeScope
python -m venv .venv
.\.venv\Scripts\Activate.ps1      # if blocked: Set-ExecutionPolicy -Scope Process Bypass
pip install -r requirements.txt
```

## Run with the synthetic sample (development)
```powershell
python scripts\make_sample_data.py --rows 20000
python scripts\run_pipeline.py --config config\config.sample.yaml --input data\sample\synthetic_sample.csv --tag sample
python scripts\run_benchmarks.py --config config\config.sample.yaml --input data\sample\synthetic_sample.csv --sizes 2000 6000 12000 --name sample
streamlit run app.py
```

## Switch to the REAL Chicago dataset
1. Open the dataset page in `config/config.yaml` (`dataset.source_url`, "Crimes - 2001 to Present", City of Chicago Data Portal), export as **CSV**, save as `data\raw\crimes.csv`. Check the portal's terms for attribution.
2. Check it: `python scripts\validate_dataset.py` (prints the columns found and how they were mapped; stops with a clear message if required columns are missing).
3. Try a slice first: `python scripts\run_pipeline.py --limit 500000 --tag trial`
4. Full run: `python scripts\run_pipeline.py` (writes `data\processed\full\`). The file is large; if you run out of memory lower `spark.driver_memory`/`output_partitions` in `config\config.yaml`.
5. `streamlit run app.py`. The sidebar **Dataset** dropdown lists every processed folder; `full` is the default when it exists. To force one: `$env:CRIMESCOPE_TAG="sample"; streamlit run app.py`.
6. Optional real benchmarks: `python scripts\run_benchmarks.py --sizes 100000 500000 0 --name full` (0 = whole file).
For another dataset edit `columns:` (name mapping), `timestamp_formats`, and the `validation` bounding box in `config\config.yaml`.

## Tests
```powershell
python -m pytest -q
```
The dashboard smoke tests are skipped unless `data\processed\sample` exists (run the sample pipeline first).

## Dashboard pages
Executive Overview · Interactive Crime Map (density heatmap, grid cells, K-Means clusters, category-specific) · Temporal Patterns · Category Explorer ·
Hotspot Intelligence · Comparative Analytics (areas / categories / periods) · Big Data Performance Lab · Data Quality & Methodology.
Sidebar filters (dataset, month range, categories, hour range, day type) apply to all pages; each page states where a cube cannot honour a filter.

## How it works
`scripts/run_pipeline.py` (Spark) -> cleaned Parquet + 14 aggregates + 4 filter "cubes" + hotspot table + K-Means clusters + JSON metrics -> the dashboard reads only those small Parquet files (cached). Spark is never started by the dashboard.

## Windows troubleshooting
- `JAVA_HOME is not set` / `Java gateway process exited`: install Java 17/21, `setx JAVA_HOME "C:\Program Files\Eclipse Adoptium\jdk-21..."`, reopen PowerShell.
- `HADOOP_HOME and hadoop.home.dir are unset` or `NativeIO$Windows` when writing Parquet: put `winutils.exe` + `hadoop.dll` (Hadoop 3.x) in `C:\hadoop\bin`, then `setx HADOOP_HOME C:\hadoop`.
- `Python worker failed to connect`: run from the activated venv.
- Map shows no background: base-map tiles need internet; data layers still draw.

## Known limitations / incomplete
- Not tested on Windows, on the real dataset, or visually in a browser (verified: headless AppTest renders, server starts and reports healthy).
- No optional point-level map exploration or sampling; maps are aggregated grid cells only.
- Area (e.g. community area) filtering is page-level, not global: the area cubes lack some grains (see notes on pages).
- Map hour filter works in 3-hour blocks (`analytics.map_hour_block`); the cell cube size on 8M+ rows is untested and may be heavy for a laptop.
- `data/processed/<tag>/hotspots` (full-data ranking with 12-month trend columns) is written but the dashboard recomputes rankings from filtered cubes instead.
- K is chosen by silhouette on geography only; it measures spatial compactness, not crime.
- docs/ deliverables and report template are still to do.
