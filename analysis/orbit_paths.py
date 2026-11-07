"""
Simulated orbit ground tracks of the FLAGGED satellites (SGP4 via Skyfield).

For each flagged notice we propagate one representative satellite and plot its
sub-satellite point (the spot on Earth directly beneath it) over ~2 orbits -- the
"ground track". It shows, concretely, the simulated path each flagged system
sweeps and whether it passes over Finland.
  - non-GSO: a sine-like track whose latitude amplitude = orbital inclination,
    drifting west each orbit as Earth turns.
  - GSO: a fixed point on the equator at the slot longitude (stays put).

Outputs: plots/orbit_paths.html (interactive, real coastlines) + .png (static).

Run:  uv run python analysis/orbit_paths.py
"""

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import plotly.graph_objects as go
from skyfield.api import load, wgs84

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from geometry_sgp4 import make_sat, TS

ROOT = Path(__file__).resolve().parent.parent
SRS = ROOT / "analysis" / "srs3074.db"
PLOTS = ROOT / "analysis" / "plots"
FIN_LAT, FIN_LON = 64.5, 26.0


def ground_track(incl, alt, raan, minutes=200, step=1):
    sat = make_sat(incl, alt, raan, 0.0, 1)
    t = TS.utc(2026, 11, 7, 0, range(0, minutes, step))
    sp = wgs84.subpoint(sat.at(t))
    return sp.longitude.degrees, sp.latitude.degrees


def collect():
    con = sqlite3.connect(SRS)
    flag = pd.read_sql("""SELECT DISTINCT sat_ntc_id, adm, is_gso FROM fin_pfd_score
                          WHERE status='scored' AND margin>0""", con)
    tracks = []
    for r in flag.itertuples():
        if r.is_gso:
            g = pd.read_sql("SELECT MIN(long_nom) lon FROM geo WHERE ntc_id=?",
                            con, params=[r.sat_ntc_id]).iloc[0, 0]
            name = pd.read_sql("SELECT sat_name FROM geo WHERE ntc_id=? LIMIT 1",
                               con, params=[r.sat_ntc_id])
            if pd.isna(g):
                continue
            tracks.append(dict(ntc=r.sat_ntc_id, adm=r.adm, gso=True,
                               name=(name.iloc[0, 0] if len(name) else "?"),
                               lon=np.array([g]), lat=np.array([0.0])))
        else:
            pl = pd.read_sql("""SELECT inclin_ang, op_ht_km, long_asc FROM orbit
                                WHERE ntc_id=? AND op_ht_km IS NOT NULL LIMIT 1""",
                             con, params=[r.sat_ntc_id])
            name = pd.read_sql("SELECT sat_name FROM non_geo WHERE ntc_id=? LIMIT 1",
                               con, params=[r.sat_ntc_id])
            if pl.empty:
                continue
            p = pl.iloc[0]
            lon, lat = ground_track(p.inclin_ang, p.op_ht_km,
                                    p.long_asc if pd.notna(p.long_asc) else 0.0)
            tracks.append(dict(ntc=r.sat_ntc_id, adm=r.adm, gso=False,
                               name=(name.iloc[0, 0] if len(name) else "?"),
                               lon=lon, lat=lat))
    con.close()
    return tracks


def plot_interactive(tracks):
    fig = go.Figure()
    for tr in tracks:
        lab = f"{tr['name']} ({tr['ntc']}, {tr['adm']})"
        if tr["gso"]:
            fig.add_trace(go.Scattergeo(lon=tr["lon"], lat=tr["lat"], mode="markers",
                marker=dict(size=9, symbol="star", color="#d69e2e"),
                name=f"GSO: {lab}"))
        else:
            fig.add_trace(go.Scattergeo(lon=tr["lon"], lat=tr["lat"], mode="lines",
                line=dict(width=1.5), name=lab))
    fig.add_trace(go.Scattergeo(lon=[FIN_LON], lat=[FIN_LAT], mode="markers+text",
        marker=dict(size=10, color="#2f855a", symbol="circle"),
        text=["FINLAND"], textposition="top center", name="Finland"))
    fig.update_geos(projection_type="natural earth", showcountries=True,
                    showland=True, landcolor="#eef3ee", oceancolor="#dce9f5",
                    showocean=True, lataxis_showgrid=True, lonaxis_showgrid=True)
    fig.update_layout(title="Simulated ground tracks of FLAGGED satellites (SGP4) "
                      "— ~2 orbits; GSO = fixed star; green = Finland",
                      height=680, legend=dict(font=dict(size=8)))
    fig.write_html(PLOTS / "orbit_paths.html", include_plotlyjs=True)


def plot_static(tracks):
    fig, ax = plt.subplots(figsize=(13, 7))
    for tr in tracks:
        if tr["gso"]:
            ax.scatter(tr["lon"], tr["lat"], marker="*", s=120, color="#d69e2e",
                       zorder=5, edgecolor="k", linewidth=0.3)
        else:
            # split the line where it wraps around +-180 lon to avoid streaks
            lon = tr["lon"].copy()
            jump = np.where(np.abs(np.diff(lon)) > 180)[0]
            lon_plot = lon.astype(float)
            for j in jump:
                lon_plot[j+1:] = np.nan if False else lon_plot[j+1:]
            segs = np.split(np.arange(len(lon)), jump + 1)
            for s in segs:
                ax.plot(lon[s], tr["lat"][s], lw=0.9, alpha=0.8)
    ax.scatter([FIN_LON], [FIN_LAT], s=90, color="#2f855a", zorder=6,
               edgecolor="k", label="Finland")
    ax.axhline(FIN_LAT, color="#2f855a", ls=":", lw=0.6)
    ax.axhline(0, color="grey", lw=0.5)       # equator
    ax.set_xlim(-180, 180); ax.set_ylim(-90, 90)
    ax.set_xlabel("longitude"); ax.set_ylabel("latitude")
    ax.set_title("Simulated ground tracks of flagged satellites (SGP4, ~2 orbits)\n"
                 "gold stars = GSO slots; green = Finland")
    ax.legend(loc="lower left")
    fig.tight_layout(); fig.savefig(PLOTS / "orbit_paths.png", dpi=130)
    plt.close(fig)


def main():
    PLOTS.mkdir(exist_ok=True)
    tracks = collect()
    print(f"flagged satellites plotted: {len(tracks)} "
          f"(GSO {sum(t['gso'] for t in tracks)}, non-GSO {sum(not t['gso'] for t in tracks)})")
    plot_interactive(tracks)
    plot_static(tracks)
    print(f"Plots -> {PLOTS}/orbit_paths.html, orbit_paths.png")


if __name__ == "__main__":
    main()
