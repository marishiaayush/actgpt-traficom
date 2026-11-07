"""
ACT-GPT Traficom — interference triage dashboard (Phase 1).

Two-panel Streamlit app reading the consolidated app.db:
  LEFT  (visual) : map of affected Finnish stations + the satellite's orbit/footprint
  RIGHT (text)   : ranked shortlist, affected bands, and the transparent PFD math

Run:  uv run streamlit run dashboard.py
"""

import math
import sqlite3
import subprocess
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
                   page_icon="🛰️", layout="wide",
                   initial_sidebar_state="expanded")

STATUS_COLOR = {"ALERT": "#e53e3e", "CLEARED": "#2f855a", "visible": "#d69e2e",
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
    try:
        return q("SELECT * FROM publications ORDER BY ific_no DESC")
    except Exception:
        return pd.DataFrame()      # app.db not built yet -> sidebar prompts to run


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
    """Which part of Finland (land + maritime/EEZ) is OVER the Article-21 limit
    (per-cell PFD margin), plus the affected stations tagged land/maritime."""
    import geo
    reg = dict(lon=[], lat=[], pct_territory=0.0, includes_maritime=False,
               pct_maritime=0.0, n_cells=0)
    wp = worst_pair(ific, ntc)
    if wp is not None and wp.status == "scored":
        d_m = wp.slant_km * 1000.0
        eirp_eff = (wp.pfd + 20 * math.log10(d_m) + 10 * math.log10(4 * math.pi)
                    + (wp.fdr_db or 0))
        freq = wp.overlap_freq_mhz
        if is_gso:
            con = sqlite3.connect(ROOT / "analysis" / f"srs{ific}.db")
            slot = pd.read_sql("SELECT MIN(long_nom) lon FROM geo WHERE ntc_id=?",
                               con, params=(ntc,)).lon.iloc[0]
            con.close()
            reg = geo.over_limit_region(True, eirp_eff, freq, slot_lon=slot)
        else:
            gi = q("SELECT alt_km, incl FROM fin_geom_sgp4 WHERE ific_no=? AND sat_ntc_id=?",
                   (ific, ntc))
            reg = geo.over_limit_region(
                False, eirp_eff, freq,
                alt_km=float(gi.alt_km.iloc[0]) if len(gi) else 600.0,
                incl=float(gi.incl.iloc[0]) if len(gi) else 90.0)
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
def map_panel(ific, ntc, is_gso, dark, focused, key):
    """Zoomable mapbox view: protected stations, maritime (EEZ) border, the
    illuminated part of Finland, affected stations (land/maritime), orbit track.
    `focused` station is enlarged and the map recenters on it; markers are also
    clickable (on_select)."""
    clicked = focused
    style = "carto-darkmatter" if dark else "carto-positron"
    allst = q("SELECT station_no, lat, lon, licence_class FROM protected_stations "
              "WHERE lat IS NOT NULL")
    reg, aff = affected_area(ific, ntc, is_gso) if ntc else (None, pd.DataFrame())
    fig = go.Figure()

    # illuminated part of Finland (margin>0 cells)
    if reg is not None and reg["n_cells"]:
        fig.add_trace(go.Scattermap(lon=list(reg["lon"]), lat=list(reg["lat"]),
            mode="markers", marker=dict(size=5, color="rgba(229,62,62,0.16)"),
            name="over-limit area", hoverinfo="skip"))
    # maritime (EEZ) border
    mlon, mlat = maritime_outline()
    fig.add_trace(go.Scattermap(lon=mlon, lat=mlat, mode="lines",
        line=dict(width=1, color="#3182ce"), name="maritime (EEZ) border",
        hoverinfo="skip"))
    # all protected stations (hover shows id + class)
    fig.add_trace(go.Scattermap(lon=allst.lon, lat=allst.lat, mode="markers",
        marker=dict(size=4, color="#9aa5b1"), name="protected stations",
        text=[f"stn {int(n)} · {c or '?'}" for n, c in zip(allst.station_no, allst.licence_class)],
        hoverinfo="text"))
    # affected stations, split land vs maritime (rich hover + clickable)
    for z, col in [("land", "#e53e3e"), ("maritime", "#dd6b20")]:
        s = aff[aff.zone == z] if len(aff) else aff
        if len(s):
            sized = [16 if int(n) == clicked else 12 for n in s.station_no]
            fig.add_trace(go.Scattermap(lon=s.lon, lat=s.lat, mode="markers",
                marker=dict(size=sized, color=col), name=f"affected · {z} ({len(s)})",
                customdata=[int(n) for n in s.station_no],
                text=[f"stn {int(r.station_no)} · {z}<br>{r.overlap_freq_mhz:.1f} MHz · "
                      f"margin {r.margin:+.1f} dB<br>class {r.role}" for r in s.itertuples()],
                hoverinfo="text"))
    # orbit ground track (non-GSO)
    if ntc:
        kind, data = orbit_track(ific, ntc, is_gso)
        if kind == "track" and data is not None:
            fig.add_trace(go.Scattermap(lon=list(data[0]), lat=list(data[1]),
                mode="lines", line=dict(width=1.5, color="#805ad5"),
                name="orbit ground track", hoverinfo="skip"))

    lab = "#e2e8f0" if dark else "#1a202c"
    ctr, zoom = dict(lat=64.5, lon=26.0), 3.4
    if clicked is not None and len(aff):
        fr = aff[aff.station_no == clicked]
        if len(fr):
            ctr, zoom = dict(lat=float(fr.lat.iloc[0]), lon=float(fr.lon.iloc[0])), 6.0
    fig.update_layout(
        map=dict(style=style, center=ctr, zoom=zoom),
        height=600, margin=dict(l=0, r=0, t=0, b=0),
        legend=dict(orientation="h", y=-0.03, font=dict(size=13, color=lab),
                    bgcolor="rgba(0,0,0,0)"),
        paper_bgcolor="rgba(0,0,0,0)", font=dict(color=lab, size=13))
    st.plotly_chart(fig, width='stretch', config={"scrollZoom": True},
                    on_select="rerun", selection_mode="points", key=key)


def clicked_from(key):
    """Extract the station_no clicked on the map (from its selection state)."""
    sel = st.session_state.get(key)
    try:
        pts = sel["selection"]["points"]
        if pts:
            cd = pts[0].get("customdata")
            return int(cd[0] if isinstance(cd, (list, tuple)) else cd)
    except Exception:
        pass
    return None


def spectrum_panel(ific, ntc, dark):
    """Frequency view under the map: the satellite's emission band(s) vs the
    Finnish RX channel(s) it overlaps -- shows the bandwidth it interferes with."""
    d = q("""SELECT DISTINCT o.sat_lo_mhz, o.sat_hi_mhz, o.victim_freq_mhz,
                    o.proximity, s.channel_bw_mhz bw
             FROM fin_freq_overlap o JOIN protected_stations s
               ON s.station_no=o.station_no
             WHERE o.ific_no=? AND o.sat_ntc_id=? ORDER BY o.victim_freq_mhz LIMIT 80""",
          (ific, ntc))
    if d.empty:
        return
    lab = "#e2e8f0" if dark else "#1a202c"
    fig = go.Figure()
    sx = []
    for b in d[["sat_lo_mhz", "sat_hi_mhz"]].drop_duplicates().itertuples():
        sx += [b.sat_lo_mhz, b.sat_hi_mhz, None]
    fig.add_trace(go.Scatter(x=sx, y=[1] * len(sx), mode="lines",
        line=dict(width=12, color="#2b6cb0"), name="satellite emission"))
    vx = []
    for r in d.itertuples():
        hw = (r.bw or 0.05) / 2.0
        vx += [r.victim_freq_mhz - hw, r.victim_freq_mhz + hw, None]
    fig.add_trace(go.Scatter(x=vx, y=[0] * len(vx), mode="lines",
        line=dict(width=12, color="#2f855a"), name="Finnish RX channel"))
    fig.update_layout(height=170, margin=dict(l=0, r=0, t=4, b=0),
        template="plotly_dark" if dark else "plotly_white",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        yaxis=dict(tickvals=[0, 1], ticktext=["FIN RX", "sat TX"], range=[-0.6, 1.6],
                   tickfont=dict(color=lab, size=12)),
        xaxis=dict(title="frequency (MHz)", color=lab),
        legend=dict(orientation="h", y=1.3, font=dict(color=lab, size=12)))
    st.plotly_chart(fig, width='stretch')


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
/* buttons */
.stButton > button, [data-testid="stBaseButton-secondary"],
[data-testid="stLinkButton"] > a, [data-testid="stLinkButton"] a {
    background-color: #1f2937 !important; color: #e2e8f0 !important;
    border: 1px solid #374151 !important; }
/* selectbox + number input: target the stable Streamlit WRAPPER classes and
   every descendant (robust to baseweb's internal structure) */
.stSelectbox div, .stSelectbox span, .stSelectbox input, .stSelectbox svg,
.stNumberInput div, .stNumberInput span, .stNumberInput input,
.stTextInput div, .stTextInput input {
    background-color: #1f2937 !important; color: #e2e8f0 !important;
    fill: #e2e8f0 !important; border-color: #374151 !important; }
/* dropdown menu (rendered in a body-root portal) */
ul[role="listbox"], li[role="option"], div[data-baseweb="popover"] div,
div[data-baseweb="menu"] * {
    background-color: #1f2937 !important; color: #e2e8f0 !important; }
li[role="option"]:hover { background-color: #2d3748 !important; }
/* alerts: info / success / warning / error -- wrapper + all descendants */
.stAlert, .stAlert div, .stAlert p, .stAlert span,
[data-testid="stAlert"], [data-testid="stAlert"] *,
[data-testid="stAlertContainer"], [data-testid="stAlertContainer"] * {
    background-color: #1a2435 !important; color: #e2e8f0 !important;
    border-color: #2d3748 !important; }
/* HTML tables -> dark */
.actgpt-tbl th, .actgpt-tbl td { border-color: #2d3748 !important; color: #e2e8f0 !important; }
.actgpt-tbl th { background: #1f2937 !important; }
</style>"""


def html_table(df, scroll=False):
    t = df.to_html(index=False, classes="actgpt-tbl", border=0, escape=False)
    return f'<div class="actgpt-scroll">{t}</div>' if scroll else t


# --------------------------------------------------------------------------
# reviewer label overrides (human-in-the-loop) -- persisted in app.db
# --------------------------------------------------------------------------
OVERRIDE_LABELS = ["ALERT", "CLEARED", "visible", "not_visible", "needs_data"]


def _ensure_overrides():
    con = sqlite3.connect(APP_DB)
    con.execute("""CREATE TABLE IF NOT EXISTS review_overrides
        (ific_no INT, sat_ntc_id INT, label TEXT, ts TEXT,
         PRIMARY KEY(ific_no, sat_ntc_id))""")
    con.commit(); con.close()


def set_override(ific, ntc, label):
    from datetime import datetime, timezone
    _ensure_overrides()
    con = sqlite3.connect(APP_DB)
    if label is None:
        con.execute("DELETE FROM review_overrides WHERE ific_no=? AND sat_ntc_id=?",
                    (int(ific), int(ntc)))
    else:
        con.execute("INSERT OR REPLACE INTO review_overrides VALUES (?,?,?,?)",
                    (int(ific), int(ntc), label,
                     datetime.now(timezone.utc).isoformat(timespec="seconds")))
    con.commit(); con.close()
    q.clear()


def get_overrides(ific):
    _ensure_overrides()
    d = q("SELECT sat_ntc_id, label FROM review_overrides WHERE ific_no=?", (ific,))
    return dict(zip(d.sat_ntc_id, d.label)) if len(d) else {}


def with_effective_label(sl, ific):
    ov = get_overrides(ific)
    sl = sl.copy()
    sl["label"] = [ov.get(int(n), rs) for n, rs in zip(sl.sat_ntc_id, sl.review_status)]
    sl["overridden"] = [int(n) in ov for n in sl.sat_ntc_id]
    return sl


# --------------------------------------------------------------------------
# Database tab -- browse raw data, relabel
# --------------------------------------------------------------------------
def database_view(ific, dark):
    st.subheader("🗄️ Raw data — browse, highlight, relabel")
    sl = with_effective_label(shortlist(ific), ific)
    tables = {
        "Shortlist (relabelable)": sl[["sat_ntc_id", "sat_name", "adm", "is_gso",
            "review_status", "label", "overridden", "worst_margin_db",
            "alert_stations", "n_bands"]],
        "PFD scores": q(f"""SELECT sat_ntc_id, adm, station_no,
            ROUND(overlap_freq_mhz,2) freq_mhz, proximity, is_gso,
            ROUND(elev,1) elev, ROUND(margin,1) margin, status, pfd_source
            FROM fin_pfd_score WHERE ific_no={int(ific)} LIMIT 5000"""),
        "Frequency overlaps": q(f"""SELECT sat_ntc_id, adm, ROUND(sat_lo_mhz,2) sat_lo,
            ROUND(sat_hi_mhz,2) sat_hi, station_no, ROUND(victim_freq_mhz,2) rx_mhz,
            proximity, ROUND(offset_mhz,1) offset, band
            FROM fin_freq_overlap WHERE ific_no={int(ific)} LIMIT 5000"""),
        "SGP4 geometry": q(f"SELECT * FROM fin_geom_sgp4 WHERE ific_no={int(ific)}"),
        "Protected stations (Finland)": q("""SELECT station_no, licence_class, lat, lon,
            ROUND(tx_freq_mhz,3) tx_mhz, ROUND(rx_freq_mhz,3) rx_mhz, band,
            ROUND(power_dbw,1) power_dbw FROM protected_stations"""),
        "M4 allocations": q("""SELECT Services_in_Finland, Sub_band_usage,
            ROUND(sub_lo_mhz,4) lo_mhz, ROUND(sub_hi_mhz,4) hi_mhz FROM m4_allocations"""),
        "Publications": q("SELECT * FROM publications"),
    }
    name = st.selectbox("table", list(tables))
    df = tables[name]
    st.caption(f"{len(df):,} rows")

    if name.startswith("Shortlist"):
        # inline relabel: edit the `label` cell of ANY row (persisted)
        st.caption("✏️ Edit the **label** column on any row to relabel "
                   "(reviewer override — persisted).")
        cols = ["sat_ntc_id", "sat_name", "adm", "is_gso", "review_status",
                "label", "worst_margin_db", "alert_stations", "n_bands"]
        edited = st.data_editor(
            sl[cols], hide_index=True, width='stretch', height=480,
            key=f"relabel_{ific}", disabled=[c for c in cols if c != "label"],
            column_config={"label": st.column_config.SelectboxColumn(
                "label", options=OVERRIDE_LABELS, required=True)})
        changed = False
        for r in edited.itertuples():
            orig = sl.loc[sl.sat_ntc_id == r.sat_ntc_id, "label"].iloc[0]
            if r.label != orig:
                auto = sl.loc[sl.sat_ntc_id == r.sat_ntc_id, "review_status"].iloc[0]
                set_override(ific, r.sat_ntc_id, None if r.label == auto else r.label)
                changed = True
        if changed:
            st.rerun()
        return

    def hl_margin(v):
        try:
            return "background-color: rgba(229,62,62,0.28)" if float(v) > 0 else ""
        except Exception:
            return ""
    def hl_label(v):
        return {"ALERT": "background-color: rgba(229,62,62,0.28)",
                "CLEARED": "background-color: rgba(47,133,90,0.28)",
                "visible": "background-color: rgba(214,158,46,0.22)"}.get(v, "")
    sty = df.style
    if "margin" in df.columns:
        sty = sty.map(hl_margin, subset=["margin"])
    if "worst_margin_db" in df.columns:
        sty = sty.map(hl_margin, subset=["worst_margin_db"])
    st.dataframe(sty, width='stretch', height=480)


def main():
    pubs = publications()
    logo = ROOT / "Logo.svg"
    if logo.exists():
        try:
            st.logo(str(logo), size="large")
        except Exception:
            pass
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
            st.warning("No processed publications yet.")
            st.info("Build `app.db` first:\n\n"
                    "```\nuv run python analysis/pipeline.py 3074\n```\n\n"
                    "(needs the IFIC `.mdb` — see SETUP.md)")
            st.stop()
        import poller
        ific = st.selectbox("Publication (IFIC)", pubs.ific_no,
                            format_func=lambda x: f"IFIC {x} (space)")
        row = pubs[pubs.ific_no == ific].iloc[0]
        st.metric("Notices", int(row.n_notices))
        st.metric("Shortlisted", int(row.n_shortlist))
        st.metric("ALERTs", int(row.n_alerts))
        st.caption(f"last processed: {row.processed_at}")
        st.link_button("📄 Fetch ITU report (.zip)", poller.report_url(ific))
        import report as _report
        _xls, _gen = _report.build_report_xlsx(ific)
        st.download_button(
            "📊 Generate review report (.xlsx)", _xls,
            file_name=f"actgpt_IFIC{ific}_{_gen[:19].replace(':', '-')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width='stretch',
            help="Timestamped summary: analysis + reviewer changes")
        st.divider()

        # --- Phase 3: watch ITU for new publications ---
        st.markdown("**ITU watch**")
        lc = poller.last_checked()
        st.caption(f"last checked: {lc}" if lc else "not checked yet")
        if st.button("🔄 Check ITU for new IFIC", width='stretch'):
            with st.spinner("Checking ITU demowic ..."):
                st.session_state["chk"] = poller.check_itu()
            st.rerun()
        chk = st.session_state.get("chk")
        if chk:
            if not chk["ok"]:
                st.warning("Could not reach ITU (offline?).")
            elif chk["new"]:
                st.info(f"{len(chk['new'])} unprocessed IFIC(s) available. "
                        f"Latest: {max(chk['available'])}")
                pick_new = st.selectbox("process a new IFIC", chk["new"][::-1])
                if st.button(f"⬇️ Download & process IFIC {pick_new}", width='stretch'):
                    with st.spinner(f"Downloading + processing IFIC {pick_new} "
                                    "(large; may take minutes) ..."):
                        from pipeline import run_ific
                        try:
                            poller.download_mdb(int(pick_new))
                            run_ific(int(pick_new))
                            q.clear(); st.session_state.pop("chk", None)
                            st.success(f"IFIC {pick_new} processed — select it above.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed: {e}")
            else:
                st.success("Up to date — no new IFIC.")

        st.divider()
        with st.expander("⚙️ Data sources (country config)"):
            st.caption("Swap the protected-station list (same column order).")
            up = st.file_uploader("Protected stations (.xlsx)", type=["xlsx"], key="stn_up")
            if up is not None and st.button("Rebuild from this list", width='stretch'):
                with st.spinner("Rebuilding stations + reprocessing all IFICs ..."):
                    path = ROOT / "analysis" / "uploaded_stations.xlsx"
                    path.write_bytes(up.getvalue())
                    r = subprocess.run([sys.executable, str(ROOT/"analysis"/"explore.py"),
                                        str(path)], capture_output=True, text=True)
                    if r.returncode != 0:
                        st.error("explore.py failed:\n" + (r.stderr or "")[-700:])
                    else:
                        from pipeline import run_ific
                        for i in list(pubs.ific_no):
                            run_ific(int(i))
                        q.clear()
                        st.success("Rebuilt — new stations applied to all publications.")
                        st.rerun()
            st.caption("**Article-21 limits** are data-driven: edit "
                       "`analysis/data/article21_table21-4.csv`. "
                       "M4 allocation / boundary parametrization → roadmap.")

    tab_triage, tab_db = st.tabs(["🛰️  Triage", "🗄️  Database"])
    with tab_db:
        database_view(ific, dark)
    with tab_triage:
        render_triage(ific, row, dark)


def render_triage(ific, row, dark):
    sl = with_effective_label(
        shortlist(ific).sort_values(["review_status", "worst_margin_db"],
                                    ascending=[True, False]), ific)
    n_alert = int((sl.label == "ALERT").sum())
    st.subheader(f"IFIC {ific} — {n_alert} satellites flagged for review")

    # --- Phase 4: bring your own receiver(s) ---
    with st.expander("🧭 Check your own receiver(s) — land or maritime"):
        st.caption("Enter coordinates + RX frequency/bandwidth. Add rows for multiple receivers.")
        ed = st.data_editor(
            pd.DataFrame([{"lat": 61.5, "lon": 20.5, "freq_MHz": 2200.0, "bw_MHz": 2.0}]),
            num_rows="dynamic", width='stretch', key="rx_ed")
        if st.button("Check interference", key="rx_go"):
            import receiver
            import geo as _geo
            summary = []
            details = []
            for _, r in ed.dropna().iterrows():
                try:
                    res = receiver.score_receiver(ific, float(r.lat), float(r.lon),
                                                  float(r.freq_MHz), float(r.bw_MHz))
                except Exception as e:
                    st.error(f"receiver {r.lat},{r.lon} failed: {e}"); continue
                zone = _geo.classify_point(float(r.lat), float(r.lon))
                al = res[res.margin > 0] if len(res) else res
                top = al.iloc[0] if len(al) else None
                summary.append(dict(receiver=f"{r.lat:.2f}, {r.lon:.2f} ({zone})",
                                    freq=f"{r.freq_MHz:.1f} MHz", in_band=len(res),
                                    alerts=len(al),
                                    worst=f"{top['name']} {top.margin:+.1f} dB" if top is not None else "—"))
                if len(al):
                    details.append((f"{r.lat:.2f},{r.lon:.2f} @ {r.freq_MHz:.0f} MHz ({zone})",
                                    al[["name", "adm", "is_gso", "elev", "margin"]].head(8)))
            if summary:
                st.markdown(html_table(pd.DataFrame(summary)), unsafe_allow_html=True)
                for title, dfd in details:
                    st.markdown(f"*threats — {title}*")
                    st.markdown(html_table(dfd), unsafe_allow_html=True)

    left, right = st.columns([1.1, 1], gap="large")
    with right:
        f = st.radio("filter", ["ALERT", "all"], horizontal=True, label_visibility="collapsed")
        view = sl if f == "all" else sl[sl.label == "ALERT"]
        TAG = {"ALERT": "🔴", "CLEARED": "✅", "visible": "🟡",
               "not_visible": "⚪", "needs_data": "🟣"}
        disp = (view.label.map(TAG).fillna("·") + " "
                + view.sat_name.fillna("?") + " · " + view.adm.fillna("?")
                + view.worst_margin_db.map(lambda m: f"  ({m:+.1f} dB)" if pd.notna(m) else "")
                + view.overridden.map(lambda o: " ✎" if o else ""))
        pick = st.selectbox(f"shortlist ({len(view)})", view.sat_ntc_id,
                            format_func=lambda n: disp[view.sat_ntc_id == n].iloc[0])
        srow = view[view.sat_ntc_id == pick].iloc[0]
        # focus a station -> highlighted on the map. Driven by THIS selector OR a
        # map click (synced): map click writes the selector's state before it renders.
        affz = affected_stations(ific, int(pick))
        mapkey = f"map_{ific}_{pick}"
        focuskey = f"focus_{ific}_{pick}"
        clicked = clicked_from(mapkey)
        if (clicked is not None and clicked in set(affz.station_no)
                and st.session_state.get(focuskey) != clicked):
            st.session_state[focuskey] = clicked
        focused = None
        if len(affz):
            focused = st.selectbox("🔦 focus a station (or click one on the map)",
                                   [None] + [int(n) for n in affz.station_no], key=focuskey,
                                   format_func=lambda s: "— none —" if s is None else f"station {s}")

    with left:
        map_panel(ific, int(pick), bool(srow.is_gso), dark, focused, mapkey)
        st.caption("Interfering bandwidth — satellite emission vs Finnish RX channel")
        spectrum_panel(ific, int(pick), dark)

    with right:
        c = STATUS_COLOR.get(srow.label, "#718096")
        ov_mark = " ✎ reviewer override" if srow.overridden else ""
        st.markdown(f"### {srow.sat_name or '?'} "
                    f"<span style='color:{c}'>({srow.label})</span>"
                    f"<span style='font-size:.7rem;color:#999'>{ov_mark}</span>",
                    unsafe_allow_html=True)
        m1, m2, m3 = st.columns(3)
        m1.metric("Admin", srow.adm or "?")
        m2.metric("Type", "GSO" if srow.is_gso else "non-GSO")
        m3.metric("Worst margin",
                  f"{srow.worst_margin_db:+.1f} dB" if pd.notna(srow.worst_margin_db) else "—")
        # reviewer relabel (human-in-the-loop)
        b1, b2, b3 = st.columns(3)
        if b1.button("✅ Clear", width='stretch', help="Mark reviewed — not a concern"):
            set_override(ific, int(pick), "CLEARED"); st.rerun()
        if b2.button("🔴 Flag ALERT", width='stretch'):
            set_override(ific, int(pick), "ALERT"); st.rerun()
        if b3.button("↩️ Reset", width='stretch', help="Back to the auto label"):
            set_override(ific, int(pick), None); st.rerun()

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
        st.markdown("**Affected part of Finland** (area over the Article-21 limit)")
        a1, a2, a3 = st.columns(3)
        a1.metric("Territory over limit", f"{reg['pct_territory']:.0f}%")
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
        if focused and focused in set(aff.station_no):
            st.caption(f"📍 focused: station {focused} (highlighted on the map)")
        if len(aff):
            tdf = (aff[["station_no", "zone", "overlap_freq_mhz", "margin"]]
                   .round({"overlap_freq_mhz": 2, "margin": 1})
                   .rename(columns={"overlap_freq_mhz": "freq (MHz)"}))
            tdf.insert(0, "", ["📍" if int(n) == focused else "" for n in tdf.station_no])
            if focused in set(tdf.station_no):      # focused row first
                tdf = pd.concat([tdf[tdf.station_no == focused],
                                 tdf[tdf.station_no != focused]])
            st.markdown(html_table(tdf, scroll=True), unsafe_allow_html=True)


if __name__ == "__main__":
    main()
