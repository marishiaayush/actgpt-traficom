"""
STEPS 2-3 across every frequency-overlap pair: geometry + PFD margin -> a
ranked triage table (the dashboard's core output).

For each (satellite notice, Finnish station) pair from fin_freq_overlap we:
  STEP 2 geometry  : worst-case elevation the satellite can reach at that
                     station's location, and the slant range there.
                       - non-GSO: overhead (90 deg) if station |lat| <= orbit
                         inclination, else the best elevation at its peak
                         latitude. Swept over achievable elevations.
                       - GSO: fixed elevation from station lat/lon vs the slot
                         longitude (geo.long_nom). Below horizon -> not visible.
  STEP 3 power/PFD : PFD vs the Article-21 limit, worst margin over the swept
                     elevations.

POWER SOURCE -- why only declared PFD:
We tested recomputing PFD from EIRP (pwr_max + beam gain, or s_beam.pwr_max_1m).
In IFIC 3074 those fields are sparse and, aggregated per notice, produce
unphysical EIRP (>100 dBW/MHz) and absurd margins (+90 dB). So we DO NOT
fabricate PFD from them. The only trustworthy power figure the filing provides
is the administration's own DECLARED PFD (table c_pfd, ~38 notices) -- which is
exactly the Article-21 regulatory quantity. Pairs are therefore split into:
   scored_declared : real PFD margin vs limit (defensible flags)
   geometry_only   : satellite reaches the station but the IFIC carries no
                     usable power -> ranked by a transparent geometry proxy
                     (closest slant range), labelled "power unknown"
   not_visible_gso : GSO slot below the station's horizon
This split is itself a finding: IFIC power completeness is partial, and the
geometry_only queue is the "needs more data / manual power" bucket.

Run:  uv run python analysis/pfd_score.py
"""

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pfd import (slant_range_km, pfd_dbw_m2, elevation_from_central_angle,
                 central_angle_deg, GSO_ALT_KM)
import article21
import adjacent

ROOT = Path(__file__).resolve().parent.parent
SRS = ROOT / "analysis" / "srs3074.db"
FIN = ROOT / "analysis" / "frequencies.db"
PLOTS = ROOT / "analysis" / "plots"
ELEV_SWEEP = np.arange(5, 91, 5)   # achievable elevations to test


def load_inputs():
    srs = sqlite3.connect(SRS)
    ov = pd.read_sql("""SELECT sat_ntc_id, adm, station_no, interf_freq_mhz,
                               proximity, offset_mhz, sat_lo_mhz, sat_hi_mhz,
                               licence_class, band
                        FROM fin_freq_overlap""", srs)

    # per-notice orbit classification
    geo = pd.read_sql("SELECT ntc_id, MIN(long_nom) long_nom FROM geo "
                      "WHERE long_nom IS NOT NULL GROUP BY ntc_id", srs)
    orb = pd.read_sql("""SELECT ntc_id, MIN(op_ht_km) alt_km,
                                MAX(inclin_ang) incl FROM orbit GROUP BY ntc_id""", srs)
    # declared PFD rows kept PER BAND (freq_min..freq_max), to be matched to the
    # actual overlap frequency -- NOT aggregated per notice (that cross-band
    # contaminated: a 43 GHz declared PFD was wrongly applied to a 2 GHz overlap)
    cpfd = pd.read_sql("""SELECT ntc_id, freq_min, freq_max, pfd, bdwdth
                          FROM c_pfd WHERE pfd IS NOT NULL""", srs)
    for c in ["freq_min", "freq_max", "pfd", "bdwdth"]:
        cpfd[c] = pd.to_numeric(cpfd[c], errors="coerce")
    cpfd_by_ntc = {k: v[["freq_min", "freq_max", "pfd", "bdwdth"]].values
                   for k, v in cpfd.groupby("ntc_id")}

    # emission beams for COMPUTED PFD: per E-group, its band + total power
    # (pwr_max, dBW) + matched-beam PEAK gain (dBi) + bandwidth (kHz).
    # Peak gain => worst case (main beam pointed at the station): the SRS has no
    # beam boresight lat/lon here (bore_lat/long are null), so we cannot reduce
    # for off-axis pointing -> this is a conservative upper-bound screen.
    emis = pd.read_sql("""
        SELECT g.ntc_id, g.freq_min, g.freq_max, g.pwr_max, b.gain, g.bdwdth
        FROM grp g JOIN s_beam b
          ON b.ntc_id=g.ntc_id AND b.beam_name=g.beam_name
        WHERE g.emi_rcp='E' AND g.pwr_max IS NOT NULL AND b.gain IS NOT NULL""", srs)
    for c in ["freq_min", "freq_max", "pwr_max", "gain", "bdwdth"]:
        emis[c] = pd.to_numeric(emis[c], errors="coerce")
    emis = emis.dropna(subset=["freq_min", "freq_max", "pwr_max", "gain"])
    emis_by_ntc = {k: v[["freq_min","freq_max","pwr_max","gain","bdwdth"]].values
                   for k, v in emis.groupby("ntc_id")}
    srs.close()

    fin = sqlite3.connect(FIN)
    st = pd.read_sql("SELECT station_no, lat, lon FROM v_clean", fin)
    st = st.drop_duplicates("station_no")      # some station_no repeat in v_clean
    fin.close()

    cand = pd.DataFrame({"ntc_id": ov["sat_ntc_id"].unique()})
    notice = (cand.merge(geo, on="ntc_id", how="left")
                  .merge(orb, on="ntc_id", how="left"))
    for c in ["long_nom", "alt_km", "incl"]:
        notice[c] = pd.to_numeric(notice[c], errors="coerce")
    notice["is_gso"] = notice["long_nom"].notna()
    return (ov, notice.set_index("ntc_id"), st.set_index("station_no"),
            cpfd_by_ntc, emis_by_ntc)


