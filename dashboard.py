"""
ACT-GPT Traficom — interference triage dashboard (Phase 1).

Two-panel Streamlit app reading the consolidated app.db:
  LEFT  (visual) : map of affected Finnish stations + the satellite's orbit/footprint
  RIGHT (text)   : ranked shortlist, affected bands, and the transparent PFD math

Run:  uv run streamlit run dashboard.py
"""

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "analysis"))
APP_DB = ROOT / "analysis" / "app.db"

st.set_page_config(page_title="ACT-GPT · Traficom interference triage",
                   page_icon="🛰️", layout="wide")

STATUS_COLOR = {"ALERT": "#e53e3e", "visible": "#d69e2e",
                "not_visible": "#718096", "needs_data": "#a0aec0"}


# --------------------------------------------------------------------------
# data access (cached)
# --------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def q(sql, params=()):
    con = sqlite3.connect(APP_DB)
    try:
        return pd.read_sql(sql, con, params=params)
    finally:
        con.close()


def publications():
    return q("SELECT * FROM publications ORDER BY ific_no DESC")


def shortlist(ific):
    return q("SELECT * FROM shortlist WHERE ific_no=? ", (ific,))


def affected_stations(ific, ntc):
    return q("""SELECT DISTINCT p.station_no, s.licence_class AS role,
                       s.lat, s.lon, p.margin, p.overlap_freq_mhz, p.elev
                FROM fin_pfd_score p
                JOIN protected_stations s ON s.station_no=p.station_no
                WHERE p.ific_no=? AND p.sat_ntc_id=? AND p.status='scored'
                  AND p.margin>0 ORDER BY p.margin DESC""", (ific, ntc))


def affected_bands(ific, ntc):
    ov = q("""SELECT DISTINCT ROUND(sat_lo_mhz,3) lo, ROUND(sat_hi_mhz,3) hi,
                     ROUND(interf_freq_mhz,3) f, proximity
              FROM fin_freq_overlap WHERE ific_no=? AND sat_ntc_id=?
              ORDER BY f LIMIT 200""", (ific, ntc))
    m4 = q("SELECT Services_in_Finland svc, sub_lo_mhz lo, sub_hi_mhz hi FROM m4_allocations")
    def svc(f):
        hit = m4[(m4.lo <= f) & (f <= m4.hi)]
        return hit.svc.iloc[0] if len(hit) else "(no M4 match)"
    ov["Finnish use (M4)"] = ov["f"].map(svc)
    return ov


def worst_pair(ific, ntc):
    d = q("""SELECT * FROM fin_pfd_score WHERE ific_no=? AND sat_ntc_id=?
             AND status='scored' ORDER BY margin DESC LIMIT 1""", (ific, ntc))
    return d.iloc[0] if len(d) else None


@st.cache_data(show_spinner=False)
def orbit_track(ific, ntc, is_gso):
    """Representative SGP4 ground track (non-GSO) or GSO slot point."""
    con = sqlite3.connect(ROOT / "analysis" / f"srs{ific}.db")
    try:
        if is_gso:
            g = pd.read_sql("SELECT MIN(long_nom) lon FROM geo WHERE ntc_id=?",
                            con, params=(ntc,))
            return ("gso", float(g.lon.iloc[0]) if pd.notna(g.lon.iloc[0]) else None)
        pl = pd.read_sql("""SELECT inclin_ang, op_ht_km, long_asc FROM orbit
                            WHERE ntc_id=? AND op_ht_km IS NOT NULL LIMIT 1""",
                         con, params=(ntc,))
    finally:
        con.close()
    if pl.empty:
        return ("none", None)
    from geometry_sgp4 import make_sat, TS
    from skyfield.api import wgs84
    r = pl.iloc[0]
    sat = make_sat(r.inclin_ang, r.op_ht_km, r.long_asc if pd.notna(r.long_asc) else 0.0, 0.0, 1)
    t = TS.utc(2026, 11, 7, 0, range(0, 200, 1))
    sp = wgs84.subpoint(sat.at(t))
    return ("track", (sp.longitude.degrees, sp.latitude.degrees))


# --------------------------------------------------------------------------
# visual panel
# --------------------------------------------------------------------------
def map_panel(ific, ntc, is_gso, dark):
    tmpl = "plotly_dark" if dark else "plotly_white"
    allst = q("SELECT station_no, lat, lon FROM protected_stations "
              "WHERE lat IS NOT NULL")
    aff = affected_stations(ific, ntc) if ntc else pd.DataFrame()
    fig = go.Figure()
    fig.add_trace(go.Scattergeo(lon=allst.lon, lat=allst.lat, mode="markers",
                  marker=dict(size=3, color="#9aa5b1"), name="protected stations",
                  hoverinfo="skip"))
    if len(aff):
        fig.add_trace(go.Scattergeo(lon=aff.lon, lat=aff.lat, mode="markers",
                      marker=dict(size=8, color="#e53e3e"),
                      name=f"affected ({len(aff)})",
                      text=[f"stn {int(s)}  margin {m:+.1f} dB" for s, m
                            in zip(aff.station_no, aff.margin)], hoverinfo="text"))
    # orbit context
    if ntc:
        kind, data = orbit_track(ific, ntc, is_gso)
        if kind == "track" and data is not None:
            fig.add_trace(go.Scattergeo(lon=data[0], lat=data[1], mode="lines",
                          line=dict(width=1.2, color="#2b6cb0"),
                          name="orbit ground track"))
        elif kind == "gso" and data is not None:
            fig.add_trace(go.Scattergeo(lon=[data], lat=[0], mode="markers",
                          marker=dict(size=11, symbol="star", color="#d69e2e"),
                          name=f"GSO slot {data:.1f}E"))
    fig.update_geos(scope="europe", lataxis_range=[55, 72], lonaxis_range=[15, 35],
                    showcountries=True, resolution=50,
                    landcolor="#1a202c" if dark else "#eef3ee",
                    oceancolor="#2d3748" if dark else "#dce9f5", showocean=True)
    fig.update_layout(template=tmpl, height=560, margin=dict(l=0, r=0, t=10, b=0),
                      legend=dict(orientation="h", y=-0.02),
                      paper_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, width='stretch')


