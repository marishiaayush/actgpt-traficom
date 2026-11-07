"""
3D projection-cone view of the FLAGGED satellites over Finland.

For each flagged notice (worst-case PFD exceedance in fin_pfd_score) we draw its
visibility footprint as a cone: apex at the satellite, base = the circle on
Earth from which the satellite is above the horizon. Where that footprint covers
Finland is where it can interfere.

  - GSO: satellite at its orbital slot (geo.long_nom, on the equator, 35 786 km).
    Footprint is huge (~81 deg half-angle); the cone reaches far across Earth.
  - non-GSO: no fixed position, so we place a REPRESENTATIVE overpass directly
    above Finland at the constellation's altitude (the worst-case geometry the
    triage used). Footprint is small and tight around Finland.

Scene is normalized to Earth radius = 1 (so GSO sits at 6.6, LEO ~1.08). The
Finnish protected stations are plotted on the surface and literally outline
Finland.

Run:  uv run python analysis/footprint_3d.py  ->  analysis/plots/footprint_3d.html
"""

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
SRS = ROOT / "analysis" / "srs3074.db"
FIN = ROOT / "analysis" / "frequencies.db"
OUT = ROOT / "analysis" / "plots" / "footprint_3d_v2.html"

R_E = 6371.0
GSO_ALT = 35786.0
FIN_LON, FIN_LAT = 26.0, 64.5          # representative Finland centroid
GSO_COL, NGSO_COL = "#d69e2e", "#e53e3e"


def unit(lon, lat):
    lo, la = np.radians(lon), np.radians(lat)
    return np.array([np.cos(la)*np.cos(lo), np.cos(la)*np.sin(lo), np.sin(la)])


def ring(u, gamma_deg, m=60):
    """m points on the unit sphere at angular radius gamma around direction u."""
    g = np.radians(gamma_deg)
    # two orthonormal vectors perpendicular to u
    a = np.array([0, 0, 1.0]) if abs(u[2]) < 0.9 else np.array([1.0, 0, 0])
    e1 = np.cross(u, a); e1 /= np.linalg.norm(e1)
    e2 = np.cross(u, e1)
    t = np.linspace(0, 2*np.pi, m)
    pts = (np.cos(g)*u[:, None]
           + np.sin(g)*(np.cos(t)*e1[:, None] + np.sin(t)*e2[:, None]))
    return pts  # shape (3, m), already unit length


def cone_mesh(apex, ring_pts, color, name, group, show):
    m = ring_pts.shape[1]
    xs = np.concatenate([[apex[0]], ring_pts[0]])
    ys = np.concatenate([[apex[1]], ring_pts[1]])
    zs = np.concatenate([[apex[2]], ring_pts[2]])
    i = np.zeros(m, int); j = np.arange(1, m+1); k = np.arange(2, m+2); k[-1] = 1
    return go.Mesh3d(x=xs, y=ys, z=zs, i=i, j=j, k=k, color=color,
                     opacity=0.18, name=name, legendgroup=group,
                     showlegend=show, hoverinfo="skip")


def earth_surface():
    u = np.linspace(0, 2*np.pi, 60); v = np.linspace(0, np.pi, 30)
    x = np.outer(np.cos(u), np.sin(v))
    y = np.outer(np.sin(u), np.sin(v))
    z = np.outer(np.ones_like(u), np.cos(v))
    return go.Surface(x=x, y=y, z=z, showscale=False, opacity=0.35,
                      colorscale=[[0, "#cfe3f5"], [1, "#cfe3f5"]],
                      hoverinfo="skip", name="Earth", showlegend=False)


def render_static(foots, stn_xyz, lim=1.35):
    """Static PNG snapshot (GitHub-viewable). View zoomed on Earth so footprint
    rings + non-GSO cones show; GSO apexes sit off-frame (cone edges enter)."""
    fig = plt.figure(figsize=(9, 9))
    ax = fig.add_subplot(projection="3d")
    # Earth
    u = np.linspace(0, 2*np.pi, 40); v = np.linspace(0, np.pi, 20)
    ax.plot_surface(np.outer(np.cos(u), np.sin(v)), np.outer(np.sin(u), np.sin(v)),
                    np.outer(np.ones_like(u), np.cos(v)), color="#cfe3f5",
                    alpha=0.3, linewidth=0, shade=False)
    ax.scatter(stn_xyz[0], stn_xyz[1], stn_xyz[2], s=1, c="#2f855a")
    for f in foots:
        rp = f["ring"]
        ax.plot(rp[0], rp[1], rp[2], color=f["col"], lw=1.2)        # footprint
        for idx in range(0, rp.shape[1], 10):                      # cone edges
            ax.plot([f["apex"][0], rp[0, idx]], [f["apex"][1], rp[1, idx]],
                    [f["apex"][2], rp[2, idx]], color=f["col"], lw=0.3, alpha=0.5)
    ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim); ax.set_zlim(-lim, lim)
    ax.set_box_aspect((1, 1, 1)); ax.set_axis_off()
    ax.view_init(elev=38, azim=60)
    ax.set_title("Flagged-satellite footprints over Finland\n"
                 "gold = GSO (far, wide cones)   red = non-GSO (tight over FIN)")
    fig.savefig(OUT.with_name("footprint_3d_v2.png"), dpi=130, bbox_inches="tight")
    plt.close(fig)


