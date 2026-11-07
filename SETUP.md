# Setup — clone, run, analyse

Everything runs locally on a laptop. The **datasets are not in the repo**
(they're large / third-party), so there's a one-time data step.

## 1. Prerequisites

### a) uv — the only thing you install by hand (handles Python + deps)

**macOS / Linux** (Terminal):
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```
**Windows** (PowerShell):
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```
Then restart the terminal and check: `uv --version`. uv installs the right
Python itself — you don't need Python pre-installed.

### b) mdbtools — only for converting the ITU `.mdb` (one-time step)

| OS | Install |
|----|---------|
| **macOS** | `brew install mdbtools` |
| **Linux** | `sudo apt-get install mdbtools` |
| **Windows** | mdbtools is Linux/mac only. Easiest: run the **conversion step** (3→4) inside **WSL** (`wsl --install`, then `sudo apt-get install mdbtools` and follow the Linux commands). Everything else — `uv`, the pipeline, the dashboard — runs **natively on Windows**. |

- Internet is needed (ITU downloads, the M4 API, the dashboard's map tiles).

## 2. Clone + environment  (same on macOS / Linux / Windows)

```bash
git clone https://github.com/marishiaayush/actgpt-traficom.git
cd actgpt-traficom
uv sync                      # uv fetches Python + all deps into .venv
```

All later commands start with `uv run …`, which works identically on every OS
(no manual venv activation needed).

## 3. Get the data (one-time)

| Dataset | How | Put it at |
|---|---|---|
| **Space IFIC 3074** (`.mdb`) | ITU demowic → 2026 → IFIC 3074 → unzip | `analysis/ific3074.mdb` |
| **Synthetic protected stations** (XLSX) | Since AI platform | repo root (`Traficom_SinceAI_..._v05112026.xlsx`) |
| **M4 frequency table** | fetched automatically (Traficom API) | — |

```bash
# Finnish reference data (protected stations + M4 allocation table)
uv run python analysis/explore.py          # XLSX -> analysis/frequencies.db
uv run python analysis/load_m4.py          # M4 API -> frequencies.db

# optional: terrestrial side quest
# download Terrestrial IFIC 3076 from the ITU terrestrial BR IFIC page
```

*(The dashboard can also download + process a new IFIC itself — see ITU watch
below — so step 3's IFIC download is only needed to seed the first run.)*

## 4. Run the analysis (one command)

```bash
uv run python analysis/pipeline.py 3074    # mdb -> sqlite -> overlap -> SGP4 ->
                                           # PFD -> shortlist, all into app.db
```

Builds `analysis/app.db` (publications + shortlist + results). Re-run with any
IFIC number whose `.mdb` is present.

## 5. Launch the dashboard

```bash
uv run streamlit run dashboard.py          # opens http://localhost:8501
```

- **🛰️ Triage tab** — pick an IFIC, read the ranked shortlist, per-satellite PFD
  math, affected part of Finland (land + maritime), map, bandwidth view.
  **Relabel** any satellite (✅ Clear / 🔴 Flag ALERT / ↩️ Reset) — persisted.
- **🗄️ Database tab** — browse the raw tables with highlighted values; relabel
  from here too.
- **🔄 ITU watch** (sidebar) — "Check now" for new IFIC publications and
  **download + process** them in-app.
- **🧭 Bring your own receiver** — score any lat/lon + RX band (land or maritime).

## Swap in your own protected-station list

The protected stations (the "antennae to protect") come from one workbook. To
replace the whole list with your own — even a huge one — just point `explore.py`
at it and rebuild:

```bash
# 1. rebuild the Finnish reference from YOUR workbook (any path / filename)
uv run python analysis/explore.py /path/to/your_stations.xlsx
#    (or: export STATIONS_XLSX=/path/to/your_stations.xlsx)

# 2. re-run the pipeline so the triage uses the new stations
uv run python analysis/pipeline.py 3074     # repeat for other processed IFICs
```

Refresh the dashboard — the shortlist, maps, and PFD now reflect the new list.

**Requirements for the new workbook:**
- **Same column ORDER** as the reference (parsing is positional: station no,
  licence class, lon, lat, ground/mast height, mast type, channel bw, TX freq,
  RX freq, ant heights, gain, emission, tx bw, direction, polarisation, power,
  power unit, …). Column *names* and any preamble rows don't matter — the data
  start row is auto-detected.
- **WGS84** lon/lat; frequencies like `"87.900 MHz"` / `"300k"`; power with a
  unit column (`W` / `kW` / `mW`).

Scale: the loader + frequency-overlap are indexed, so a very large list is fine;
the pipeline's per-notice geometry/PFD don't grow with station count.

## 6. Share a read-only demo (no server, free)

```bash
uv run python analysis/build_static.py     # -> docs/index.html
```

Host `docs/` on **GitHub Pages** (public repo: Settings → Pages → `main`/`docs`)
or drag the folder to **[Netlify Drop](https://app.netlify.com/drop)** (works
with a private repo).

## Troubleshooting

- **Dashboard says "No processed publications"** → run step 4 (`pipeline.py`).
- **`mdb-tables: command not found`** → install mdbtools (step 1).
- **Map is blank** → carto basemap tiles need internet; the overlays still draw.
- **Sidebar missing** → it may have collapsed; use the `›` arrow top-left (it's
  forced open by default now).

See [`analysis/EXPLAIN.md`](analysis/EXPLAIN.md) for the plain-language overview
and [`analysis/REPORT.md`](analysis/REPORT.md) for the full methodology.
