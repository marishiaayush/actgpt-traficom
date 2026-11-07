# actgpt-traficom

**Saving Earth from Space Interferers** — an auditable, AI-assisted workflow that
monitors ITU BR IFIC satellite filings, flags the ones that could interfere with
protected Finnish radio stations, and produces a ranked, human-reviewable queue.

Built for the *Since AI Hackathon 2026 — Traficom* challenge.

> **Full methodology and findings:** see [`analysis/REPORT.md`](analysis/REPORT.md).
> **Abbreviations:** [`analysis/GLOSSARY.md`](analysis/GLOSSARY.md).

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

# 3. the pipeline
uv run python analysis/freq_overlap.py    # step 1: frequency overlap
uv run python analysis/pfd_score.py       # steps 2-3: geometry + PFD triage

# explainers
uv run python analysis/map_interactive.py # protected-station map
uv run python analysis/pfd_explainer.py   # interactive PFD vs elevation
```

## Code map (`analysis/`)

| file | role |
|------|------|
| `explore.py` | load/clean the synthetic protected-station XLSX → SQLite + plots |
| `load_m4.py` | load the Traficom M4 allocation table |
| `mdb_to_sqlite.py` | convert ITU IFIC `.mdb` → SQLite (via mdbtools) |
| `freq_overlap.py` | step 1 — satellite-vs-Finland frequency overlap |
| `pfd.py` | orbital geometry + PFD link-budget primitives |
| `article21.py` | ITU RR Article 21, Table 21-4 per-band PFD limits |
| `pfd_score.py` | steps 2–3 — geometry + PFD margin, ranked triage |
| `adjacent.py` | adjacent-band guard + frequency-dependent rejection (FDR) |
| `pfd_explainer.py`, `map_interactive.py` | interactive explainer figures |
| `footprint_3d.py` | 3D visibility-cone footprints of flagged satellites over Finland |

Figures live in `analysis/plots/`.
