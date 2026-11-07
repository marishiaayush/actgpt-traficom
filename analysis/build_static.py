"""
Phase 5 -- static export for GitHub Pages.

Renders the current app.db + geometry into a self-contained docs/ site (a
read-only, precomputed showcase of the triage). No Python at view time, so it
can live on github.io as an always-on, shareable demo.

    uv run python analysis/build_static.py
    -> docs/index.html  (+ embedded data)

Enable Pages: GitHub repo Settings -> Pages -> Source: main / docs.
"""

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

A = Path(__file__).resolve().parent
ROOT = A.parent
APP_DB = A / "app.db"
DOCS = ROOT / "docs"
sys.path.insert(0, str(A))
import geo
from geometry_sgp4 import make_sat, TS
from skyfield.api import wgs84


def maritime_segments():
    """EEZ outline as a list of polylines (simplified for the web)."""
    from shapely.geometry import shape
    g = geo.load()["eez"].simplify(0.15)
    polys = g.geoms if g.geom_type == "MultiPolygon" else [g]
    segs = []
    for p in polys:
        x, y = p.exterior.xy
        segs.append([[round(a, 3), round(b, 3)] for a, b in zip(x, y)])
    return segs


def orbit_track(srs, ntc):
    pl = pd.read_sql("""SELECT inclin_ang, op_ht_km, long_asc FROM orbit
                        WHERE ntc_id=? AND op_ht_km IS NOT NULL LIMIT 1""",
                     srs, params=(ntc,))
    if pl.empty:
        return None
    r = pl.iloc[0]
    sat = make_sat(r.inclin_ang, r.op_ht_km,
                   r.long_asc if pd.notna(r.long_asc) else 0.0, 0.0, 1)
    sp = wgs84.subpoint(sat.at(TS.utc(2026, 11, 7, 0, range(0, 200, 2))))
    return [[round(float(lo), 2), round(float(la), 2)]
            for lo, la in zip(sp.longitude.degrees, sp.latitude.degrees)]


