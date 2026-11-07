<p align="center"><img src="Logo.svg" alt="ACT-GPT" width="320"></p>

# actgpt-traficom

**Saving Earth from Space Interferers** — an auditable, AI-assisted workflow that
monitors ITU BR IFIC satellite filings, flags the ones that could interfere with
protected Finnish radio stations, and produces a ranked, human-reviewable queue.

Built for the *Since AI Hackathon 2026 — Traficom* challenge.

> **New here? Plain-language explainer:** [`analysis/EXPLAIN.md`](analysis/EXPLAIN.md).
> **Full methodology and findings:** [`analysis/REPORT.md`](analysis/REPORT.md).
> **Abbreviations:** [`analysis/GLOSSARY.md`](analysis/GLOSSARY.md).

## Quickstart (macOS · Linux · Windows)

**1. Install `uv`** (it brings its own Python — nothing else to install):

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```
```powershell
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**2. Clone, sync, run:**
```bash
git clone https://github.com/marishiaayush/actgpt-traficom.git && cd actgpt-traficom
uv sync                                     # uv fetches Python + all deps
uv run python analysis/pipeline.py 3074     # build app.db (needs the IFIC .mdb)
uv run streamlit run dashboard.py           # open http://localhost:8501
```

Every command is `uv run …` and works the same on all three OSes.
**Full step-by-step + the one-time data download (and the Windows `mdbtools`
note): [`SETUP.md`](SETUP.md).**

## What it does — the funnel

196 satellite notices in one IFIC → a short list a human expert should actually open:

1. **Frequency overlap** — satellite downlink bands vs Finnish protected channels.
2. **Geometry** — does the satellite illuminate Finland, and at what elevation
   (GSO slot visibility / non-GSO latitude coverage)?
3. **PFD vs ITU RR Article 21** — power-flux-density link budget against the
   per-band Table 21-4 limits; worst-case screen where power data is partial.

Key design principle: **auditable triage**, not a black box. Every flag records
why it was kept (frequency, geometry, power source, margin). The human stays in
the loop.

## The app (what you demo)

A local **Streamlit dashboard** (`dashboard.py`) reads the consolidated `app.db`
and presents a two-panel review tool:

- **Pick an IFIC** (or ⬇️ download + process a new one straight from ITU).
- **Ranked shortlist** with colour-coded status (🔴 ALERT / 🟡 visible / ⚪ not
  visible / 🟣 needs data).
- **Per-satellite detail** — the transparent PFD-math chain, the **affected part
  of Finland** (land + maritime/EEZ, % over the Article-21 limit), affected
  bands vs M4, and affected protected stations.
- **Map** — zoomable, protected + affected stations (hover for detail), maritime
  (EEZ) border, over-limit area, and the SGP4 orbit ground track; a **bandwidth
  strip** shows the satellite emission vs the Finnish RX channel.
- **🧭 Bring your own receiver(s)** — score any lat/lon + RX band (land or
  maritime, one or many) against the IFIC.
- **Reviewer relabel** — human-in-the-loop: flip any satellite ALERT ↔ CLEARED
  (persisted, with an ✎ override marker).
- **🗄️ Database tab** — browse the raw tables with highlighted values; relabel.
- **🔄 ITU watch** — "Check now" for new IFIC publications, with last-checked
  provenance. **🌙 Dark mode** throughout.

A **read-only static version** (`analysis/build_static.py` → `docs/`) mirrors the
triage for free, shareable hosting (GitHub Pages / Netlify Drop).

## Data is NOT in this repo

All datasets (ITU IFIC `.mdb`, the synthetic XLSX, the M4 API JSON, derived
`.db` files) are git-ignored — download/regenerate them locally:

- **Space IFIC 3074** — ITU `demowic` portal → `ific3074.zip`
- **Terrestrial IFIC 3076** — ITU terrestrial BR IFIC page
- **M4 frequency table** — `https://opendata.traficom.fi/api/v13/Taajuusjakotaulukko`
- **Synthetic protected-stations XLSX** — Since AI platform

## Reproduce

```bash
uv sync                                   # create env from pyproject/uv.lock

# 1. convert ITU .mdb -> SQLite (needs: brew install mdbtools)
uv run python analysis/mdb_to_sqlite.py path/to/ific3074.mdb --out analysis/srs3074.db

# 2. load Finnish reference data
uv run python analysis/explore.py         # synthetic protected stations -> frequencies.db
uv run python analysis/load_m4.py         # M4 allocation table

# 3. the pipeline -- ONE entry point (consolidated backend)
uv run python analysis/pipeline.py 3074   # mdb->sqlite -> overlap -> SGP4 ->
                                          # PFD -> shortlist, all into app.db
# (or run the stages individually: freq_overlap.py, geometry_sgp4.py, pfd_score.py)

# explainers
uv run python analysis/map_interactive.py # protected-station map
uv run python analysis/pfd_explainer.py   # interactive PFD vs elevation

# 4. the dashboard (reads app.db from step 3)
uv run streamlit run dashboard.py         # two-panel triage UI in the browser

# 5. (optional) static export for sharing
uv run python analysis/build_static.py    # -> docs/index.html (read-only)
```

## Deploy / share
- **Live, full:** `uv run streamlit run dashboard.py` (local) — or **Streamlit
  Community Cloud** (free) for an online link.
- **Read-only, free, shareable:** the `docs/` static site → **GitHub Pages**
  (public repo: Settings → Pages → `main` / `docs`) or **Netlify Drop** (drag the
  `docs/` folder — works even for a private repo).

## Code map (`analysis/`)

| file | role |
|------|------|
| `explore.py` | load/clean the synthetic protected-station XLSX → SQLite + plots |
| `load_m4.py` | load the Traficom M4 allocation table |
| `pipeline.py` | **backend entry point**: run_ific() → consolidated `app.db` (publications + shortlist + results, tagged by IFIC) |
| `mdb_to_sqlite.py` | convert ITU IFIC `.mdb` → SQLite (via mdbtools) |
| `freq_overlap.py` | step 1 — satellite-vs-Finland frequency overlap |
| `pfd.py` | orbital geometry + PFD link-budget primitives |
| `geometry_sgp4.py` | Stage-2 upgrade: real SGP4 propagation (Skyfield) — time-resolved passes/coverage over Finland |
| `article21.py` | ITU RR Article 21, Table 21-4 per-band PFD limits |
| `pfd_score.py` | steps 2–3 — geometry + PFD margin, ranked triage |
| `adjacent.py` | adjacent-band guard + frequency-dependent rejection (FDR) |
| `geo.py` | Finland land + maritime (EEZ) boundaries; which part is over the limit |
| `poller.py` | ITU watch — check for new IFIC, download + convert |
| `receiver.py` | score a user-supplied receiver (land/maritime) vs the IFIC |
| `build_static.py` | render `app.db` → static `docs/` site (GitHub Pages / Netlify) |
| `score_breakdown.py` | audit trace: every number behind a flagged score, verified |
| `orbit_paths.py` | simulated SGP4 ground tracks of the flagged satellites |
| `custom_receiver.py` | interference for a fixed/offshore/**moving** (ship) receiver |
| `pfd_explainer.py`, `map_interactive.py`, `footprint_3d.py` | interactive explainer figures |

Top level: **`dashboard.py`** (Streamlit app). Figures live in `analysis/plots/`;
Finland boundaries in `analysis/data/`.
