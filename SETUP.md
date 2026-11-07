# Setup — clone, run, analyse

Everything runs locally on a laptop. The **datasets are not in the repo**
(they're large / third-party), so there's a one-time data step.

## 1. Prerequisites

- **[uv](https://docs.astral.sh/uv/)** (Python env + runner):
  `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **mdbtools** (to read ITU MS-Access `.mdb` on macOS/Linux):
  macOS `brew install mdbtools` · Debian/Ubuntu `sudo apt-get install mdbtools`
- Internet (for the ITU downloads, the M4 API, and the dashboard's map tiles).

## 2. Clone + environment

```bash
git clone https://github.com/marishiaayush/actgpt-traficom.git
cd actgpt-traficom
uv sync                      # creates .venv from pyproject/uv.lock
```

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
