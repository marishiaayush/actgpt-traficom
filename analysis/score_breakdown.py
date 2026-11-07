"""
Audit trace: show EVERY number behind a flagged score, step by step, and verify
it reproduces the stored margin. "Show your work" for the triage.

For each top screening alert it prints a card:
  1. OVERLAP   - satellite emission band vs the victim's RX channel (co/adjacent)
  2. GEOMETRY  - elevation + slant range (SGP4 max elev for non-GSO)
  3. POWER     - EIRP = pwr_max + gain -> spectral density in the ref bandwidth
  4. PFD       - EIRP_eff - 20log10(d) - 10.99 - FDR
  5. LIMIT     - Article 21 Table 21-4 at that band + elevation
  6. MARGIN    - PFD - limit  (and a check vs the value stored in fin_pfd_score)

Run:  uv run python analysis/score_breakdown.py [N]      (default N=4)
"""

import math
import sqlite3
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pfd import slant_range_km, SPREAD_CONST_DB, GSO_ALT_KM
import article21

SRS = Path(__file__).resolve().parent.parent / "analysis" / "srs3074.db"


def eirp_breakdown(con, ntc_id, freq_mhz, ref_bw_hz):
    """Reconstruct the worst-case EIRP exactly as pfd_score does, but keep the
    components of the chosen beam."""
    rows = pd.read_sql("""
        SELECT g.freq_min, g.freq_max, g.pwr_max, b.gain, g.bdwdth, g.beam_name
        FROM grp g JOIN s_beam b ON b.ntc_id=g.ntc_id AND b.beam_name=g.beam_name
        WHERE g.emi_rcp='E' AND g.ntc_id=? AND g.pwr_max IS NOT NULL
          AND b.gain IS NOT NULL""", con, params=[ntc_id])
    best = None
    for r in rows.itertuples():
        if r.freq_min <= freq_mhz <= r.freq_max:
            b_hz = r.bdwdth * 1000.0 if pd.notna(r.bdwdth) and r.bdwdth > 0 else ref_bw_hz
            bw_norm = 10 * math.log10(max(b_hz / ref_bw_hz, 1.0))
            eff = (r.pwr_max + r.gain) - bw_norm
            if best is None or eff > best["eff"]:
                best = dict(pwr=r.pwr_max, gain=r.gain, b_hz=b_hz, beam=r.beam_name,
                            bw_norm=bw_norm, eff=eff)
    return best


def card(con, row):
    ntc, stn = int(row.sat_ntc_id), int(row.station_no)
    freq = row.overlap_freq_mhz
    print("=" * 72)
    print(f"ALERT  notice {ntc} ({row.adm})  ->  Finnish station {stn}   "
          f"margin = {row.margin:+.1f} dB")
    print("=" * 72)

    # 1. overlap
    ov = pd.read_sql("""SELECT sat_lo_mhz, sat_hi_mhz, victim_freq_mhz, station_role
                        FROM fin_freq_overlap WHERE sat_ntc_id=? AND station_no=?
                        AND proximity=? LIMIT 1""", con,
                     params=[ntc, stn, row.proximity]).iloc[0]
    print(f"\n1. OVERLAP ({row.proximity})")
    print(f"   satellite emission band : {ov.sat_lo_mhz:.2f} - {ov.sat_hi_mhz:.2f} MHz")
    print(f"   victim RX channel       : {ov.victim_freq_mhz:.2f} MHz  (role={ov.station_role})")
    print(f"   interference frequency  : {freq:.2f} MHz")
    if row.proximity == "adjacent":
        print(f"   frequency offset        : {row.offset_mhz:.1f} MHz  -> FDR {row.fdr_db:.1f} dB")

    # 2. geometry
    print(f"\n2. GEOMETRY ({'GSO' if row.is_gso else 'non-GSO'})")
    if row.is_gso:
        print(f"   GSO slot -> elevation from station : {row.elev:.1f} deg")
        print(f"   altitude {GSO_ALT_KM:.0f} km")
    else:
        sg = pd.read_sql("SELECT max_elev_deg FROM fin_geom_sgp4 WHERE sat_ntc_id=?",
                         con, params=[ntc])
        mx = sg.iloc[0, 0] if len(sg) else float("nan")
        print(f"   SGP4 max elevation over Finland    : {mx:.1f} deg  (visible)")
        print(f"   worst-margin elevation used        : {row.elev:.1f} deg,  alt {row.alt_km:.0f} km")
    d_km = slant_range_km(row.elev, row.alt_km if pd.notna(row.alt_km) else GSO_ALT_KM)
    print(f"   slant range d = sqrt((R sin e)^2 + h(2R+h)) - R sin e = {d_km:,.0f} km")

    # 3. power
    _, ref_bw = article21.limit(freq, row.elev)
    eb = eirp_breakdown(con, ntc, freq, ref_bw)
    print("\n3. POWER (worst-case: main beam on station)")
    if eb:
        print(f"   beam {eb['beam']}:  pwr_max {eb['pwr']:.1f} dBW  +  gain {eb['gain']:.1f} dBi"
              f"  =  EIRP {eb['pwr']+eb['gain']:.1f} dBW")
        print(f"   emission bw {eb['b_hz']/1e6:.3f} MHz -> scale to {ref_bw/1e3:.0f} kHz ref"
              f"  (-{eb['bw_norm']:.1f} dB)")
        print(f"   EIRP_eff = {eb['eff']:.1f} dBW in {ref_bw/1e3:.0f} kHz")

    # 4. PFD
    if eb:
        pfd = eb["eff"] - 20*math.log10(d_km*1000) - SPREAD_CONST_DB - row.fdr_db
        print("\n4. PFD  = EIRP_eff - 20log10(d_m) - 10.99" +
              (" - FDR" if row.fdr_db else ""))
        print(f"        = {eb['eff']:.1f} - {20*math.log10(d_km*1000):.1f} - 10.99"
              + (f" - {row.fdr_db:.1f}" if row.fdr_db else "")
              + f"  =  {pfd:.1f} dBW/m2/{ref_bw/1e3:.0f}kHz")

    # 5. limit
    lim, _ = article21.limit(freq, row.elev)
    print(f"\n5. ARTICLE-21 LIMIT  (band containing {freq:.0f} MHz, elevation {row.elev:.1f} deg)")
    print(f"   limit = {lim:.1f} dBW/m2/{ref_bw/1e3:.0f}kHz   [strictest at low elevation]")

    # 6. margin + check
    print(f"\n6. MARGIN = PFD - limit = {row.pfd:.1f} - ({lim:.1f}) = {row.margin:+.1f} dB"
          f"   ({'FLAG' if row.margin > 0 else 'ok'})")
    chk = abs((row.pfd - lim) - row.margin)
    print(f"   [check vs stored margin: {'OK' if chk < 0.5 else 'MISMATCH %.2f' % chk}]\n")


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    con = sqlite3.connect(SRS)
    top = pd.read_sql(f"""SELECT * FROM fin_pfd_score
        WHERE status='scored' AND margin>0
        ORDER BY margin DESC LIMIT {n*3}""", con)
    top = top.drop_duplicates("sat_ntc_id").head(n)   # distinct notices
    for r in top.itertuples():
        card(con, r)
    con.close()


if __name__ == "__main__":
    main()