def build_payload():
    app = sqlite3.connect(APP_DB)
    srs = sqlite3.connect(A / "srs3074.db")
    pub = pd.read_sql("SELECT * FROM publications", app).iloc[0]
    sl = pd.read_sql("""SELECT * FROM shortlist WHERE ific_no=?
                        ORDER BY review_status, worst_margin_db DESC""",
                     app, params=(int(pub.ific_no),))
    allst = pd.read_sql("SELECT lon, lat FROM protected_stations WHERE lon IS NOT NULL", app)

    sats = {}
    for r in sl.itertuples():
        ntc = int(r.sat_ntc_id)
        d = dict(name=r.sat_name or "?", adm=r.adm or "?", is_gso=bool(r.is_gso),
                 status=r.review_status,
                 margin=None if pd.isna(r.worst_margin_db) else round(r.worst_margin_db, 1),
                 n_bands=int(r.n_bands or 0))
        if r.review_status == "ALERT":
            wp = pd.read_sql('''SELECT overlap_freq_mhz f, elev, slant_km, pfd,
                                "limit" lim, margin, pfd_source, proximity
                                FROM fin_pfd_score WHERE ific_no=? AND sat_ntc_id=?
                                AND status='scored' ORDER BY margin DESC LIMIT 1''',
                             app, params=(int(pub.ific_no), ntc)).iloc[0]
            d["chain"] = dict(freq=round(wp.f, 2), elev=round(wp.elev, 1),
                              slant=round(wp.slant_km), pfd=round(wp.pfd, 1),
                              limit=round(wp.lim, 1), margin=round(wp.margin, 1),
                              src=wp.pfd_source, prox=wp.proximity)
            aff = pd.read_sql("""SELECT DISTINCT p.station_no, s.lat, s.lon, p.margin
                                 FROM fin_pfd_score p JOIN protected_stations s
                                 ON s.station_no=p.station_no WHERE p.ific_no=?
                                 AND p.sat_ntc_id=? AND p.status='scored' AND p.margin>0
                                 ORDER BY p.margin DESC""",
                              app, params=(int(pub.ific_no), ntc))
            d["affected"] = [[round(x.lon, 3), round(x.lat, 3), round(x.margin, 1),
                              geo.classify_point(x.lat, x.lon)] for x in aff.itertuples()]
            bands = pd.read_sql("""SELECT DISTINCT ROUND(interf_freq_mhz,2) f, proximity
                                   FROM fin_freq_overlap WHERE ific_no=? AND sat_ntc_id=?
                                   ORDER BY f LIMIT 40""",
                                app, params=(int(pub.ific_no), ntc))
            m4 = pd.read_sql("SELECT Services_in_Finland s, sub_lo_mhz lo, sub_hi_mhz hi FROM m4_allocations", app)
            def svc(f):
                h = m4[(m4.lo <= f) & (f <= m4.hi)]
                return h.s.iloc[0] if len(h) else "(no M4)"
            d["bands"] = [[b.f, b.proximity, svc(b.f)] for b in bands.itertuples()]
            # bandwidth/spectrum: satellite emission bands vs Finnish RX channels
            spec = pd.read_sql("""SELECT DISTINCT o.sat_lo_mhz lo, o.sat_hi_mhz hi,
                                         o.victim_freq_mhz vf, s.channel_bw_mhz bw
                                  FROM fin_freq_overlap o JOIN protected_stations s
                                    ON s.station_no=o.station_no
                                  WHERE o.ific_no=? AND o.sat_ntc_id=? LIMIT 80""",
                               app, params=(int(pub.ific_no), ntc))
            d["spectrum"] = dict(
                sat=[[round(b.lo, 2), round(b.hi, 2)]
                     for b in spec[["lo", "hi"]].drop_duplicates().itertuples()],
                rx=[[round(x.vf - (x.bw or 0.05)/2, 3), round(x.vf + (x.bw or 0.05)/2, 3)]
                    for x in spec.itertuples()])
            # over-limit region (per-cell PFD margin), using EIRP backed out of wp
            import math as _m
            eirp_eff = wp.pfd + 20*_m.log10(wp.slant_km*1000) + 10*_m.log10(4*_m.pi)
            if r.is_gso:
                slot = pd.read_sql("SELECT MIN(long_nom) l FROM geo WHERE ntc_id=?",
                                   srs, params=(ntc,)).l.iloc[0]
                reg = geo.over_limit_region(True, eirp_eff, wp.f, slot_lon=slot)
                d["orbit"] = None
            else:
                gi = pd.read_sql("SELECT alt_km a, incl i FROM fin_geom_sgp4 WHERE ific_no=? AND sat_ntc_id=?",
                                 app, params=(int(pub.ific_no), ntc))
                reg = geo.over_limit_region(False, eirp_eff, wp.f,
                        alt_km=float(gi.a.iloc[0]) if len(gi) else 600,
                        incl=float(gi.i.iloc[0]) if len(gi) else 90)
                d["orbit"] = orbit_track(srs, ntc)
            nmar = sum(1 for x in d["affected"] if x[3] == "maritime")
            d["area"] = dict(pct=reg["pct_territory"], maritime=reg["includes_maritime"],
                             pct_sea=reg["pct_maritime"], n=len(d["affected"]), n_mar=nmar)
        sats[ntc] = d
    app.close(); srs.close()
    return dict(
        publication=dict(ific=int(pub.ific_no), service=pub.service_type,
                         country=pub.country, n_notices=int(pub.n_notices),
                         n_shortlist=int(pub.n_shortlist), n_alerts=int(pub.n_alerts),
                         processed_at=pub.processed_at, pdf_url=pub.pdf_url),
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        shortlist=[int(n) for n in sl.sat_ntc_id],
        stations=[[round(x.lon, 3), round(x.lat, 3)] for x in allst.itertuples()],
        maritime=maritime_segments(), satellites=sats)


