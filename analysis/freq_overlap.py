"""
STEP 1 of Finland-relevance filtering: frequency overlap.

Which IFIC 3074 satellite emissions share frequency with Finnish protected
stations? This is the cheap, necessary first gate (geometry + PFD come later).

Direction matters: a satellite *emission* (emi_rcp='E', space->Earth downlink)
is what raises power at a Finnish *receiver*, so we test satellite E-bands
against the protected stations' channels. (emi_rcp='R' = uplink, the satellite
receiving; kept out of the primary candidate set.)

Interval overlap rule: bands [a_lo,a_hi] and [b_lo,b_hi] overlap iff
    a_lo <= b_hi AND b_lo <= a_hi

Outputs:
  - table `fin_freq_overlap` in srs3074.db (one row per sat-band x station hit)
  - prints a summary (candidates by administration, by band)
  - plots written by make_overlap_plots()

Run:  uv run python analysis/freq_overlap.py
"""

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
SRS = ROOT / "analysis" / "srs3074.db"
FIN = ROOT / "analysis" / "frequencies.db"
PLOTS = ROOT / "analysis" / "plots"


def band_label(mhz):
    if mhz < 30:   return "HF"
    if mhz < 300:  return "VHF"
    if mhz < 3000: return "UHF"
    if mhz < 30000:return "SHF"
    return "EHF"


def load_bands():
    # Finnish protected station channels: [tx - bw/2, tx + bw/2] in MHz.
    fcon = sqlite3.connect(FIN)
    p = pd.read_sql("""
        SELECT station_no, licence_class, tx_freq_mhz, channel_bw_mhz, band
        FROM v_clean WHERE tx_freq_mhz IS NOT NULL
    """, fcon)
    fcon.close()
    bw = p["channel_bw_mhz"].fillna(0.0) / 2.0
    p["lo"] = p["tx_freq_mhz"] - bw
    p["hi"] = p["tx_freq_mhz"] + bw

    # Satellite emission bands (downlink). Dedupe to distinct notice/band.
    scon = sqlite3.connect(SRS)
    s = pd.read_sql("""
        SELECT DISTINCT g.ntc_id, n.adm, g.freq_min AS lo, g.freq_max AS hi
        FROM grp g JOIN notice n ON n.ntc_id = g.ntc_id
        WHERE g.emi_rcp = 'E'
          AND g.freq_min IS NOT NULL AND g.freq_max IS NOT NULL
    """, scon)
    scon.close()
    return p, s


def compute_overlap(p, s):
    rows = []
    lo = p["lo"].to_numpy(); hi = p["hi"].to_numpy()
    for b in s.itertuples():
        m = (b.lo <= hi) & (lo <= b.hi)          # vectorized interval overlap
        if not m.any():
            continue
        hit = p[m]
        ov_lo = np.maximum(b.lo, hit["lo"].to_numpy())
        ov_hi = np.minimum(b.hi, hit["hi"].to_numpy())
        for i, st in enumerate(hit.itertuples()):
            rows.append((b.ntc_id, b.adm, b.lo, b.hi, st.station_no,
                         st.licence_class, st.tx_freq_mhz,
                         float(ov_lo[i]), float(ov_hi[i]), st.band))
    cols = ["sat_ntc_id", "adm", "sat_lo_mhz", "sat_hi_mhz", "station_no",
            "licence_class", "station_freq_mhz", "overlap_lo_mhz",
            "overlap_hi_mhz", "band"]
    return pd.DataFrame(rows, columns=cols)


def save_and_report(ov):
    con = sqlite3.connect(SRS)
    ov.to_sql("fin_freq_overlap", con, if_exists="replace", index=False)
    con.close()

    print(f"\n{'='*58}\nFREQUENCY-OVERLAP CANDIDATES (IFIC 3074 downlinks vs FIN)\n{'='*58}")
    print(f"overlap pairs           : {len(ov)}")
    print(f"satellite notices hit   : {ov['sat_ntc_id'].nunique()} "
          f"(of 196 total)")
    print(f"protected stations hit  : {ov['station_no'].nunique()}")
    print("\nby administration (top 12, # notices touching FIN bands):")
    print(ov.groupby("adm")["sat_ntc_id"].nunique()
            .sort_values(ascending=False).head(12).to_string())
    print("\nby band (# overlap pairs):")
    print(ov["band"].value_counts().to_string())


def make_overlap_plots(p, s, ov):
    PLOTS.mkdir(exist_ok=True)

    # ---- mirror spectrum: where sat downlinks and FIN stations coincide ----
    edges = np.logspace(np.log10(100), np.log10(30000), 70)  # 100 MHz..30 GHz
    centers = np.sqrt(edges[:-1] * edges[1:])

    sat_cov = np.zeros(len(centers))   # # distinct sat notices covering each bin
    for i, (a, b) in enumerate(zip(edges[:-1], edges[1:])):
        sat_cov[i] = s.loc[(s["lo"] <= b) & (a <= s["hi"]), "ntc_id"].nunique()
    fin_cnt, _ = np.histogram(p["tx_freq_mhz"], bins=edges)

    fig, ax = plt.subplots(figsize=(13, 6))
    ax.bar(centers, sat_cov, width=np.diff(edges), align="center",
           color="#2b6cb0", alpha=0.85, label="satellite downlink notices (3074)")
    ax.bar(centers, -fin_cnt, width=np.diff(edges), align="center",
           color="#2f855a", alpha=0.85, label="Finnish protected stations")
    # shade bins where BOTH are present = overlap zones
    for i in range(len(centers)):
        if sat_cov[i] > 0 and fin_cnt[i] > 0:
            ax.axvspan(edges[i], edges[i+1], color="#e53e3e", alpha=0.12, zorder=0)
    ax.axhline(0, color="k", lw=0.8)
    ax.set_xscale("log")
    ax.set_xlabel("frequency (MHz, log)")
    ax.set_ylabel("<- FIN stations    |    sat notices ->")
    ax.set_title("Spectrum overlap: IFIC 3074 satellite downlinks vs Finnish "
                 "protected stations\n(red = bands where they coincide = "
                 "frequency-overlap candidates)")
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(PLOTS / "spectrum_overlap.png", dpi=130)
    plt.close(fig)

    # ---- who threatens Finnish bands: notices by administration ----
    by_adm = (ov.groupby("adm")["sat_ntc_id"].nunique()
                .sort_values(ascending=False).head(15))
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.barh(range(len(by_adm)), by_adm.values, color="#6b46c1")
    ax.set_yticks(range(len(by_adm))); ax.set_yticklabels(by_adm.index)
    ax.invert_yaxis()
    ax.set_xlabel("# satellite notices overlapping Finnish protected bands")
    ax.set_title("Frequency-overlap candidates by filing administration (3074)")
    fig.tight_layout()
    fig.savefig(PLOTS / "overlap_by_admin.png", dpi=130)
    plt.close(fig)
    print(f"\nPlots -> {PLOTS}/spectrum_overlap.png, overlap_by_admin.png")


if __name__ == "__main__":
    p, s = load_bands()
    print(f"Finnish protected bands: {len(p)}   satellite E-bands: {len(s)}")
    ov = compute_overlap(p, s)
    save_and_report(ov)
    make_overlap_plots(p, s, ov)
