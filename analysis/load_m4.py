"""
Load the Finnish frequency allocation table (Regulation M4, pulled from the
Traficom OData API) into the project SQLite DB as table `m4_allocations`.

The OData endpoint returns everything in one page (5917 rows) under "value";
numeric band edges live in Sub_band_*__Hz_, which are what we'll use later for
frequency-overlap matching against ITU IFIC notices.

Run:  uv run python analysis/load_m4.py
"""

import json
import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "M4_Taajuusjakotaulukko.json"
DB = ROOT / "analysis" / "frequencies.db"


def main():
    rows = json.load(open(SRC))["value"]
    df = pd.DataFrame(rows)
    # convenient MHz columns alongside the raw Hz ones
    df["sub_lo_mhz"] = pd.to_numeric(df["Sub_band_lower_limit__Hz_"], errors="coerce") / 1e6
    df["sub_hi_mhz"] = pd.to_numeric(df["Sub_band_upper_limit__Hz_"], errors="coerce") / 1e6

    con = sqlite3.connect(DB)
    df.to_sql("m4_allocations", con, if_exists="replace", index=False)
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM m4_allocations").fetchone()[0]
    span = con.execute(
        "SELECT MIN(sub_lo_mhz), MAX(sub_hi_mhz) FROM m4_allocations").fetchone()
    con.close()
    print(f"Loaded {n} M4 allocation rows into m4_allocations")
    print(f"Band span: {span[0]:.6f} MHz .. {span[1]:.1f} MHz")


if __name__ == "__main__":
    main()