def main():
    DOCS.mkdir(exist_ok=True)
    payload = build_payload()
    html = TEMPLATE.replace("/*DATA*/", json.dumps(payload, separators=(",", ":")))
    (DOCS / "index.html").write_text(html)
    size = (DOCS / "index.html").stat().st_size / 1024
    (DOCS / ".nojekyll").write_text("")
    print(f"Wrote {DOCS/'index.html'} ({size:.0f} KB) — {payload['publication']['n_alerts']} alerts")
    print("Enable: GitHub Settings -> Pages -> Source: main / docs")


TEMPLATE = r"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ACT-GPT · Traficom interference triage</title>
<script src="https://cdn.plot.ly/plotly-3.0.1.min.js" charset="utf-8"></script>
<style>
:root{--bg:#f7fafc;--panel:#fff;--text:#1a202c;--muted:#718096;--line:#e2e8f0;--accent:#2b6cb0}
body.dark{--bg:#0e1117;--panel:#161b26;--text:#e2e8f0;--muted:#94a3b8;--line:#2d3748;--accent:#63b3ed}
*{box-sizing:border-box}body{margin:0;font-family:system-ui,-apple-system,sans-serif;
background:var(--bg);color:var(--text);transition:background .25s,color .25s}
header{display:flex;align-items:center;gap:16px;padding:12px 20px;border-bottom:1px solid var(--line)}
header h1{font-size:1.1rem;margin:0}.pill{background:var(--accent);color:#fff;border-radius:999px;
padding:2px 10px;font-size:.8rem}.muted{color:var(--muted);font-size:.8rem}
.toggle{margin-left:auto;cursor:pointer;border:1px solid var(--line);background:var(--panel);
color:var(--text);border-radius:8px;padding:6px 12px}
.wrap{display:grid;grid-template-columns:1.1fr 1fr;gap:16px;padding:16px;max-width:1500px;margin:auto}
@media(max-width:900px){.wrap{grid-template-columns:1fr}}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;margin-bottom:14px}
#map{height:560px;border-radius:12px;overflow:hidden}
.list{max-height:240px;overflow:auto}.row{padding:7px 10px;border-radius:8px;cursor:pointer;
display:flex;justify-content:space-between;gap:8px;font-size:.85rem}.row:hover{background:var(--line)}
.row.sel{background:var(--accent);color:#fff}.tag{font-size:.7rem;padding:1px 7px;border-radius:999px;color:#fff}
.ALERT{background:#e53e3e}.visible{background:#d69e2e}.not_visible{background:#718096}.needs_data{background:#a0aec0}
table{border-collapse:collapse;width:100%;font-size:.8rem}td,th{border:1px solid var(--line);padding:4px 8px;text-align:left}
th{background:var(--line)}.metrics{display:flex;gap:10px;flex-wrap:wrap}.metric{flex:1;min-width:90px;
background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:8px}.metric .v{font-size:1.2rem;font-weight:600}
a.btn{display:inline-block;text-decoration:none;color:var(--accent);border:1px solid var(--line);
border-radius:8px;padding:5px 10px;font-size:.8rem}.filter{display:flex;gap:6px;margin-bottom:8px}
.filter button{border:1px solid var(--line);background:var(--panel);color:var(--text);border-radius:8px;padding:3px 10px;cursor:pointer}
.filter button.on{background:var(--accent);color:#fff}
</style></head><body>
<header><h1>🛰️ ACT-GPT</h1><span class="pill" id="ific"></span>
<span class="muted" id="prov"></span>
<button class="toggle" onclick="toggleDark()">🌙 Dark</button></header>
<div class="wrap">
  <div><div class="card"><div id="map"></div></div>
    <div class="card"><div class="muted" style="margin-bottom:6px">Interfering bandwidth — satellite emission (blue) vs Finnish RX channel (green)</div><div id="spectrum"></div></div>
    <div class="card"><b>Finnish interference triage</b> — precomputed static demo.
    <span class="muted">Live interactive version runs locally via Streamlit; this read-only
    snapshot is generated from the same backend.</span></div></div>
  <div>
    <div class="card"><div class="metrics" id="pubmetrics"></div>
      <a class="btn" id="report" target="_blank">📄 ITU report</a></div>
    <div class="card"><div class="filter"><button onclick="setFilter('ALERT')" id="fA" class="on">ALERT</button>
      <button onclick="setFilter('all')" id="fAll">all</button></div>
      <div class="list" id="list"></div></div>
    <div class="card" id="detail"></div>
  </div>
</div>
<script>
const D=/*DATA*/;let filter="ALERT",sel=null,dark=false;
const el=id=>document.getElementById(id);
el("ific").textContent="IFIC "+D.publication.ific+" · "+D.publication.service;
el("prov").textContent="processed "+D.publication.processed_at+" · generated "+D.generated_at;
el("report").href=D.publication.pdf_url||"https://www.itu.int";
el("pubmetrics").innerHTML=[["Notices",D.publication.n_notices],["Shortlisted",D.publication.n_shortlist],
["ALERTs",D.publication.n_alerts]].map(m=>`<div class="metric"><div class="muted">${m[0]}</div><div class="v">${m[1]}</div></div>`).join("");
function setFilter(f){filter=f;el("fA").className=f=="ALERT"?"on":"";el("fAll").className=f=="all"?"on":"";renderList();}
function renderList(){const rows=D.shortlist.filter(n=>filter=="all"||D.satellites[n].status=="ALERT");
el("list").innerHTML=rows.map(n=>{const s=D.satellites[n];return `<div class="row ${n==sel?'sel':''}" onclick="select(${n})">
<span>${s.name} · ${s.adm}</span><span>${s.margin!=null?s.margin.toFixed(1)+' dB ':''}<span class="tag ${s.status}">${s.status}</span></span></div>`}).join("");
if(rows.length&&!rows.includes(sel))select(rows[0]);}
function tbl(head,rows){return `<table><tr>${head.map(h=>`<th>${h}</th>`).join("")}</tr>${rows.map(r=>`<tr>${r.map(c=>`<td>${c}</td>`).join("")}</tr>`).join("")}</table>`}
function select(n){sel=n;const s=D.satellites[n];let h=`<h3>${s.name} <span class="tag ${s.status}">${s.status}</span></h3>
<div class="metrics"><div class="metric"><div class="muted">Admin</div><div class="v">${s.adm}</div></div>
<div class="metric"><div class="muted">Type</div><div class="v">${s.is_gso?'GSO':'non-GSO'}</div></div>
<div class="metric"><div class="muted">Worst margin</div><div class="v">${s.margin!=null?s.margin.toFixed(1)+' dB':'—'}</div></div></div>`;
if(s.chain){const c=s.chain;h+=`<p><b>Transparent PFD math</b> <span class="muted">(worst pair, screening)</span></p>`+
tbl(["step","value"],[["interference freq",c.freq+" MHz"],["elevation",c.elev+"°"],["slant range",c.slant.toLocaleString()+" km"],
["PFD (computed)",c.pfd+" dBW/m²"],["Article-21 limit",c.limit+" dBW/m²"],["margin",(c.margin>0?'+':'')+c.margin+" dB"]])+
`<div class="muted">source: ${c.src} · proximity: ${c.prox}</div>`;}
if(s.area){const a=s.area;h+=`<p><b>Affected part of Finland</b></p><div class="metrics">
<div class="metric"><div class="muted">Territory over limit</div><div class="v">${a.pct}%</div></div>
<div class="metric"><div class="muted">Maritime (EEZ)</div><div class="v">${a.maritime?'yes':'no'}</div><div class="muted">${a.maritime?a.pct_sea+'% of sea':''}</div></div>
<div class="metric"><div class="muted">Affected stations</div><div class="v">${a.n}</div><div class="muted">${a.n_mar?a.n_mar+' maritime':'all land'}</div></div></div>`;}
if(s.bands&&s.bands.length){h+=`<p><b>Affected Finnish bands</b></p>`+tbl(["freq (MHz)","prox","Finnish use (M4)"],s.bands.map(b=>[b[0],b[1],b[2]]));}
el("detail").innerHTML=h;renderList();drawMap(s);drawSpectrum(s);}
function seg(pairs){const x=[];pairs.forEach(p=>x.push(p[0],p[1],null));return x;}
function drawSpectrum(s){if(!s.spectrum){Plotly.purge("spectrum");return;}
const lab=dark?"#e2e8f0":"#1a202c";
const t=[{x:seg(s.spectrum.sat),y:s.spectrum.sat.flatMap(()=>[1,1,null]),mode:"lines",
line:{width:12,color:"#2b6cb0"},name:"satellite emission"},
{x:seg(s.spectrum.rx),y:s.spectrum.rx.flatMap(()=>[0,0,null]),mode:"lines",
line:{width:12,color:"#2f855a"},name:"Finnish RX channel"}];
Plotly.newPlot("spectrum",t,{height:150,margin:{l:60,r:10,t:6,b:34},
paper_bgcolor:"rgba(0,0,0,0)",plot_bgcolor:"rgba(0,0,0,0)",font:{color:lab},
yaxis:{tickvals:[0,1],ticktext:["FIN RX","sat TX"],range:[-0.6,1.6]},
xaxis:{title:"frequency (MHz)"},legend:{orientation:"h",y:1.4,font:{size:11}}},{displayModeBar:false});}
function drawMap(s){const style=dark?"carto-darkmatter":"carto-positron";const t=[];
t.push({type:"scattermap",lon:D.stations.map(p=>p[0]),lat:D.stations.map(p=>p[1]),mode:"markers",
marker:{size:4,color:"#9aa5b1"},name:"protected",hoverinfo:"skip"});
D.maritime.forEach((seg,i)=>t.push({type:"scattermap",lon:seg.map(p=>p[0]),lat:seg.map(p=>p[1]),mode:"lines",
line:{width:1,color:"#3182ce"},name:i?"":"maritime (EEZ)",showlegend:!i,hoverinfo:"skip"}));
if(s.orbit)t.push({type:"scattermap",lon:s.orbit.map(p=>p[0]),lat:s.orbit.map(p=>p[1]),mode:"lines",
line:{width:1.5,color:"#805ad5"},name:"orbit track",hoverinfo:"skip"});
if(s.affected){["land","maritime"].forEach(z=>{const a=s.affected.filter(x=>x[3]==z);if(a.length)
t.push({type:"scattermap",lon:a.map(p=>p[0]),lat:a.map(p=>p[1]),mode:"markers",
marker:{size:11,color:z=="land"?"#e53e3e":"#dd6b20"},name:"affected · "+z,
text:a.map(p=>"stn "+p[0]+"  "+p[2]+" dB"),hoverinfo:"text"});});}
Plotly.newPlot("map",t,{map:{style:style,center:{lat:64.5,lon:26},zoom:3.3},
margin:{l:0,r:0,t:0,b:0},paper_bgcolor:"rgba(0,0,0,0)",font:{color:dark?"#e2e8f0":"#1a202c"},
legend:{orientation:"h",y:-0.02}},{scrollZoom:true,displayModeBar:false});}
function toggleDark(){dark=!dark;document.body.classList.toggle("dark");if(sel){drawMap(D.satellites[sel]);drawSpectrum(D.satellites[sel]);}}
renderList();
</script></body></html>"""


if __name__ == "__main__":
    main()
