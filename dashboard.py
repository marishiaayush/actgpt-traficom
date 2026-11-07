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
def affected_area(ific, ntc, is_gso):
    """Which part of Finland (land + maritime/EEZ) the satellite can illuminate,
    plus the affected stations tagged land/maritime."""
    import geo
    if is_gso:
        con = sqlite3.connect(ROOT / "analysis" / f"srs{ific}.db")
        slot = pd.read_sql("SELECT MIN(long_nom) lon FROM geo WHERE ntc_id=?",
                           con, params=(ntc,)).lon.iloc[0]
        con.close()
        reg = geo.affected_region(True, slot_lon=slot)
    else:
        alt = q("SELECT alt_km FROM fin_geom_sgp4 WHERE ific_no=? AND sat_ntc_id=?",
                (ific, ntc))
        reg = geo.affected_region(False, alt_km=(float(alt.alt_km.iloc[0]) if len(alt) else 600))
    aff = affected_stations(ific, ntc)
    aff = aff.copy()
    aff["zone"] = [geo.classify_point(la, lo) for la, lo in zip(aff.lat, aff.lon)]
    return reg, aff


@st.cache_data(show_spinner=False)
def maritime_outline():
    import geo
    return geo.outline("eez")


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
    """Zoomable mapbox view: protected stations, maritime (EEZ) border, the
    illuminated part of Finland, affected stations (land/maritime), orbit track."""
    style = "carto-darkmatter" if dark else "carto-positron"
    allst = q("SELECT lat, lon FROM protected_stations WHERE lat IS NOT NULL")
    reg, aff = affected_area(ific, ntc, is_gso) if ntc else (None, pd.DataFrame())
    fig = go.Figure()

    # illuminated part of Finland (footprint ∩ territory)
    if reg is not None and reg["n_cells"]:
        fig.add_trace(go.Scattermap(lon=list(reg["lon"]), lat=list(reg["lat"]),
            mode="markers", marker=dict(size=5, color="rgba(49,130,206,0.20)"),
            name="illuminated area", hoverinfo="skip"))
    # maritime (EEZ) border
    mlon, mlat = maritime_outline()
    fig.add_trace(go.Scattermap(lon=mlon, lat=mlat, mode="lines",
        line=dict(width=1, color="#3182ce"), name="maritime (EEZ) border",
        hoverinfo="skip"))
    # all protected stations
    fig.add_trace(go.Scattermap(lon=allst.lon, lat=allst.lat, mode="markers",
        marker=dict(size=4, color="#9aa5b1"), name="protected stations",
        hoverinfo="skip"))
    # affected stations, split land vs maritime
    for z, col in [("land", "#e53e3e"), ("maritime", "#dd6b20")]:
        s = aff[aff.zone == z] if len(aff) else aff
        if len(s):
            fig.add_trace(go.Scattermap(lon=s.lon, lat=s.lat, mode="markers",
                marker=dict(size=11, color=col), name=f"affected · {z} ({len(s)})",
                text=[f"stn {int(n)}  {m:+.1f} dB" for n, m in zip(s.station_no, s.margin)],
                hoverinfo="text"))
    # orbit ground track (non-GSO)
    if ntc:
        kind, data = orbit_track(ific, ntc, is_gso)
        if kind == "track" and data is not None:
            fig.add_trace(go.Scattermap(lon=list(data[0]), lat=list(data[1]),
                mode="lines", line=dict(width=1.5, color="#805ad5"),
                name="orbit ground track", hoverinfo="skip"))

    fig.update_layout(
        map=dict(style=style, center=dict(lat=64.5, lon=26.0), zoom=3.4),
        height=600, margin=dict(l=0, r=0, t=0, b=0),
        legend=dict(orientation="h", y=-0.02, font=dict(size=10)),
        paper_bgcolor="rgba(0,0,0,0)",
        font_color="#e2e8f0" if dark else "#1a202c")
    st.plotly_chart(fig, width='stretch', config={"scrollZoom": True})