def matched_declared_pfd(cpfd_rows, freq_mhz, ref_bw_hz):
    """From a notice's c_pfd rows, pick the one whose band covers freq_mhz and
    gives the worst (highest) PFD normalized to ref_bw_hz. Returns value or None."""
    if cpfd_rows is None:
        return None
    best = None
    for f_lo, f_hi, pfd, bw in cpfd_rows:
        if pd.notna(f_lo) and pd.notna(f_hi) and f_lo <= freq_mhz <= f_hi:
            norm = article21.normalize_pfd_to_ref(pfd, bw, ref_bw_hz)
            if best is None or norm > best:
                best = norm
    return best


def matched_eirp_eff(emis_rows, freq_mhz, ref_bw_hz):
    """Worst-case effective EIRP (dBW IN ref_bw_hz) of the emission beams
    covering freq_mhz. 'Effective' folds the bandwidth scaling in, so PFD is
    just eirp_eff - 20log10(d_m) - 10.99.
        EIRP_total = pwr_max + gain            (peak gain = main beam on station)
        eirp_eff   = EIRP_total - 10log10(max(B/ref, 1))

    ASSUMPTION TO CONFIRM (expert flag): this treats grp.pwr_max as TRANSMITTER
    power (dBW) in the emission bandwidth, so adding s_beam.gain yields EIRP. If
    pwr_max were already an EIRP or a power DENSITY, this double-counts gain or
    mis-scales bandwidth. Data leans toward "power" (median pwr_max 20.5 dBW +
    gain 30 dBi -> ~50 dBW EIRP, plausible; a separate pwr_max_1m density field
    exists), but verify against the SRS Preface / GIBC. Also: the Article-21
    Table 21-4 limit is NOT universal -- its applicability depends on the
    service and provision of each notice, which we do not yet check.
    """
    if emis_rows is None:
        return None
    import math
    best = None
    for f_lo, f_hi, pwr, gain, bw_khz in emis_rows:
        if f_lo <= freq_mhz <= f_hi:
            b_hz = (bw_khz * 1000.0) if pd.notna(bw_khz) and bw_khz > 0 else ref_bw_hz
            eff = (pwr + gain) - 10.0 * math.log10(max(b_hz / ref_bw_hz, 1.0))
            if best is None or eff > best:
                best = eff
    return best


