"""
Interactive 2D map of the protected terrestrial stations, over a real
(offline) Finland basemap. Plotly scattergeo ships Natural Earth geometry,
so country coastlines/borders render with no internet or tiles.

Produces: analysis/plots/map_interactive.html  (open in a browser)

Two toggleable layers:
  - stations, coloured by frequency band, rich hover text
  - antenna azimuth "pointers": short lines showing where each directional
    link radiates (the terrestrial analog of a coverage direction)

Run:  uv run python analysis/map_interactive.py
"""

import math
import sqlite3
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "analysis" / "frequencies.db"
OUT = ROOT / "analysis" / "plots" / "map_interactive.html"

POINTER_KM = 18.0  # length of the azimuth pointer lines

BAND_COLORS = {
    "HF (<30 MHz)": "#3b82f6",
    "VHF (30-300 MHz)": "#f59e0b",
    "UHF (0.3-3 GHz)": "#22c55e",
    "SHF (3-30 GHz)": "#ef4444",
    "EHF (>30 GHz)": "#a855f7",
    "unknown": "#9ca3af",
}


def azimuth_endpoint(lat, lon, az_deg, dist_km):
    """Simple local flat-earth offset — fine at these short distances."""
    az = math.radians(az_deg)
    dlat = (dist_km / 111.0) * math.cos(az)
    dlon = (dist_km / (111.0 * math.cos(math.radians(lat)))) * math.sin(az)
    return lat + dlat, lon + dlon


def main():
    con = sqlite3.connect(DB)
    df = pd.read_sql("""
        SELECT station_no, licence_class, lon, lat, band,
               tx_freq_mhz, power_dbw, power_valid, radiation_dir_deg,
               polarisation
        FROM frequencies
        WHERE lon IS NOT NULL AND lat IS NOT NULL
    """, con)
    con.close()

    fig = go.Figure()

    # --- station markers, one trace per band so the legend toggles bands ---
    for band, color in BAND_COLORS.items():
        s = df[df["band"] == band]
        if s.empty:
            continue
        hover = [
            f"Station {int(r.station_no)}<br>"
            f"Class: {r.licence_class or '(none)'}<br>"
            f"Freq: {r.tx_freq_mhz:.3f} MHz<br>"
            f"Power: {'%.1f dBW' % r.power_dbw if r.power_valid else 'n/a'}<br>"
            f"Azimuth: {'%.0f deg' % r.radiation_dir_deg if pd.notna(r.radiation_dir_deg) else 'ND'}"
            for r in s.itertuples()
        ]
        fig.add_trace(go.Scattergeo(
            lon=s["lon"], lat=s["lat"], mode="markers",
            marker=dict(size=6, color=color, line=dict(width=0.3, color="white")),
            name=band, text=hover, hoverinfo="text",
        ))

    # --- azimuth pointers for directional stations (off by default) ---
    d = df[df["radiation_dir_deg"].notna()]
    plon, plat = [], []
    for r in d.itertuples():
        elat, elon = azimuth_endpoint(r.lat, r.lon, r.radiation_dir_deg, POINTER_KM)
        plon += [r.lon, elon, None]   # None breaks the line between segments
        plat += [r.lat, elat, None]
    fig.add_trace(go.Scattergeo(
        lon=plon, lat=plat, mode="lines",
        line=dict(width=1, color="rgba(30,30,30,0.5)"),
        name=f"antenna azimuth ({len(d)})", hoverinfo="skip",
        visible="legendonly",
    ))

    fig.update_geos(
        scope="europe",
        lataxis_range=[59, 71], lonaxis_range=[18, 33],
        showcountries=True, countrycolor="#555",
        showland=True, landcolor="#eef3ee",
        showocean=True, oceancolor="#dce9f5",
        resolution=50,
    )
    fig.update_layout(
        title="Protected terrestrial stations in Finland (synthetic) "
              "- colour = band, toggle layers in legend",
        margin=dict(l=0, r=0, t=50, b=0),
        legend=dict(bgcolor="rgba(255,255,255,0.7)"),
    )
    # inline plotly.js so the file opens offline (no CDN dependency)
    fig.write_html(OUT, include_plotlyjs=True)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
