"""
Convert ITU BR IFIC MS-Access .mdb file(s) into a single SQLite .db on macOS,
without MS Access or the Windows-only ITU tools (SpaceQry/TerRaQ).

Uses `mdbtools` (install once:  brew install mdbtools).

The space SRS database is split into srsNNNN_part1of2.mdb + _part2of2.mdb; the
two files hold DIFFERENT physical tables, so just pass BOTH and they merge into
one .db. (mdbtools reads each file's own tables; it ignores the Access-internal
links between the parts, which we don't need.)

Examples:
  uv run python analysis/mdb_to_sqlite.py path/to/srs3074_part1of2.mdb \
      path/to/srs3074_part2of2.mdb --out analysis/srs3074.db
  uv run python analysis/mdb_to_sqlite.py path/to/terrestrial_3076.mdb \
      --out analysis/ter3076.db
"""

import argparse
import io
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pandas as pd


def have_mdbtools():
    return shutil.which("mdb-tables") and shutil.which("mdb-export")


def list_tables(mdb):
    out = subprocess.run(["mdb-tables", "-1", str(mdb)],
                         capture_output=True, text=True, check=True).stdout
    return [t for t in out.splitlines() if t.strip()]


def export_table(mdb, table):
    # CSV to stdout; let pandas infer types. mdbtools quotes text fields.
    csv = subprocess.run(
        ["mdb-export", "-D", "%Y-%m-%d %H:%M:%S", str(mdb), table],
        capture_output=True, text=True, check=True).stdout
    if not csv.strip():
        return None
    try:
        return pd.read_csv(io.StringIO(csv), low_memory=False)
    except Exception as e:
        print(f"    ! could not parse {table}: {e}")
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mdb", nargs="+", help="one or more .mdb files")
    ap.add_argument("--out", required=True, help="output SQLite .db path")
    args = ap.parse_args()

    if not have_mdbtools():
        sys.exit("mdbtools not found. Install it first:  brew install mdbtools")

    out = Path(args.out)
    if out.exists():
        out.unlink()
    con = sqlite3.connect(out)

    total_tables = 0
    total_rows = 0
    for mdb_path in args.mdb:
        mdb = Path(mdb_path)
        if not mdb.exists():
            print(f"SKIP (missing): {mdb}")
            continue
        print(f"\n=== {mdb.name} ===")
        for table in list_tables(mdb):
            df = export_table(mdb, table)
            if df is None or df.empty:
                print(f"  - {table:30s} (empty, skipped)")
                continue
            # if a table name appears in both parts, keep the larger one
            existing = con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,)).fetchone()
            if existing:
                have = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                if len(df) <= have:
                    print(f"  - {table:30s} (dup, kept existing {have} rows)")
                    continue
            df.to_sql(table, con, if_exists="replace", index=False)
            total_tables += 1
            total_rows += len(df)
            print(f"  + {table:30s} {len(df):>8d} rows  ({len(df.columns)} cols)")
    con.commit()
    con.close()
    print(f"\nDone. {total_tables} tables, {total_rows} rows -> {out}")
    print("Next: open it and look for the notice / frequency / orbital tables.")


if __name__ == "__main__":
    main()