def score_pair(nrow, srow, freq_mhz, cpfd_rows, emis_rows, fdr=0.0):
    """Return dict with geometry + PFD margin for one (notice, station) pair.
    `fdr` (dB) is the adjacent-band frequency-dependent rejection subtracted from
    the interfering PFD (0 for co-channel)."""
    lat, lon = srow["lat"], srow["lon"]
    # ---- step 2: achievable elevations ----
    if nrow["is_gso"]:
        gamma = central_angle_deg(lat, lon, 0.0, nrow["long_nom"])
        el = elevation_from_central_angle(gamma, GSO_ALT_KM)
        if el <= 0:
            return {"status": "not_visible_gso", "elev": el, "slant_km": np.nan,
                    "pfd": np.nan, "limit": np.nan, "margin": np.nan,
                    "pfd_source": None, "alt_km": GSO_ALT_KM}
        elevs, alt = np.array([el]), GSO_ALT_KM
    else:
        alt = nrow["alt_km"]
        if pd.isna(alt):
            return {"status": "no_orbit_data", "elev": np.nan, "slant_km": np.nan,
                    "pfd": np.nan, "limit": np.nan, "margin": np.nan,
                    "pfd_source": None, "alt_km": np.nan}
        incl = nrow["incl"] if pd.notna(nrow["incl"]) else 90.0
        # max ground-track latitude = inclination (prograde) or 180-incl
        # (retrograde, e.g. sun-synchronous ~98deg reaches ~82N). This is
        # POTENTIAL visibility only -- not proof the beam illuminates the
        # station, nor for how long. A screening approximation.
        max_track_lat = incl if incl <= 90 else 180 - incl
        if abs(lat) <= max_track_lat:
            elevs = ELEV_SWEEP                      # sub-track can pass overhead
        else:
            el_max = elevation_from_central_angle(abs(lat) - max_track_lat, alt)
            elevs = ELEV_SWEEP[ELEV_SWEEP <= max(el_max, 5)]
            if len(elevs) == 0:
                elevs = np.array([max(el_max, 1.0)])

    # closest approach over achievable elevations (geometry proxy for all rows)
    slants = np.array([slant_range_km(e, alt) for e in elevs])
    min_slant = float(slants.min())          # closest the sat ever gets
    best_e = float(elevs[np.argmin(slants)])
    geom = {"status": "geometry_only", "elev": best_e, "slant_km": min_slant,
            "min_slant_km": min_slant, "pfd": np.nan, "limit": np.nan,
            "margin": np.nan, "pfd_source": None, "alt_km": alt}

    # ---- step 3: PFD margin needs a Table-21-4 band + a power source ----
    _, ref_bw = article21.limit(freq_mhz, 10)     # ref bw is elevation-independent
    if ref_bw is None:
        geom["reason"] = "no_art21_band"
        return geom
    # power source: declared PFD (trustworthy) preferred; else computed
    # worst-case EIRP (conservative, main-beam-on-station)
    declared = matched_declared_pfd(cpfd_rows, freq_mhz, ref_bw)
    eirp_eff = matched_eirp_eff(emis_rows, freq_mhz, ref_bw) if declared is None else None
    if declared is None and eirp_eff is None:
        geom["reason"] = "no_power_data"
        return geom
    src = "declared" if declared is not None else "computed"

    best = None
    for e, d in zip(elevs, slants):
        lim, _ = article21.limit(freq_mhz, e)
        pfd = declared if src == "declared" else pfd_dbw_m2(eirp_eff, d)
        pfd -= fdr                              # adjacent-band rejection
        margin = pfd - lim
        rec = {"elev": float(e), "slant_km": float(d), "pfd": pfd,
               "limit": lim, "margin": margin}
        if best is None or margin > best["margin"]:
            best = rec
    best.update({"status": "scored", "pfd_source": src,
                 "alt_km": alt, "min_slant_km": min_slant, "ref_bw_hz": ref_bw})
    return best


