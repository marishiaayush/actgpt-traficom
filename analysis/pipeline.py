"""
Phase 0 -- backend consolidation. ONE entry point that turns an IFIC into a
reviewable shortlist, and writes everything to a single lean SQLite db (app.db)
that the dashboard reads.

    run_ific(ific_no, mdb_path=None, country="FIN")
      1. convert the IFIC .mdb -> srs{ific}.db   (cached; skipped if present)
      2. run the pipeline on it (freq_overlap -> geometry_sgp4 -> pfd_score),
         pointed at that db via the SRS_DB env var
      3. consolidate results + reference + a per-notice SHORTLIST into app.db,
         tagged by ific_no so many publications coexist
      4. upsert a `publications` registry row

The heavy, per-IFIC artefacts (srs{ific}.db) stay on disk for drill-down; the
dashboard only needs app.db.

CLI:  uv run python analysis/pipeline.py 3074
"""

import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

A = Path(__file__).resolve().parent
ROOT = A.parent
APP_DB = A / "app.db"
FIN_DB = A / "frequencies.db"


# --------------------------------------------------------------------------
# db helpers
# --------------------------------------------------------------------------
def srs_db(ific):
    return A / f"srs{ific}.db"


def upsert_by_ific(app, table, df, ific):
    """Replace this IFIC's rows in `table` (create the table if new)."""
    df = df.copy()
    df.insert(0, "ific_no", int(ific))
    exists = app.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,)).fetchone()
    if exists:
        app.execute(f'DELETE FROM "{table}" WHERE ific_no=?', (int(ific),))
        app.commit()
    df.to_sql(table, app, if_exists="append", index=False)


def ensure_base_tables(app):
    app.executescript("""
    CREATE TABLE IF NOT EXISTS publications (
        ific_no INTEGER PRIMARY KEY, service_type TEXT, country TEXT,
        status TEXT, n_notices INTEGER, n_shortlist INTEGER, n_alerts INTEGER,
        mdb_path TEXT, pdf_url TEXT, processed_at TEXT);
    CREATE TABLE IF NOT EXISTS country_config (
        code TEXT PRIMARY KEY, name TEXT, allocation_table TEXT,
        pfd_criterion TEXT, boundary_geojson TEXT);
    CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT);
    """)
    app.execute("""INSERT OR REPLACE INTO country_config VALUES
        ('FIN','Finland','m4_allocations','RR Article 21 Table 21-4', NULL)""")
    app.commit()


# --------------------------------------------------------------------------
# steps
# --------------------------------------------------------------------------
def ensure_converted(ific, mdb_path):
    db = srs_db(ific)
    if db.exists():
        print(f"[pipeline] srs{ific}.db present -> skip conversion")
        return db
    if not mdb_path or not Path(mdb_path).exists():
        raise SystemExit(f"[pipeline] need the IFIC .mdb to build srs{ific}.db "
                         f"(pass mdb_path; looked for {mdb_path})")
    print(f"[pipeline] converting {mdb_path} -> srs{ific}.db ...")
    subprocess.run([sys.executable, str(A / "mdb_to_sqlite.py"),
                    str(mdb_path), "--out", str(db)], check=True)
    return db


def run_analysis(ific):
    env = {**os.environ, "SRS_DB": str(srs_db(ific)), "FIN_DB": str(FIN_DB)}
    for script in ("freq_overlap.py", "geometry_sgp4.py", "pfd_score.py"):
        print(f"[pipeline] running {script} on srs{ific}.db ...")
        subprocess.run([sys.executable, str(A / script)], check=True, env=env)


