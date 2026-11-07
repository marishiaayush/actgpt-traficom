"""
Phase 3 -- ITU IFIC watcher.

"Check now" polling (the user chose a button + provenance over a daemon): fetch
the ITU demowic index, diff the available IFIC numbers against what we've
already processed (the publications table), and record a last-checked
timestamp. Also downloads + converts a new IFIC's .mdb so pipeline.run_ific()
can process it.

All network calls are best-effort and fail soft (offline -> empty result).
"""

import io
import re
import sqlite3
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

A = Path(__file__).resolve().parent
APP_DB = A / "app.db"
DEMOWIC = "https://www.itu.int/sns/wic/demowic{yy}.html"
YEARS = [26, 25]                       # recent year pages to scan
UA = {"User-Agent": "actgpt-traficom/1.0"}


def _fetch(url, timeout=30):
    return urllib.request.urlopen(
        urllib.request.Request(url, headers=UA), timeout=timeout).read()


def report_url(ific):
    """Direct ITU download for a space IFIC package (verified pattern)."""
    return f"https://www.itu.int/sns/ific10/ific{int(ific)}.zip"


def available_ifics(years=YEARS):
    """{ific_no: zip_url} of space IFICs currently published on ITU."""
    out = {}
    for yy in years:
        page = DEMOWIC.format(yy=yy)
        try:
            html = _fetch(page).decode("latin-1", "ignore")
        except Exception:
            continue
        for href in re.findall(r'href="([^"]*ific\d+\.zip)"', html, re.I):
            m = re.search(r"ific(\d+)\.zip", href)
            if m:
                out[int(m.group(1))] = urljoin(page, href)
    return out


# ---- app_meta provenance ----
def _meta(key, value=None):
    con = sqlite3.connect(APP_DB)
    con.execute("CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT)")
    if value is not None:
        con.execute("INSERT OR REPLACE INTO app_meta VALUES (?,?)", (key, value))
        con.commit()
        r = value
    else:
        row = con.execute("SELECT value FROM app_meta WHERE key=?", (key,)).fetchone()
        r = row[0] if row else None
    con.close()
    return r


def last_checked():
    return _meta("last_checked")


def processed_ifics():
    con = sqlite3.connect(APP_DB)
    try:
        return {int(r[0]) for r in con.execute("SELECT ific_no FROM publications")}
    except Exception:
        return set()
    finally:
        con.close()


def check_itu():
    """Poll ITU, record last_checked, return availability + what's NEW."""
    av = available_ifics()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _meta("last_checked", now)
    if av:
        _meta("last_available", ",".join(map(str, sorted(av))))
    proc = processed_ifics()
    return dict(last_checked=now, available=sorted(av),
                processed=sorted(proc), new=sorted(n for n in av if n not in proc),
                urls=av, ok=bool(av))


def download_mdb(ific, url=None, timeout=180):
    """Download + unzip an IFIC, write its .mdb as analysis/ific{N}.mdb."""
    url = url or report_url(ific)
    zf = zipfile.ZipFile(io.BytesIO(_fetch(url, timeout=timeout)))
    mdbs = [n for n in zf.namelist() if n.lower().endswith(".mdb")]
    if not mdbs:
        raise RuntimeError(f"no .mdb inside {url}")
    biggest = max(mdbs, key=lambda n: zf.getinfo(n).file_size)
    out = A / f"ific{int(ific)}.mdb"
    out.write_bytes(zf.read(biggest))
    return out


if __name__ == "__main__":
    r = check_itu()
    print("last_checked:", r["last_checked"])
    print(f"available: {len(r['available'])}  processed: {r['processed']}")
    print("NEW (unprocessed):", r["new"][:10], "..." if len(r["new"]) > 10 else "")
