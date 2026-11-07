"""
Stage-2 geometry UPGRADE (prototype): real SGP4 orbit propagation via Skyfield.

The crude Stage-2 geometry (pfd_score.py) only asks "could this shell be visible
from Finland's latitude?" and -- as the experts flagged -- cannot say WHEN a
satellite is actually above the horizon or FOR HOW LONG. It also mishandles
edge cases (e.g. an equatorial LEO that never rises at 64N was still scored).

This module synthesizes a representative constellation from each IFIC notice's
real orbital planes (inclination, altitude, RAAN per plane in the `orbit` table),
propagates it with SGP4 (Skyfield, MIT-licensed -- same engine as NSF SOPP, no
AGPL), and reports time-resolved coverage over Finland:
  - max_elev_deg  : highest elevation any satellite reaches (pure geometry; does
                    NOT depend on how many we sample) -> the authoritative
                    "is this actually visible from Finland?" test
  - view_min_per_day, passes_per_day, coverage_pct : from the SAMPLED
                    sub-constellation (indicative; scale with sampling)

It does NOT replace the regulatory stages -- it feeds them better geometry.
Representative orbits != the operator's real phasing, so treat temporal stats as
screening-grade.

Run:  uv run python analysis/geometry_sgp4.py
"""

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sgp4.api import Satrec, WGS72
from skyfield.api import load, wgs84, EarthSatellite

ROOT = Path(__file__).resolve().parent.parent
import os
SRS = Path(os.environ.get("SRS_DB", ROOT / "analysis" / "srs3074.db"))
PLOTS = ROOT / "analysis" / "plots"

MU, R_E = 398600.4418, 6378.137      # km^3/s^2, km
FIN_LAT, FIN_LON = 64.5, 26.0        # representative Finland point
MIN_ELEV = 5.0                       # deg, horizon-visibility threshold
N_PLANES, N_SATS = 12, 4             # sampled sub-constellation size
WINDOW_H, STEP_MIN = 24, 1           # propagation window / resolution
JD_1949 = 2433281.5

TS = load.timescale()
EPOCH = TS.utc(2026, 11, 7, 0, 0, 0)


def make_sat(incl_deg, alt_km, raan_deg, ma_deg, satnum):
    a = R_E + alt_km
    no_kozai = np.sqrt(MU / a**3) * 60.0        # rad/min
    s = Satrec()
    s.sgp4init(WGS72, 'i', satnum, EPOCH.tt - JD_1949, 0.0, 0.0, 0.0,
               1e-6, 0.0, np.radians(incl_deg), np.radians(raan_deg),
               no_kozai, np.radians(ma_deg))
    return EarthSatellite.from_satrec(s, TS)


def constellation(planes):
    """planes: list of (incl, alt, raan). Place N_SATS per plane in mean anomaly."""
    sats, n = [], 0
    for incl, alt, raan in planes:
        for ma in np.linspace(0, 360, N_SATS, endpoint=False):
            n += 1
            sats.append(make_sat(incl, alt, raan, ma, n))
    return sats


def coverage_over_finland(sats):
    fin = wgs84.latlon(FIN_LAT, FIN_LON)
    t = TS.utc(2026, 11, 7, 0, range(0, WINDOW_H * 60, STEP_MIN))
    elev = np.vstack([(sat - fin).at(t).altaz()[0].degrees for sat in sats])
    best = elev.max(axis=0)                      # best satellite each instant
    nvis = (elev > MIN_ELEV).sum(axis=0)         # how many in view each instant
    # count passes of the single best-elevation track above threshold
    above = best > MIN_ELEV
    passes = int(np.sum(np.diff(above.astype(int)) == 1))
    return dict(
        max_elev_deg=float(best.max()),
        view_min_per_day=int(np.sum(nvis > 0) * STEP_MIN),
        passes_per_day=passes,
        coverage_pct=float(100.0 * np.mean(nvis > 0)),
        t_hours=(t.tt - t.tt[0]) * 24, best_elev=best, nvis=nvis)