def main():
    ov, notice, st, cpfd_by_ntc, emis_by_ntc = load_inputs()
    print(f"scoring {len(ov)} overlap pairs...")
    out = []
    for r in ov.itertuples():
        if r.sat_ntc_id not in notice.index or r.station_no not in st.index:
            continue
        freq_mhz = r.interf_freq_mhz
        sat_bw = r.sat_hi_mhz - r.sat_lo_mhz
        fdr = adjacent.fdr_db(r.offset_mhz, sat_bw) if r.proximity == "adjacent" else 0.0
        res = score_pair(notice.loc[r.sat_ntc_id], st.loc[r.station_no],
                         freq_mhz, cpfd_by_ntc.get(r.sat_ntc_id),
                         emis_by_ntc.get(r.sat_ntc_id), fdr)
        res.update({"sat_ntc_id": r.sat_ntc_id, "adm": r.adm,
                    "station_no": r.station_no, "band": r.band,
                    "overlap_freq_mhz": round(freq_mhz, 3),
                    "proximity": r.proximity, "offset_mhz": round(r.offset_mhz, 2),
                    "fdr_db": round(fdr, 1),
                    "is_gso": bool(notice.loc[r.sat_ntc_id, "is_gso"])})
        out.append(res)
    df = pd.DataFrame(out).sort_values("margin", ascending=False,
                                       na_position="last").reset_index(drop=True)

    con = sqlite3.connect(SRS)
    df.to_sql("fin_pfd_score", con, if_exists="replace", index=False)
    con.close()

    # ---------- report ----------
    print(f"\n{'='*62}\nSTEP 2-3 RESULTS: ranked triage ({len(df)} pairs)\n{'='*62}")
    print("status breakdown:")
    print(df["status"].value_counts().to_string())

    sc = df[df.status == "scored"]
    print(f"\n-- PFD-ASSESSED --  {len(sc)} pairs   "
          f"(source: {sc['pfd_source'].value_counts().to_dict()})")
    print(f"   proximity: {sc['proximity'].value_counts().to_dict()}")
    exceed = sc[sc.margin > 0]
    print(f"   SCREENING ALERTS (margin>0 under stated assumptions): {len(exceed)} "
          f"pairs, {exceed.sat_ntc_id.nunique()} notices, {exceed.station_no.nunique()} stations")
    print(f"     co-channel: {(exceed.proximity=='co').sum()}, "
          f"adjacent-band (exploratory): {(exceed.proximity=='adjacent').sum()}")
    print("   NOTE: alerts are NOT confirmed interference. 'computed' assumes main-beam-")
    print("   on-station with an UNCONFIRMED Art-21 applicability + pwr_max definition;")
    print("   margin<0 = below the screening threshold under these assumptions, not proven safe.")
    print("\nTOP 10 SCREENING ALERTS (worst margin):")
    cols = ["sat_ntc_id","adm","station_no","overlap_freq_mhz","proximity",
            "offset_mhz","fdr_db","is_gso","margin","pfd_source"]
    show = sc[cols].head(10).copy()
    for c in ["offset_mhz", "fdr_db", "margin"]:
        show[c] = show[c].round(1)
    print(show.to_string(index=False))

    go = df[df.status == "geometry_only"]
    print(f"\n-- GEOMETRY-ONLY (power unknown) --  {len(go)} pairs, "
          f"{go.sat_ntc_id.nunique()} notices")
    if "reason" in go.columns:
        print("   reasons:", go["reason"].value_counts().to_dict())
    print("   top 5 by closest approach (worst geometry):")
    gos = go.sort_values("min_slant_km").head(5)
    print(gos[["sat_ntc_id","adm","station_no","alt_km","min_slant_km"]]
          .round(0).to_string(index=False))

    make_plots(df)


def make_plots(df):
    PLOTS.mkdir(exist_ok=True)
    sc = df[df.status == "scored"].copy()
    fig, ax = plt.subplots(1, 2, figsize=(14, 5.5))

    # (a) worst-case PFD margin distribution, co-channel vs adjacent-band
    for prox, color in [("co","#2b6cb0"), ("adjacent","#d69e2e")]:
        d = sc[sc.proximity == prox]["margin"].dropna()
        if len(d):
            ax[0].hist(d, bins=45, alpha=0.6, color=color, label=f"{prox} ({len(d)})")
    ax[0].axvline(0, color="k", ls="--", lw=1)
    ax[0].set_title("Worst-case PFD margin (margin>0 = screening alert, not confirmed)\n"
                    "co-channel vs adjacent-band (after FDR)")
    ax[0].set_xlabel("margin (dB)  [PFD - limit]"); ax[0].set_ylabel("pairs")
    ax[0].legend()

    # (b) worst margin per notice (top 20) -- the triage ranking
    worst = (sc.groupby(["sat_ntc_id","adm","is_gso"])["margin"].max()
               .reset_index().sort_values("margin", ascending=False).head(20))
    colors = ["#2b6cb0" if g else "#e53e3e" for g in worst.is_gso]
    ax[1].barh(range(len(worst)), worst.margin, color=colors)
    ax[1].set_yticks(range(len(worst)))
    ax[1].set_yticklabels([f"{int(n)} ({a})" for n, a in
                           zip(worst.sat_ntc_id, worst.adm)], fontsize=7)
    ax[1].invert_yaxis(); ax[1].axvline(0, color="k", ls="--", lw=1)
    ax[1].set_title("Worst-case PFD screening margin per notice, top 20\nblue=GSO, red=non-GSO")
    ax[1].set_xlabel("margin (dB)")
    fig.tight_layout(); fig.savefig(PLOTS / "pfd_triage_v2.png", dpi=130)
    plt.close(fig)
    print(f"\nPlot -> {PLOTS}/pfd_triage_v2.png")
    print(f"Table -> srs3074.db :: fin_pfd_score (ranked)")


if __name__ == "__main__":
    main()
