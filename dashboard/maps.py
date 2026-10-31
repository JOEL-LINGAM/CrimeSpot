"""PyDeck layer builders. Every map shows AGGREGATED grid cells (never raw points)."""
import math
import numpy as np
import pandas as pd
import pydeck as pdk
import streamlit as st

from . import data as D

RAMP = [(15, 23, 42), (30, 58, 138), (8, 145, 178), (253, 224, 71), (239, 68, 68)]
CLUSTER_COLORS = [(34, 211, 238), (245, 158, 11), (167, 139, 250), (52, 211, 153), (244, 114, 182),
                  (96, 165, 250), (251, 146, 60), (163, 230, 53), (232, 121, 249), (148, 163, 184)]


def ramp_color(t, alpha=190):
    t = float(np.clip(t, 0, 1)) * (len(RAMP) - 1)
    i = min(int(t), len(RAMP) - 2)
    f = t - i
    a, b = RAMP[i], RAMP[i + 1]
    return [int(a[k] + (b[k] - a[k]) * f) for k in range(3)] + [alpha]


def norm_values(v):
    """sqrt-scaled and capped at the 99th percentile so a few extreme cells do not wash out the map."""
    v = np.asarray(v, dtype=float)
    cap = np.percentile(v, 99) if len(v) else 1
    cap = cap if cap > 0 else 1
    return np.sqrt(np.clip(v / cap, 0, 1)), cap


def view_for(df, height_px=560):
    if df is None or df.empty:
        return pdk.ViewState(latitude=0, longitude=0, zoom=1)
    lat0, lat1, lon0, lon1 = df.cell_lat.min(), df.cell_lat.max(), df.cell_lon.min(), df.cell_lon.max()
    span = max(lat1 - lat0, (lon1 - lon0) * math.cos(math.radians((lat0 + lat1) / 2)), 0.01)
    zoom = max(3.0, min(14.0, math.log2(360 / span) - 0.9))
    return pdk.ViewState(latitude=float((lat0 + lat1) / 2), longitude=float((lon0 + lon1) / 2), zoom=zoom, pitch=0)


def legend(cap, what="incidents per grid cell"):
    st.markdown(f'<div class="cs-legend"><span>low</span><div class="cs-grad"></div><span>high</span>'
                f'<span>· colour = {what} (sqrt scale, capped at the 99th percentile = {int(cap):,})</span></div>',
                unsafe_allow_html=True)


def _deck(layers, df, tooltip_html, height):
    return pdk.Deck(layers=layers, initial_view_state=view_for(df, height), map_style="dark",
                    tooltip={"html": tooltip_html, "style": {"backgroundColor": "#0f172a", "color": "#e5e7eb",
                                                              "border": "1px solid #1e2b45", "fontSize": "12px"}})


def by_cell(cell_df):
    return cell_df.groupby(["cell_id", "cell_lat", "cell_lon"], as_index=False)["incidents"].sum()


def heatmap_deck(cell_df, height=560):
    g = by_cell(cell_df)
    g["location"] = [D.cell_label(a, b) for a, b in zip(g.cell_lat, g.cell_lon)]
    heat = pdk.Layer("HeatmapLayer", data=g, get_position="[cell_lon, cell_lat]", get_weight="incidents",
                     aggregation="SUM", radiusPixels=45, intensity=1.2, threshold=0.04,
                     color_range=[[15, 23, 42, 0], [30, 58, 138, 140], [8, 145, 178, 190], [253, 224, 71, 220],
                                  [239, 68, 68, 245], [255, 255, 255, 255]])
    pick = pdk.Layer("ScatterplotLayer", data=g, get_position="[cell_lon, cell_lat]", get_radius=150,
                     radius_min_pixels=3, radius_max_pixels=14, get_fill_color=[255, 255, 255, 30], pickable=True)
    return _deck([heat, pick], g, "<b>{location}</b><br/>Recorded incidents: {incidents}", height), g


def grid_deck(cell_df, cell_deg, height=560, highlight_ids=()):
    g = by_cell(cell_df)
    t, cap = norm_values(g.incidents)
    g["location"] = [D.cell_label(a, b) for a, b in zip(g.cell_lat, g.cell_lon)]
    g["polygon"] = [D.cell_polygon(a, b, cell_deg) for a, b in zip(g.cell_lat, g.cell_lon)]
    g["fill"] = [ramp_color(x) for x in t]
    g["line"] = [[255, 255, 255, 255] if c in set(highlight_ids) else [255, 255, 255, 25] for c in g.cell_id]
    layer = pdk.Layer("PolygonLayer", data=g[["polygon", "fill", "line", "incidents", "location"]], get_polygon="polygon",
                      get_fill_color="fill", get_line_color="line", line_width_min_pixels=1, stroked=True,
                      filled=True, pickable=True, auto_highlight=True)
    return _deck([layer], g, "<b>{location}</b><br/>Recorded incidents: {incidents}", height), g, cap


def cluster_deck(cell_df, assign, summary, cell_deg, height=560):
    """cell_df: filtered cube_cell; assign: cell_id->cluster_no/label; summary: cluster_summary (centroids)."""
    g = by_cell(cell_df).merge(assign, on="cell_id", how="inner")
    g["location"] = [D.cell_label(a, b) for a, b in zip(g.cell_lat, g.cell_lon)]
    g["color"] = [list(CLUSTER_COLORS[(n - 1) % len(CLUSTER_COLORS)]) + [200] for n in g.cluster_no]
    g["polygon"] = [D.cell_polygon(a, b, cell_deg) for a, b in zip(g.cell_lat, g.cell_lon)]
    cells = pdk.Layer("PolygonLayer", data=g[["polygon", "color", "incidents", "location", "cluster_label"]],
                      get_polygon="polygon", get_fill_color="color", get_line_color=[255, 255, 255, 30],
                      line_width_min_pixels=1, stroked=True, pickable=True, auto_highlight=True)
    s = summary.copy()
    s["pos"] = [[lo, la] for la, lo in zip(s.centroid_lat, s.centroid_lon)]
    labels = pdk.Layer("TextLayer", data=s[["pos", "cluster_label"]], get_position="pos", get_text="cluster_label",
                       get_size=14, get_color=[255, 255, 255, 255], get_alignment_baseline="'center'",
                       background=True, get_background_color=[11, 18, 32, 200])
    return _deck([cells, labels], g, "<b>{location}</b><br/>{cluster_label}<br/>Recorded incidents: {incidents}", height), g
