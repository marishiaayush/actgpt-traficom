"""
Interactive PFD explainer -> analysis/plots/pfd_explainer.html

Drag the EIRP slider and watch each orbit family's power-flux-density curve
rise/fall against the Article-21 limit. Where a curve pokes ABOVE the dashed
limit line = a PFD exceedance = a flagged concern.

Key teaching points baked in:
  - PFD depends on elevation angle (x-axis) because slant distance does.
  - LEO curves sit far above GSO (same EIRP) -> the ~29-36 dB "LEO is hot" gap.
  - The limit is STRICTEST at low elevation -> exactly Finland's GSO regime
    (shaded band: a GSO bird is only ever seen from Finland below ~20 deg).

How it ties to the ground data: PFD is the flux arriving at the Earth's
SURFACE at a given location. Every protected Finnish station at that spot is
exposed to it; the Article-21 limit protects them generically, without needing
each station's own antenna. (The station-specific I/N refinement comes later.)

Run:  uv run python analysis/pfd_explainer.py
"""

from pathlib import Path

import numpy as np
import plotly.graph_objects as go

from pfd import (slant_range_km, pfd_dbw_m2, article21_limit_dbw_m2,
                 gso_max_elevation_deg)

OUT = Path(__file__).resolve().parent / "plots" / "pfd_explainer.html"

ORBITS = [("GSO (35 786 km)", 35786.0, "#2b6cb0"),
          ("MEO (8 000 km)", 8000.0, "#38a169"),
          ("LEO (1 200 km)", 1200.0, "#d69e2e"),
          ("LEO (600 km)", 600.0, "#e53e3e")]
ELEV = np.linspace(1, 90, 90)
EIRP_STEPS = list(range(-20, 41, 5))   # dBW per MHz
DEFAULT_IDX = EIRP_STEPS.index(10)
REF_BW = 1.0

# Finland can only see a GSO bird below this elevation (same-longitude best case)
FIN_GSO_MAX = gso_max_elevation_deg(62.0)


def pfd_curve(eirp, alt):
    d = np.array([slant_range_km(e, alt) for e in ELEV])
    return np.array([pfd_dbw_m2(eirp, dd, ref_bw_mhz=REF_BW) for dd in d]), d


def main():
    fig = go.Figure()

    # constant limit curve
    lim = np.array([article21_limit_dbw_m2(e) for e in ELEV])
    fig.add_trace(go.Scatter(
        x=ELEV, y=lim, mode="lines", name="Article-21 limit (illustrative)",
        line=dict(color="black", dash="dash", width=2), hoverinfo="skip"))

    # one set of orbit traces per EIRP step; only DEFAULT visible initially
    steps = []
    for si, eirp in enumerate(EIRP_STEPS):
        idxs = []
        for name, alt, color in ORBITS:
            pfd, d = pfd_curve(eirp, alt)
            fig.add_trace(go.Scatter(
                x=ELEV, y=pfd, mode="lines", name=name,
                line=dict(color=color, width=2.5),
                visible=(si == DEFAULT_IDX),
                customdata=np.stack([d, pfd - np.array([article21_limit_dbw_m2(e) for e in ELEV])], axis=-1),
                hovertemplate=(name + "<br>elev %{x:.0f} deg"
                               "<br>slant %{customdata[0]:,.0f} km"
                               "<br>PFD %{y:.1f} dBW/m2/MHz"
                               "<br>margin %{customdata[1]:+.1f} dB<extra></extra>")))
            idxs.append(len(fig.data) - 1)
        steps.append((eirp, idxs))

    # slider: toggle which EIRP block is visible (limit=trace 0 always on)
    n_total = len(fig.data)
    slider_steps = []
    for eirp, idxs in steps:
        vis = [False] * n_total
        vis[0] = True
        for i in idxs:
            vis[i] = True
        slider_steps.append(dict(method="update", label=f"{eirp}",
                                 args=[{"visible": vis}]))
    fig.update_layout(sliders=[dict(active=DEFAULT_IDX, steps=slider_steps,
                                    currentvalue=dict(prefix="Satellite EIRP = ",
                                                      suffix=" dBW/MHz"),
                                    pad=dict(t=40))])

    # shade Finland's GSO elevation regime
    fig.add_vrect(x0=0, x1=FIN_GSO_MAX, fillcolor="#3182ce", opacity=0.08,
                  line_width=0, annotation_text=f"Finland's GSO arc (<={FIN_GSO_MAX:.0f}deg)",
                  annotation_position="top left")

    fig.update_layout(
        title="PFD vs elevation angle — drag EIRP; curves above the dashed "
              "limit = flagged exceedances",
        xaxis_title="arrival elevation angle (deg)  —  low = grazing the horizon",
        yaxis_title="PFD at surface (dBW/m2 per MHz)",
        template="plotly_white", height=620,
        legend=dict(orientation="h", y=1.08))
    fig.write_html(OUT, include_plotlyjs=True)
    print(f"Wrote {OUT}")
    print(f"Finland GSO max elevation used for shaded band: {FIN_GSO_MAX:.1f} deg")


if __name__ == "__main__":
    main()
