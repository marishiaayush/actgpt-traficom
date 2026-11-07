"""
Generality demo: score interference for ANY receiver the user supplies -- a new
fixed tower, an offshore/maritime point, or a MOVING receiver (ship/vehicle).

The scorer never hard-codes "Finland": a victim is just (lat, lon, RX frequency,
bandwidth). So a new or offshore location works unchanged. A MOVING receiver is
the new capability, and SGP4 already gives satellite positions over time, so we
evaluate the interference PFD ALONG the receiver's track: at each moment, where
is it, which satellites are overhead, and how strong is the power arriving.

This file demonstrates both against a real flagged threat
(notice 117520318 / NSL-1, incl 53.5 deg, 520 km, 18.8-19.3 GHz downlink).

Run:  uv run python analysis/custom_receiver.py
"""

import math
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from skyfield.api import wgs84

sys.path.insert(0, str(Path(__file__).resolve().parent))
from geometry_sgp4 import make_sat, TS, N_SATS
from pfd import pfd_dbw_m2
import article21

ROOT = Path(__file__).resolve().parent.parent
SRS = ROOT / "analysis" / "srs3074.db"
PLOTS = ROOT / "analysis" / "plots"
THREAT_NTC = 117520318
MIN_ELEV = 5.0


def load_threat(ntc, rx_mhz):
    """Build a sampled constellation + the worst-case effective EIRP (dBW in the
    Article-21 reference bandwidth) of the notice's emission at rx_mhz."""
    con = sqlite3.connect(SRS)
    planes = pd.read_sql("""SELECT inclin_ang, op_ht_km, long_asc FROM orbit
                            WHERE ntc_id=? AND op_ht_km IS NOT NULL""",
                         con, params=[ntc]).dropna(subset=["inclin_ang", "op_ht_km"])
    emis = pd.read_sql("""SELECT g.freq_min,g.freq_max,g.pwr_max,b.gain,g.bdwdth
                          FROM grp g JOIN s_beam b
                            ON b.ntc_id=g.ntc_id AND b.beam_name=g.beam_name
                          WHERE g.emi_rcp='E' AND g.ntc_id=? AND g.pwr_max IS NOT NULL
                            AND b.gain IS NOT NULL""", con, params=[ntc])
    con.close()
    _, ref_bw = article21.limit(rx_mhz, 10)
    if ref_bw is None:
        raise SystemExit(f"{rx_mhz} MHz is not in an Article-21 band for this demo.")
    eirp_eff = None
    for r in emis.itertuples():
        if r.freq_min <= rx_mhz <= r.freq_max:
            b_hz = r.bdwdth * 1000.0
            eff = (r.pwr_max + r.gain) - 10*math.log10(max(b_hz/ref_bw, 1.0))
            eirp_eff = max(eirp_eff, eff) if eirp_eff is not None else eff
    # sample a sub-constellation
    samp = planes.sample(min(12, len(planes)), random_state=0)
    sats = []
    for i, row in enumerate(samp.itertuples()):
        raan = row.long_asc if pd.notna(row.long_asc) else 360*i/len(samp)
        for k, ma in enumerate(np.linspace(0, 360, N_SATS, endpoint=False)):
            sats.append(make_sat(row.inclin_ang, row.op_ht_km, raan, ma, len(sats)+1))
    return sats, eirp_eff, ref_bw


def best_margin_at(sats, eirp_eff, rx_mhz, ref_bw, lat, lon, t):
    """Worst (highest) PFD margin from any visible satellite at one instant."""
    rx = wgs84.latlon(lat, lon)
    best = -999.0
    for sat in sats:
        topo = (sat - rx).at(t)
        elev = topo.altaz()[0].degrees
        if elev <= MIN_ELEV:
            continue
        d_km = topo.distance().km
        pfd = pfd_dbw_m2(eirp_eff, d_km)
        lim, _ = article21.limit(rx_mhz, elev)
        best = max(best, pfd - lim)
    return best