def main():
    srs = sqlite3.connect(SRS)
    flag = pd.read_sql("""
        SELECT sat_ntc_id, adm, is_gso, MAX(margin) margin
        FROM fin_pfd_score WHERE status='scored' AND margin>0
        GROUP BY sat_ntc_id, adm, is_gso""", srs)
    geo = pd.read_sql(
        "SELECT ntc_id, MIN(long_nom) long_nom FROM geo GROUP BY ntc_id", srs)
    orb = pd.read_sql(
        "SELECT ntc_id, MIN(op_ht_km) alt FROM orbit GROUP BY ntc_id", srs)
    flag = (flag.merge(geo, left_on="sat_ntc_id", right_on="ntc_id", how="left")
                .merge(orb, left_on="sat_ntc_id", right_on="ntc_id", how="left"))
    srs.close()
    fin = sqlite3.connect(FIN)
    stn = pd.read_sql("SELECT lon, lat FROM v_clean WHERE lon IS NOT NULL", fin)
    fin.close()

    fig = go.Figure()
    fig.add_trace(earth_surface())

    # Finnish protected stations outline Finland
    s = unit(stn["lon"].values, stn["lat"].values)
    fig.add_trace(go.Scatter3d(x=s[0], y=s[1], z=s[2], mode="markers",
                  marker=dict(size=1.6, color="#2f855a"),
                  name="Finnish protected stations", hoverinfo="skip"))

    # build the footprint geometry once; render to both plotly and a static PNG
    foots = []
    for r in flag.itertuples():
        is_gso = bool(r.is_gso)
        if is_gso:
            if pd.isna(r.long_nom):
                continue
            u = unit(r.long_nom, 0.0); h = GSO_ALT
            col, grp, lab = GSO_COL, "gso", "GSO footprint cone"
            sub = f"slot {r.long_nom:.1f}E"
        else:
            if pd.isna(r.alt):
                continue
            u = unit(FIN_LON, FIN_LAT); h = r.alt
            col, grp, lab = NGSO_COL, "ngso", "non-GSO footprint cone (over FIN)"
            sub = f"{r.alt:.0f} km overpass"
        r_sat = 1.0 + h/R_E
        gamma = np.degrees(np.arccos(1.0/r_sat))     # horizon half-angle
        foots.append(dict(u=u, apex=r_sat*u, ring=ring(u, gamma), col=col,
                          grp=grp, lab=lab, is_gso=is_gso,
                          hover=f"notice {int(r.sat_ntc_id)} ({r.adm})<br>"
                                f"{'GSO '+sub if is_gso else 'non-GSO '+sub}<br>"
                                f"worst margin {r.margin:.1f} dB"))

    first = {"gso": True, "ngso": True}
    for f in foots:
        show = first[f["grp"]]; first[f["grp"]] = False
        fig.add_trace(cone_mesh(f["apex"], f["ring"], f["col"], f["lab"],
                                f["grp"], show))
        rp = f["ring"]
        fig.add_trace(go.Scatter3d(x=rp[0], y=rp[1], z=rp[2], mode="lines",
                      line=dict(color=f["col"], width=3), legendgroup=f["grp"],
                      showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter3d(x=[f["apex"][0]], y=[f["apex"][1]],
                      z=[f["apex"][2]], mode="markers",
                      marker=dict(size=4, color=f["col"]),
                      legendgroup=f["grp"], showlegend=False,
                      text=[f["hover"]], hoverinfo="text"))

    render_static(foots, s)
    fig.update_layout(
        title="Flagged satellites — visibility footprint cones over Finland "
              "(Earth radius = 1; GSO gold, non-GSO red)",
        scene=dict(xaxis=dict(visible=False), yaxis=dict(visible=False),
                   zaxis=dict(visible=False), aspectmode="data"),
        legend=dict(orientation="h", y=0.02))
    fig.write_html(OUT, include_plotlyjs=True)
    print(f"Wrote {OUT}  ({len(flag)} flagged notices)")


if __name__ == "__main__":
    main()