def build_shortlist(srs):
    """One row per satellite notice: the reviewer's ranked worklist."""
    sc = pd.read_sql("SELECT * FROM fin_pfd_score", srs)
    ov = pd.read_sql("SELECT sat_ntc_id, COUNT(DISTINCT ROUND(sat_lo_mhz,3)||'-'"
                     "||ROUND(sat_hi_mhz,3)) n_bands FROM fin_freq_overlap "
                     "GROUP BY sat_ntc_id", srs)
    names_g = pd.read_sql("SELECT ntc_id, sat_name FROM non_geo", srs)
    names_s = pd.read_sql("SELECT ntc_id, sat_name FROM geo", srs)
    names = pd.concat([names_g, names_s]).drop_duplicates("ntc_id")
    adm = pd.read_sql("SELECT ntc_id, adm FROM notice", srs).drop_duplicates("ntc_id")

    g = sc.groupby("sat_ntc_id")
    sl = pd.DataFrame({
        "worst_margin_db": g.apply(lambda d: d.loc[d.status == "scored", "margin"].max()
                                   if (d.status == "scored").any() else None),
        "alert_pairs": g.apply(lambda d: int(((d.status == "scored") & (d.margin > 0)).sum())),
        "alert_stations": g.apply(lambda d: d.loc[(d.status == "scored") & (d.margin > 0),
                                                  "station_no"].nunique()),
        "is_gso": g["is_gso"].max(),
        "statuses": g["status"].apply(lambda s: ",".join(sorted(set(s)))),
    }).reset_index()
    sl = (sl.merge(ov, on="sat_ntc_id", how="left")
            .merge(names, left_on="sat_ntc_id", right_on="ntc_id", how="left")
            .merge(adm, left_on="sat_ntc_id", right_on="ntc_id", how="left"))
    sl["review_status"] = sl.apply(
        lambda r: "ALERT" if r.alert_pairs > 0 else
                  ("visible" if "scored" in r.statuses else
                   ("not_visible" if "not_visible" in r.statuses or
                    "not_visible_sgp4" in r.statuses else "needs_data")), axis=1)
    # rank: alerts first (by worst margin), then visible, then rest
    order = {"ALERT": 0, "visible": 1, "needs_data": 2, "not_visible": 3}
    sl["_o"] = sl.review_status.map(order)
    sl = sl.sort_values(["_o", "worst_margin_db"], ascending=[True, False])
    return sl[["sat_ntc_id", "adm", "sat_name", "is_gso", "review_status",
               "worst_margin_db", "alert_pairs", "alert_stations", "n_bands"]]


def consolidate(ific, country, mdb_path):
    srs = sqlite3.connect(srs_db(ific))
    app = sqlite3.connect(APP_DB)
    ensure_base_tables(app)

    # per-IFIC result tables
    for t in ("fin_freq_overlap", "fin_geom_sgp4", "fin_pfd_score"):
        upsert_by_ific(app, t, pd.read_sql(f"SELECT * FROM {t}", srs), ific)
    shortlist = build_shortlist(srs)
    upsert_by_ific(app, "shortlist", shortlist, ific)

    # country reference (same across IFICs; refresh each run is fine)
    fin = sqlite3.connect(FIN_DB)
    pd.read_sql("SELECT * FROM v_clean", fin).to_sql(
        "protected_stations", app, if_exists="replace", index=False)
    pd.read_sql("SELECT * FROM m4_allocations", fin).to_sql(
        "m4_allocations", app, if_exists="replace", index=False)
    fin.close()

    n_notices = pd.read_sql("SELECT COUNT(*) n FROM notice", srs).n[0]
    srs.close()
    app.execute("""INSERT OR REPLACE INTO publications VALUES
        (?,?,?,?,?,?,?,?,?,?)""", (
        int(ific), "space", country, "processed", int(n_notices),
        int(len(shortlist)), int((shortlist.review_status == "ALERT").sum()),
        str(mdb_path) if mdb_path else None,
        f"https://www.itu.int/sns/wic/demowic.html  (IFIC {ific})",
        datetime.now(timezone.utc).isoformat(timespec="seconds")))
    app.commit()
    app.close()
    return shortlist


def run_ific(ific, mdb_path=None, country="FIN"):
    ific = int(ific)
    if mdb_path is None:
        guess = A / f"ific{ific}.mdb"
        mdb_path = guess if guess.exists() else None
    t0 = time.time()
    ensure_converted(ific, mdb_path)
    run_analysis(ific)
    sl = consolidate(ific, country, mdb_path)
    print(f"\n[pipeline] IFIC {ific} done in {time.time()-t0:.0f}s -> {APP_DB.name}")
    print(f"  notices shortlisted: {len(sl)}   "
          f"ALERTs: {(sl.review_status=='ALERT').sum()}")
    print("\n  top of shortlist:")
    print(sl.head(8).to_string(index=False))
    return sl


if __name__ == "__main__":
    ific = int(sys.argv[1]) if len(sys.argv) > 1 else 3074
    run_ific(ific)
