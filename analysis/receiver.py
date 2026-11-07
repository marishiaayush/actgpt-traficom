"""
Score interference for a USER-SUPPLIED receiver (any lat/lon, incl. offshore)
against a processed IFIC's satellite emissions -- the "bring your own receiver"
path (one or many, land or maritime). Reuses the same physics as the pipeline.

    score_receiver(ific, lat, lon, freq_mhz, bw_mhz) -> ranked DataFrame of
    threatening satellites (worst-case PFD margin, screening estimate).
"""

import math
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

import article21
from pfd import (slant_range_km, elevation_from_central_angle,
                 central_angle_deg, GSO_ALT_KM, pfd_dbw_m2)

A = Path(__file__).resolve().parent
ELEV = np.arange(5, 91, 5)


def score_receiver(ific, lat, lon, freq_mhz, bw_mhz):
    srs = sqlite3.connect(A / f"srs{int(ific)}.db")
    lo, hi = freq_mhz - bw_mhz / 2, freq_mhz + bw_mhz / 2
    em = pd.read_sql("""
        SELECT g.ntc_id, n.adm, g.freq_min, g.freq_max, g.pwr_max, g.bdwdth, b.gain
        FROM grp g JOIN notice n ON n.ntc_id=g.ntc_id
        JOIN s_beam b ON b.ntc_id=g.ntc_id AND b.beam_name=g.beam_name
        WHERE g.emi_rcp='E' AND g.pwr_max IS NOT NULL AND b.gain IS NOT NULL
          AND g.freq_min<=? AND g.freq_max>=?""", srs, params=(hi, lo))
    _, ref_bw = article21.limit(freq_mhz, 10.0)
    if em.empty or ref_bw is None:
        srs.close()
        return pd.DataFrame()
    geo = pd.read_sql("SELECT ntc_id, MIN(long_nom) slot FROM geo GROUP BY ntc_id", srs)
    gso = {r.ntc_id: r.slot for r in geo.itertuples() if pd.notna(r.slot)}
    orb = pd.read_sql("SELECT ntc_id, MIN(op_ht_km) alt, MAX(inclin_ang) incl FROM orbit GROUP BY ntc_id", srs)
    orbm = {r.ntc_id: (r.alt, r.incl) for r in orb.itertuples()}
    nm = pd.read_sql("SELECT ntc_id, sat_name FROM non_geo UNION SELECT ntc_id, sat_name FROM geo", srs)
    names = dict(zip(nm.ntc_id, nm.sat_name))
    srs.close()

    recs = []
    for ntc, grp in em.groupby("ntc_id"):
        eff = None
        for r in grp.itertuples():
            if r.freq_min <= freq_mhz <= r.freq_max:
                bhz = r.bdwdth * 1000 if pd.notna(r.bdwdth) and r.bdwdth > 0 else ref_bw
                e = (r.pwr_max + r.gain) - 10 * math.log10(max(bhz / ref_bw, 1))
                eff = e if eff is None else max(eff, e)
        if eff is None:
            continue
        is_gso = ntc in gso
        if is_gso:
            el = elevation_from_central_angle(
                central_angle_deg(lat, lon, 0.0, gso[ntc]), GSO_ALT_KM)
            elevs, alt = ([el] if el > 0 else []), GSO_ALT_KM
        else:
            if ntc not in orbm or pd.isna(orbm[ntc][0]):
                continue
            alt, incl = orbm[ntc]
            mtl = incl if incl <= 90 else 180 - incl
            if abs(lat) <= mtl:
                elevs = ELEV
            else:
                emax = elevation_from_central_angle(abs(lat) - mtl, alt)
                if emax <= 5:            # never rises above the horizon -> skip
                    continue
                elevs = ELEV[ELEV <= emax]
        best = None
        for e in elevs:
            d = slant_range_km(e, alt)
            pfd = pfd_dbw_m2(eff, d)
            lim, _ = article21.limit(freq_mhz, e)
            if best is None or pfd - lim > best[3]:
                best = (e, d, pfd, pfd - lim)
        if best:
            recs.append(dict(ntc_id=int(ntc), name=names.get(ntc, "?"),
                             adm=grp.adm.iloc[0], is_gso=is_gso,
                             elev=round(best[0], 1), pfd=round(best[2], 1),
                             margin=round(best[3], 1)))
    df = pd.DataFrame(recs)
    return df.sort_values("margin", ascending=False) if len(df) else df
