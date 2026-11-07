"""
Exploratory analysis of the Traficom "Frequencies of interest" synthetic dataset.

What this does, in order:
  1. Load the XLSX (skipping the preamble; real header is on the English row).
  2. Clean/parse the messy string columns into numeric, analysis-ready columns.
  3. Flag the known data-quality issues the dataset note warns about.
  4. Write a tidy table to a SQLite .db (fast to query / dashboard later).
  5. Generate overview + geographic plots.
  6. Print a plain-language summary so we understand what we're looking at.

Run:  python3 analysis/explore.py
"""

from pathlib import Path
import math
import re
import sqlite3

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
XLSX = ROOT / "Traficom_SinceAI_Frequencies_of_interest_v05112026.xlsx"
DB = ROOT / "analysis" / "frequencies.db"
PLOTS = ROOT / "analysis" / "plots"
PLOTS.mkdir(parents=True, exist_ok=True)

# Finland rough bounding box (WGS84) used only to flag out-of-country points.
FIN_LON = (19.0, 32.0)
FIN_LAT = (59.5, 70.1)

# Radiated power above this is physically impossible for a terrestrial
# station and marks the synthetic gigawatt artifact (see flag_bogus_power).
POWER_CEILING_DBW = 70.0  # 70 dBW = 10 MW

# The English header is on sheet row 11 (0-indexed 10); data starts row 13 (idx 12).
HEADER_ROW = 10
FIRST_DATA_ROW = 12

COLS = [
    "station_no", "licence_class", "lon", "lat", "ground_height_m",
    "mast_height_m", "mast_type", "channel_bw_raw", "tx_freq_raw", "rx_freq_raw",
    "ant_h_agl_m", "ant_h_asl_m", "ant_gain_db", "emission_class",
    "tx_bw_raw", "radiation_dir_deg", "polarisation", "power_val",
    "power_val_itu", "power_unit", "tx_line_db", "directivity",
]


def parse_hz(s):
    """'87.900 MHz' / '300k' / '2.4 GHz' -> value in MHz (float) or NaN."""
    if s is None:
        return np.nan
    t = str(s).strip().replace(",", ".")
    if not t:
        return np.nan
    m = re.match(r"^([\d.]+)\s*([kKmMgG]?)[Hh]?[Zz]?$", t)
    if not m:
        return np.nan
    val = float(m.group(1))
    scale = {"": 1e-6, "k": 1e-3, "m": 1.0, "g": 1e3}[m.group(2).lower()]
    return val * scale  # MHz


def power_to_watts(val, unit):
    if pd.isna(val) or unit is None or str(unit).strip() == "":
        return np.nan
    factor = {"mW": 1e-3, "W": 1.0, "kW": 1e3}.get(str(unit).strip())
    return float(val) * factor if factor else np.nan


def band_label(mhz):
    if pd.isna(mhz):
        return "unknown"
    if mhz < 30:
        return "HF (<30 MHz)"
    if mhz < 300:
        return "VHF (30-300 MHz)"
    if mhz < 3000:
        return "UHF (0.3-3 GHz)"
    if mhz < 30000:
        return "SHF (3-30 GHz)"
    return "EHF (>30 GHz)"