# --------------------------------------------------------------------------
# app
# --------------------------------------------------------------------------
BASE_CSS = """<style>
.actgpt-tbl { border-collapse: collapse; width: 100%; font-size: 0.82rem; }
.actgpt-tbl th, .actgpt-tbl td { border: 1px solid #e2e8f0; padding: 4px 8px;
    text-align: left; white-space: nowrap; }
.actgpt-tbl th { background: #f1f5f9; }
.actgpt-scroll { max-height: 220px; overflow: auto; }
</style>"""

DARK_CSS = """<style>
.stApp, [data-testid="stHeader"] { background-color: #0e1117; color: #e2e8f0; }
[data-testid="stSidebar"] { background-color: #161b26; }
[data-testid="stSidebar"] * , .stApp p, .stApp label, .stApp span,
.stMarkdown, h1,h2,h3,h4 { color: #e2e8f0 !important; }
[data-testid="stMetricValue"], [data-testid="stMetricLabel"] { color: #e2e8f0 !important; }
/* buttons: dark bg + light text (fixes the "white text on light button" bug) */
.stButton > button, [data-testid="stBaseButton-secondary"],
[data-testid="stLinkButton"] > a, [data-testid="stLinkButton"] a {
    background-color: #1f2937 !important; color: #e2e8f0 !important;
    border: 1px solid #374151 !important; }
/* inputs */
[data-baseweb="select"] > div, .stNumberInput input, .stTextInput input,
[data-baseweb="input"] { background-color: #1f2937 !important; color: #e2e8f0 !important; }
/* HTML tables -> dark */
.actgpt-tbl th, .actgpt-tbl td { border-color: #2d3748 !important; color: #e2e8f0 !important; }
.actgpt-tbl th { background: #1f2937 !important; }
</style>"""


def html_table(df, scroll=False):
    t = df.to_html(index=False, classes="actgpt-tbl", border=0, escape=False)
    return f'<div class="actgpt-scroll">{t}</div>' if scroll else t


def main():
    pubs = publications()
    with st.sidebar:
        st.title("🛰️ ACT-GPT")
        st.caption("ITU IFIC → Finnish interference triage")
        dark = st.toggle("🌙 Dark mode", value=False)
        st.divider()
    if dark:
        st.markdown(DARK_CSS, unsafe_allow_html=True)
    st.markdown(BASE_CSS, unsafe_allow_html=True)
    with st.sidebar:
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
            st.markdown(html_table(chain), unsafe_allow_html=True)
            st.caption(f"source: {wp.pfd_source} · proximity: {wp.proximity}"
                       + (f" · FDR −{wp.fdr_db:.0f} dB" if wp.proximity == 'adjacent' else ""))

        # affected part of Finland (land + maritime)
        reg, aff = affected_area(ific, int(pick), bool(srow.is_gso))
        st.markdown("**Affected part of Finland** (footprint ∩ territory)")
        a1, a2, a3 = st.columns(3)
        a1.metric("Finnish territory in footprint", f"{reg['pct_territory']:.0f}%")
        a2.metric("Maritime (EEZ) affected",
                  "yes" if reg["includes_maritime"] else "no",
                  f"{reg['pct_maritime']:.0f}% of sea" if reg["includes_maritime"] else None)
        nmar = int((aff.zone == "maritime").sum()) if len(aff) else 0
        a3.metric("Affected stations", f"{len(aff)}",
                  f"{nmar} maritime" if nmar else "all on land")

        st.markdown("**Affected Finnish frequency bands**")
        st.markdown(html_table(affected_bands(ific, int(pick)).rename(
            columns={"lo": "sat lo (MHz)", "hi": "sat hi (MHz)", "f": "freq (MHz)"}),
            scroll=True), unsafe_allow_html=True)

        st.markdown(f"**Affected protected stations ({len(aff)})**")
        if len(aff):
            st.markdown(html_table(
                aff[["station_no", "zone", "overlap_freq_mhz", "margin"]]
                .round({"overlap_freq_mhz": 2, "margin": 1})
                .rename(columns={"overlap_freq_mhz": "freq (MHz)"}), scroll=True),
                unsafe_allow_html=True)


if __name__ == "__main__":
    main()