# --------------------------------------------------------------------------
# app
# --------------------------------------------------------------------------
def main():
    pubs = publications()
    with st.sidebar:
        st.title("🛰️ ACT-GPT")
        st.caption("ITU IFIC → Finnish interference triage")
        dark = st.toggle("🌙 Dark charts", value=False)
        st.divider()
        if pubs.empty:
            st.warning("No processed publications. Run the pipeline first.")
            st.stop()
        ific = st.selectbox("Publication (IFIC)", pubs.ific_no,
                            format_func=lambda x: f"IFIC {x} (space)")
        row = pubs[pubs.ific_no == ific].iloc[0]
        st.metric("Notices", int(row.n_notices))
        st.metric("Shortlisted", int(row.n_shortlist))
        st.metric("ALERTs", int(row.n_alerts))
        st.caption(f"last processed: {row.processed_at}")
        st.link_button("📄 Fetch ITU report", row.pdf_url or "https://www.itu.int")
        st.divider()
        with st.expander("Process another IFIC"):
            new = st.number_input("IFIC number", value=int(ific), step=1)
            if st.button("Run pipeline", width='stretch'):
                with st.spinner(f"Processing IFIC {new} ..."):
                    from pipeline import run_ific
                    try:
                        run_ific(int(new)); q.clear()
                        st.success("Done — reselect it above."); st.rerun()
                    except SystemExit as e:
                        st.error(str(e))

    sl = shortlist(ific).sort_values(
        ["review_status", "worst_margin_db"], ascending=[True, False])
    st.subheader(f"IFIC {ific} — {int(row.n_alerts)} satellites flagged for review")

    left, right = st.columns([1.1, 1], gap="large")
    with right:
        f = st.radio("filter", ["ALERT", "all"], horizontal=True, label_visibility="collapsed")
        view = sl if f == "all" else sl[sl.review_status == "ALERT"]
        label = (view.sat_name.fillna("?") + "  ·  " + view.adm.fillna("?")
                 + view.worst_margin_db.map(lambda m: f"  ({m:+.1f} dB)" if pd.notna(m) else ""))
        pick = st.selectbox(f"shortlist ({len(view)})", view.sat_ntc_id,
                            format_func=lambda n: label[view.sat_ntc_id == n].iloc[0])
        srow = view[view.sat_ntc_id == pick].iloc[0]

    with left:
        map_panel(ific, int(pick), bool(srow.is_gso), dark)

    with right:
        c = STATUS_COLOR.get(srow.review_status, "#718096")
        st.markdown(f"### {srow.sat_name or '?'} "
                    f"<span style='color:{c}'>({srow.review_status})</span>",
                    unsafe_allow_html=True)
        m1, m2, m3 = st.columns(3)
        m1.metric("Admin", srow.adm or "?")
        m2.metric("Type", "GSO" if srow.is_gso else "non-GSO")
        m3.metric("Worst margin",
                  f"{srow.worst_margin_db:+.1f} dB" if pd.notna(srow.worst_margin_db) else "—")

        wp = worst_pair(ific, int(pick))
        if wp is not None and wp.status == "scored":
            st.markdown("**Transparent PFD math (worst pair)** — *screening estimate*")
            chain = pd.DataFrame({
                "step": ["interference freq", "elevation", "slant range",
                         "PFD (computed)", "Article-21 limit", "margin"],
                "value": [f"{wp.overlap_freq_mhz:.2f} MHz",
                          f"{wp.elev:.1f}°", f"{wp.slant_km:,.0f} km",
                          f"{wp.pfd:.1f} dBW/m²", f"{wp['limit']:.1f} dBW/m²",
                          f"{wp.margin:+.1f} dB"]})
            st.dataframe(chain, hide_index=True, width='stretch')
            st.caption(f"source: {wp.pfd_source} · proximity: {wp.proximity}"
                       + (f" · FDR −{wp.fdr_db:.0f} dB" if wp.proximity == 'adjacent' else ""))

        st.markdown("**Affected Finnish frequency bands**")
        st.dataframe(affected_bands(ific, int(pick)).rename(
            columns={"lo": "sat lo (MHz)", "hi": "sat hi (MHz)", "f": "freq (MHz)"}),
            hide_index=True, width='stretch', height=180)

        aff = affected_stations(ific, int(pick))
        st.markdown(f"**Affected protected stations ({len(aff)})**")
        if len(aff):
            st.dataframe(aff[["station_no", "role", "overlap_freq_mhz", "margin"]]
                         .rename(columns={"overlap_freq_mhz": "freq (MHz)"}),
                         hide_index=True, width='stretch', height=160)


if __name__ == "__main__":
    main()