def main():
    con = sqlite3.connect(SRS)
    # ALL non-GSO candidate notices (from Stage 1), so the triage can use SGP4
    # visibility for every one -- not just the already-flagged ones. Sourced
    # from fin_freq_overlap (not fin_pfd_score) to avoid a circular dependency:
    # run order is freq_overlap -> geometry_sgp4 -> pfd_score.
    flag = pd.read_sql("""SELECT DISTINCT o.sat_ntc_id, o.adm
                          FROM fin_freq_overlap o
                          WHERE o.sat_ntc_id IN (SELECT ntc_id FROM non_geo)""", con)
    rows, example = [], {}
    for r in flag.itertuples():
        pl = pd.read_sql("""SELECT inclin_ang, op_ht_km, long_asc FROM orbit
                            WHERE ntc_id=? AND op_ht_km IS NOT NULL""",
                         con, params=[r.sat_ntc_id])
        pl = pl.dropna(subset=["inclin_ang", "op_ht_km"])
        if pl.empty:
            continue
        name = pd.read_sql("SELECT sat_name FROM non_geo WHERE ntc_id=? LIMIT 1",
                           con, params=[r.sat_ntc_id])
        sat_name = name.iloc[0, 0] if len(name) else "?"
        samp = pl.sample(min(N_PLANES, len(pl)), random_state=0)
        planes = [(row.inclin_ang, row.op_ht_km,
                   row.long_asc if pd.notna(row.long_asc) else 360*i/len(samp))
                  for i, row in enumerate(samp.itertuples())]
        cov = coverage_over_finland(constellation(planes))
        rows.append(dict(sat_ntc_id=r.sat_ntc_id, adm=r.adm, sat_name=sat_name,
                         incl=round(planes[0][0], 1), alt_km=round(planes[0][1]),
                         planes_declared=len(pl), **{k: cov[k] for k in
                         ["max_elev_deg","view_min_per_day","passes_per_day","coverage_pct"]}))
        example[r.sat_ntc_id] = cov
    con.close()

    df = pd.DataFrame(rows).sort_values("max_elev_deg", ascending=False)
    df["visible_from_FIN"] = df["max_elev_deg"] > MIN_ELEV
    for c in ["max_elev_deg", "coverage_pct"]:
        df[c] = df[c].round(1)
    con2 = sqlite3.connect(SRS); df.to_sql("fin_geom_sgp4", con2, if_exists="replace", index=False); con2.close()

    print(f"\n{'='*66}\nSGP4 GEOMETRY over Finland for non-GSO candidate notices\n{'='*66}")
    print(df.to_string(index=False))
    spurious = df[~df.visible_from_FIN]
    print(f"\n*** {len(spurious)} candidate notice(s) are NOT actually visible from "
          f"Finland (max elev < {MIN_ELEV} deg) -> the crude geometry would have "
          f"scored them anyway; the triage now drops them:")
    print(spurious[["sat_ntc_id","adm","sat_name","incl","max_elev_deg"]].to_string(index=False))

    make_plot(df, example)


def make_plot(df, example):
    PLOTS.mkdir(exist_ok=True)
    # pick a clearly-visible and a not-visible example
    vis = df[df.visible_from_FIN].head(1)
    inv = df[~df.visible_from_FIN].head(1)
    picks = pd.concat([vis, inv])
    fig, axes = plt.subplots(len(picks), 1, figsize=(12, 4*len(picks)), squeeze=False)
    for ax, r in zip(axes[:, 0], picks.itertuples()):
        cov = example[r.sat_ntc_id]
        ax.plot(cov["t_hours"], cov["best_elev"], color="#2b6cb0", lw=1)
        ax.axhline(MIN_ELEV, color="#e53e3e", ls="--", lw=1, label=f"{MIN_ELEV} deg horizon")
        ax.axhline(0, color="k", lw=0.5)
        ax.set_title(f"{r.sat_name} (notice {r.sat_ntc_id}, {r.adm}) — incl {r.incl} deg, "
                     f"{r.alt_km} km — max elev {r.max_elev_deg} deg "
                     f"{'VISIBLE' if r.visible_from_FIN else 'NOT visible from Finland'}")
        ax.set_ylabel("best-satellite\nelevation (deg)"); ax.legend(fontsize=8)
    axes[-1, 0].set_xlabel("hours")
    fig.suptitle("SGP4 real passes over Finland: best-satellite elevation vs time")
    fig.tight_layout(); fig.savefig(PLOTS / "geom_sgp4.png", dpi=130)
    plt.close(fig)
    print(f"\nPlot -> {PLOTS}/geom_sgp4.png   Table -> srs3074.db :: fin_geom_sgp4")


if __name__ == "__main__":
    main()