def load():
    raw = pd.read_excel(XLSX, header=None, skiprows=FIRST_DATA_ROW)
    raw = raw.iloc[:, : len(COLS)]
    raw.columns = COLS
    df = raw[raw["station_no"].notna()].copy()

    # numeric coercions
    for c in ["lon", "lat", "ground_height_m", "mast_height_m", "ant_h_agl_m",
              "ant_h_asl_m", "ant_gain_db", "radiation_dir_deg", "power_val",
              "tx_line_db", "station_no"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # parsed physical quantities
    df["tx_freq_mhz"] = df["tx_freq_raw"].map(parse_hz)
    df["rx_freq_mhz"] = df["rx_freq_raw"].map(parse_hz)
    df["channel_bw_mhz"] = df["channel_bw_raw"].map(parse_hz)
    df["tx_bw_mhz"] = df["tx_bw_raw"].map(parse_hz)
    df["band"] = df["tx_freq_mhz"].map(band_label)
    df["power_w"] = df.apply(lambda r: power_to_watts(r["power_val"], r["power_unit"]), axis=1)
    df["power_dbw"] = df["power_w"].map(lambda w: 10 * math.log10(w) if w and w > 0 else np.nan)
    # crude EIRP estimate where gain is known (dBW): P + gain - feed loss
    df["eirp_dbw"] = (df["power_dbw"]
                      + df["ant_gain_db"].fillna(0)
                      - df["tx_line_db"].fillna(0))

    # ---- data-quality flags (per the dataset's own caveats) ----
    df["flag_out_of_finland"] = ~(
        df["lon"].between(*FIN_LON) & df["lat"].between(*FIN_LAT))
    # antenna above sea level lower than ground height => impossible (buried)
    df["flag_ant_below_ground"] = (
        df["ant_h_asl_m"].notna()
        & (df["ant_h_asl_m"] < df["ground_height_m"]))
    df["flag_missing_freq"] = df["tx_freq_mhz"].isna()
    df["flag_missing_power"] = df["power_w"].isna()

    # Quarantine bogus radiated power.
    # A coherent subgroup (blank licence class, SHF digital D7W microwave
    # point-to-point links) carries gigawatt-scale power values that are a
    # synthetic-generation artifact: the real population tops out ~49 dBW,
    # the bogus one starts ~81 dBW, with a clean gap between. Terrestrial
    # radiated power above POWER_CEILING_DBW (70 dBW = 10 MW) is impossible,
    # so we null the power there while KEEPING the station (freq/location are
    # valid protected spectrum).
    df["flag_bogus_power"] = df["power_dbw"] > POWER_CEILING_DBW
    df["power_valid"] = df["power_w"].notna() & ~df["flag_bogus_power"]
    for c in ["power_w", "power_dbw", "eirp_dbw"]:
        df.loc[df["flag_bogus_power"], c] = np.nan
    return df


def write_db(df):
    con = sqlite3.connect(DB)
    df.to_sql("frequencies", con, if_exists="replace", index=False)
    # Analysis-ready view: every station, but power already nulled where it
    # was the gigawatt artifact, so power aggregates are safe to run directly.
    con.execute("DROP VIEW IF EXISTS v_clean")
    con.execute("""
        CREATE VIEW v_clean AS
        SELECT station_no, licence_class, lon, lat, band,
               tx_freq_mhz, rx_freq_mhz, channel_bw_mhz,
               power_w, power_dbw, eirp_dbw, power_valid, ant_gain_db,
               ant_h_agl_m, ant_h_asl_m, radiation_dir_deg, polarisation
        FROM frequencies
    """)
    # Quarantine view: the rows whose power was rejected, with the original
    # bogus value kept visible for audit/transparency.
    con.execute("DROP VIEW IF EXISTS v_quarantine")
    con.execute("""
        CREATE VIEW v_quarantine AS
        SELECT station_no, licence_class, band, tx_freq_mhz, rx_freq_mhz,
               emission_class, power_val AS bogus_power_raw, power_unit
        FROM frequencies
        WHERE flag_bogus_power = 1
    """)
    con.commit()
    con.close()


def plots(df):
    # 1) overview panel
    fig, ax = plt.subplots(2, 2, figsize=(13, 9))

    order = ["HF (<30 MHz)", "VHF (30-300 MHz)", "UHF (0.3-3 GHz)",
             "SHF (3-30 GHz)", "EHF (>30 MHz)", "unknown"]
    bc = df["band"].value_counts().reindex([b for b in order if b in df["band"].values]).dropna()
    ax[0, 0].bar(range(len(bc)), bc.values, color="#2b6cb0")
    ax[0, 0].set_xticks(range(len(bc)))
    ax[0, 0].set_xticklabels(bc.index, rotation=25, ha="right", fontsize=8)
    ax[0, 0].set_title("Stations by frequency band")
    ax[0, 0].set_ylabel("count")

    lc = df["licence_class"].fillna("(blank)").value_counts()
    ax[0, 1].barh(range(len(lc)), lc.values, color="#2f855a")
    ax[0, 1].set_yticks(range(len(lc)))
    ax[0, 1].set_yticklabels(lc.index, fontsize=8)
    ax[0, 1].invert_yaxis()
    ax[0, 1].set_title("Stations by class of licence")

    f = df["tx_freq_mhz"].dropna()
    ax[1, 0].hist(f, bins=60, color="#6b46c1")
    ax[1, 0].set_yscale("log")
    ax[1, 0].set_title("TX frequency distribution")
    ax[1, 0].set_xlabel("MHz"); ax[1, 0].set_ylabel("count (log)")

    p = df["power_dbw"].dropna()
    ax[1, 1].hist(p, bins=40, color="#c05621")
    ax[1, 1].set_title("Radiated power distribution")
    ax[1, 1].set_xlabel("dBW"); ax[1, 1].set_ylabel("count")

    fig.suptitle("Traficom frequencies of interest - overview", fontsize=14)
    fig.tight_layout()
    fig.savefig(PLOTS / "overview.png", dpi=130)
    plt.close(fig)

    # 2) geographic map coloured by band, out-of-box points marked
    fig, ax = plt.subplots(figsize=(7, 10))
    inside = df[~df["flag_out_of_finland"]]
    outside = df[df["flag_out_of_finland"] & df["lon"].notna()]
    bands = [b for b in order if b in inside["band"].values]
    cmap = plt.get_cmap("tab10")
    for i, b in enumerate(bands):
        s = inside[inside["band"] == b]
        ax.scatter(s["lon"], s["lat"], s=14, color=cmap(i), label=b, alpha=0.75)
    if len(outside):
        ax.scatter(outside["lon"], outside["lat"], s=30, marker="x",
                   color="red", label=f"outside FIN box ({len(outside)})")
    ax.axvline(FIN_LON[0], ls=":", c="grey"); ax.axvline(FIN_LON[1], ls=":", c="grey")
    ax.axhline(FIN_LAT[0], ls=":", c="grey"); ax.axhline(FIN_LAT[1], ls=":", c="grey")
    ax.set_title("Station locations (WGS84)")
    ax.set_xlabel("longitude"); ax.set_ylabel("latitude")
    ax.legend(fontsize=7, loc="lower right")
    fig.tight_layout()
    fig.savefig(PLOTS / "map.png", dpi=130)
    plt.close(fig)


def report(df):
    n = len(df)
    print(f"\n{'='*60}\nDATASET SUMMARY  ({n} station records)\n{'='*60}")
    print("\nFrequency bands:")
    print(df["band"].value_counts().to_string())
    print("\nLicence classes:")
    print(df["licence_class"].fillna("(blank)").value_counts().to_string())
    print(f"\nTX frequency span: {df['tx_freq_mhz'].min():.3f} - "
          f"{df['tx_freq_mhz'].max():.1f} MHz")
    print(f"Power known for {df['power_w'].notna().sum()}/{n} rows; "
          f"range {df['power_dbw'].min():.1f} .. {df['power_dbw'].max():.1f} dBW")
    print(f"Power VALID (after quarantine) for {int(df['power_valid'].sum())}/{n} rows")
    print("\n--- DATA QUALITY FLAGS ---")
    for col, desc in [
        ("flag_bogus_power", "QUARANTINED: gigawatt power artifact (power nulled)"),
        ("flag_missing_power", "radiated power missing (no value/unit)"),
        ("flag_out_of_finland", "coordinates outside Finland bounding box"),
        ("flag_ant_below_ground", "antenna ASL below ground height (impossible)"),
        ("flag_missing_freq", "TX frequency missing/unparseable"),
    ]:
        print(f"  {int(df[col].sum()):4d}  {desc}")
    print(f"\nWrote SQLite DB -> {DB}")
    print(f"Wrote plots     -> {PLOTS}/overview.png, map.png\n")


if __name__ == "__main__":
    df = load()
    write_db(df)
    plots(df)
    report(df)