def demo_static(sats, eirp_eff, rx_mhz, ref_bw):
    print(f"\n--- STATIC receiver (offshore, Gulf of Bothnia) @ {rx_mhz} MHz ---")
    lat, lon = 61.5, 20.5                      # a point over open water
    # worst margin over a 24h window (real passes)
    t = TS.utc(2026, 11, 7, 0, range(0, 24*60, 1))
    margins = [best_margin_at(sats, eirp_eff, rx_mhz, ref_bw, lat, lon, t[i])
               for i in range(0, len(t.tt), 5)]
    margins = [m for m in margins if m > -900]
    if margins:
        print(f"receiver at ({lat}N,{lon}E): worst PFD margin over 24h = "
              f"{max(margins):+.1f} dB  ({'ALERT' if max(margins)>0 else 'ok'})")
    else:
        print(f"receiver at ({lat}N,{lon}E): threat never rises above {MIN_ELEV} deg")


def demo_moving(sats, eirp_eff, rx_mhz, ref_bw):
    print(f"\n--- MOVING receiver (ship across the Baltic) @ {rx_mhz} MHz ---")
    # a 6-hour voyage: SW Baltic -> Gulf of Finland
    hours = 6
    n = hours * 12                              # 5-min steps
    lat = np.linspace(58.0, 60.2, n)
    lon = np.linspace(19.0, 27.0, n)
    t = TS.utc(2026, 11, 7, 0, range(0, hours*60, 5))
    margins = np.array([best_margin_at(sats, eirp_eff, rx_mhz, ref_bw,
                                       lat[i], lon[i], t[i]) for i in range(n)])
    hrs = (t.tt - t.tt[0]) * 24
    worst = int(np.argmax(margins))
    print(f"track {lat[0]:.1f}N,{lon[0]:.1f}E -> {lat[-1]:.1f}N,{lon[-1]:.1f}E over {hours}h")
    print(f"worst encounter: margin {margins[worst]:+.1f} dB at t+{hrs[worst]:.1f}h, "
          f"position {lat[worst]:.1f}N {lon[worst]:.1f}E")
    print(f"minutes in alert (margin>0): {int(np.sum(margins>0)*5)}")

    fig, ax = plt.subplots(1, 2, figsize=(14, 5))
    m = np.where(margins > -900, margins, np.nan)
    ax[0].plot(hrs, m, color="#2b6cb0"); ax[0].axhline(0, color="#e53e3e", ls="--")
    ax[0].scatter([hrs[worst]], [margins[worst]], color="#e53e3e", zorder=5)
    ax[0].set_xlabel("hours into voyage"); ax[0].set_ylabel("PFD margin (dB)")
    ax[0].set_title("Interference along the ship track\n(margin>0 = screening alert)")
    sc = ax[1].scatter(lon, lat, c=m, cmap="RdYlBu_r", s=25)
    ax[1].scatter([lon[worst]], [lat[worst]], marker="*", s=200, color="k", zorder=5)
    plt.colorbar(sc, ax=ax[1], label="PFD margin (dB)")
    ax[1].set_xlabel("longitude"); ax[1].set_ylabel("latitude")
    ax[1].set_title("Ship track coloured by interference margin\n(star = worst)")
    fig.suptitle(f"Moving maritime receiver vs flagged LEO threat (notice {THREAT_NTC})")
    fig.tight_layout(); fig.savefig(PLOTS / "custom_receiver_moving.png", dpi=130)
    plt.close(fig)
    print(f"Plot -> {PLOTS}/custom_receiver_moving.png")


def main():
    rx_mhz = 19000.0                           # a Ka-band maritime RX frequency
    sats, eirp_eff, ref_bw = load_threat(THREAT_NTC, rx_mhz)
    print(f"Threat notice {THREAT_NTC}: {len(sats)} sampled sats, "
          f"EIRP_eff {eirp_eff:.1f} dBW in {ref_bw/1e3:.0f} kHz at {rx_mhz} MHz")
    demo_static(sats, eirp_eff, rx_mhz, ref_bw)
    demo_moving(sats, eirp_eff, rx_mhz, ref_bw)


if __name__ == "__main__":
    main()
