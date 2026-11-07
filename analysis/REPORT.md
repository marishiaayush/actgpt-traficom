# Dataset primer — Traficom "Frequencies of interest" (synthetic)

*Working notes, updated 2026-11-07. Source: `Traficom_SinceAI_Frequencies_of_interest_v05112026.xlsx` (874 records).*
*Abbreviations: see [`GLOSSARY.md`](GLOSSARY.md).*

## 1. What this dataset actually is

It is a list of **terrestrial radio stations located inside Finland that must be
protected** from interference. These are the **victims**, not the threats:

- The coordinates (WGS84 lon/lat) are **ground locations in Finland** — the map
  draws a recognizable Finland.
- The challenge is to flag when a **satellite** (from ITU space IFIC) or a
  **foreign terrestrial station** (from ITU terrestrial IFIC) would transmit on
  the same/adjacent frequency over or near Finland and raise the power level at
  one of these protected stations above a permitted limit.

**These are NOT satellites.** There are no orbital slots, no coverage cones, no
PFD footprints in this file. Those live in the ITU IFIC `.mdb` databases we have
not loaded yet. The only "direction" a ground station has is its **antenna
azimuth + directivity** (which way a fixed link points) — the terrestrial analog
of a satellite's coverage.

So: a **2D map of Finland** is the correct view for this dataset. A **3D globe**
only becomes meaningful once we add the satellite side (to show which orbital
arc / footprint overlaps Finland).

## 2. Problem concepts (read this before the IFIC step)

### Why this problem exists
Satellites are **filed at the ITU before launch** (advance publication "API/A",
then coordination "CR/C"), often months to years ahead. Once a satellite is up
and radiating you cannot recall it, so the only real leverage is **during the
ITU paper process**: object / coordinate early. The number of filings is
**exploding** (mega-constellations = tens of thousands of objects), so manual
expert review no longer scales. The deliverable is therefore an
**assisted-triage system**: auto-rank the filings, surface the few that a human
expert should actually review, and show the evidence. Human stays in the loop;
everything must be auditable.

### TX vs RX
- **TX frequency** = what a station transmits on; **RX frequency** = what it
  listens on.
- A **fixed link (FX)** is two towers talking point-to-point using **paired
  frequencies** (frequency-division duplex): tower A transmits on f1 / receives
  on f2, tower B does the reverse. That is why FX rows show **TX != RX with a
  fixed duplex spacing**. Broadcast (BC) is one-way, so TX == RX.
- **Why it matters:** the thing that gets interfered with is a **receiver**, so
  the protected frequency is the victim's **RX** frequency, and the geometry
  that matters is where that receiver's antenna is *looking*. A satellite
  transmitting *down* onto a Finnish receiver's RX band is the classic threat.

### FX = the Fixed Service
Licensed point-to-point microwave links (telecom backhaul). Narrow dish
antennas pointed at the **horizon** toward the partner tower.

### Why antenna azimuth is NOT a standalone interference filter
A tempting shortcut is "the antenna points at azimuth X, so just flag
satellites in direction X." Azimuth is a useful *discriminator*, but it does not
*decide* interference, for five reasons:

1. **Elevation matters more than azimuth.** Fixed links point at the horizon
   (elevation ~ 0 deg); satellites are *up*. At Finland's high latitude, **GSO
   satellites sit low (~10-25 deg elevation)** — close to where horizon-pointing
   links look. You need the antenna's **3D gain pattern (azimuth AND
   elevation)**, not azimuth alone.
2. **Sidelobes.** Even a sharp dish receives off-axis energy through sidelobes
   (ITU-R reference patterns, e.g. F.699 / F.1245: gain falls roughly as
   `32 - 25*log10(theta)`, never to zero). A strong satellite outside the main
   beam can still interfere. "Not pointing at it" != "safe".
3. **It's a power budget, not a direction test.** Harm depends on satellite
   **EIRP toward Finland** -> **path loss** -> victim antenna **gain in the
   satellite's direction** -> **frequency/bandwidth overlap** -> vs the
   **protection threshold** (PFD limit / I-over-N). Direction is one term. This
   is why the challenge stresses PFD calculation.
4. **The satellite isn't one direction.** Non-GSO constellations sweep **all
   azimuths over time**; GSO fleets spread along an **orbital arc** (a band of
   az/el as seen from Finland). "The satellite's direction" is a set, not a point.
5. **Many victims have no useful azimuth** (broadcast/mobile are ~omni) — there
   you fall back on frequency + PFD threshold.

### The real pipeline (a funnel; azimuth refines, it doesn't gate)
1. **Frequency/band overlap** (cheap, removes most candidates) ->
2. **Geographic footprint** over Finland (is Finland illuminated at all?) ->
3. **Geometry**: satellite apparent az/el from each victim; look up victim
   antenna gain in *that* direction (main beam vs sidelobe) ->
4. **Power budget**: received interference vs protection threshold ->
   **flag + priority score**.

Azimuth sharpens steps 3-4: a satellite in a directional link's **main beam** =
top-priority flag; one hitting only a sidelobe = lower. That ranking is what
keeps the human-review queue short — which is the whole point.

**One line:** azimuth lets you *rank* interference risk, not *decide* it, and
ranking is the product.

### Do NOT filter on the "FIN" service-area label
A satellite does not have to *target* Finland to interfere with it. Filtering
IFIC notices on `service_area = FIN` is wrong, confirmed by IFIC 3074:

- **57% of the notices (112 / 196) are non-GSO constellations** at ~600 km with
  high inclination (thousands of orbital planes at 55-99 deg). A LEO
  constellation at inclination >= ~60 deg **overflies Finland (60-70 N) by
  construction** and transmits continuously, whatever service area was declared.
- Service areas are barely country-level anyway: only 47 distinct area codes in
  the whole file, **`FIN` appears in just 2 group records**, and the dominant
  code is `XAA` (310) - a broad ITU zone, not a country - plus neighbours
  (`SWE`, `NOR`, `RUS`, `E`, `D`). A literal `FIN` filter would catch ~2 things
  and miss everything that matters.
- Finland is far north, so **GSO satellites appear at low elevation** - their
  downlink grazes the horizon, right where terrestrial antennas point - and a
  bird serving central Europe or Russia still spills power across the border.

**Correct relevance test = geometry + frequency, service area only as a hint:**
1. **Frequency overlap** with Finnish protected bands (necessary, cheap gate).
2. **Geometric reach to Finland**: non-GSO -> latitude coverage from
   altitude + inclination; GSO -> elevation angle from `geo.long_nom` /
   `s_beam.bore_long` (visible only within Finland's low-elevation arc).
3. **PFD / power budget** decides harm; **service area** (FIN, European/global
   zones, neighbours) only **ranks** priority - it never excludes.

## 3. The station populations (by licence class)

| Class | n | What it is | Power recorded? |
|-------|---|------------|-----------------|
| **FX**  | 320 | Licensed fixed point-to-point links (~2 GHz, digital D7W, directional) | **No** (structurally blank) |
| *(blank)* | 294 | Microwave fixed links in SHF (6–19 GHz), digital D7W | Yes, but 67 are corrupt |
| **BC**  | 117 | Broadcast transmitters (FM/TV), high power, kW, horizontal pol. | Yes |
| **MVV** | 63 | Maritime / mobile stations | Yes |
| **BT**  | 58 | Broadcast (transmitter variant) | Yes |
| **MUUT**| 22 | "Other" | **No** (structurally blank) |

Bands overall: UHF 532, VHF 234, SHF 96, HF 9. TX frequency 1.5 MHz – 27.5 GHz.

## 4. Column meaning (the ones that matter)

- **TX / RX frequency** — for fixed links these differ (frequency-division
  duplex); for broadcast they're equal. Parsed to `tx_freq_mhz` / `rx_freq_mhz`.
- **Radiation power + unit** — radiated power. Normalized to `power_w` / `power_dbw`.
- **Radiation power (ITU)** — a one-letter ITU power-type code; it's `E` on 855
  of 874 rows, so it does **not** distinguish subgroups (earlier red herring).
- **Ant gain / Ant height AGL / ASL** — antenna gain and heights (above ground /
  above sea level). Needed for EIRP and propagation later.
- **Radiation direction (°)** — antenna azimuth. **Directivity** — ND (non-directional)
  vs D (directional).
- **Emission class** — ITU emission designator (e.g. D7W = digital multi-channel,
  F3E = FM telephony, A3E = AM).

## 5. Data-quality findings (what's dirty, and the fix applied)

| Issue | Count | Cause | Handling |
|-------|------:|-------|----------|
| **Gigawatt power** | 67 | Synthetic artifact: blank-licence SHF microwave links; power 1e8–9e9 W, 35/67 duplicated | **Quarantined** — power nulled, station kept (`flag_bogus_power`, view `v_quarantine`) |
| **Blank power** | 342 | **Structural**: 100% of FX + 100% of MUUT. Power is simply not recorded for these licence types | Keep as-is; treat as victims (no TX power needed) or assume a typical fixed-link EIRP for threat modelling |
| Antenna below ground | 1 | Random generation (dataset note warns of this) | Flag only |
| Unparseable frequency | 3 | Bad cell value | Flag only |
| Out of Finland | 0 | — | — |

**Net:** radiated power is known-good for **465** stations (−8.8 … 49.0 dBW).
Frequency and geography are clean across the board.

## 6. Where the `.db` leaves you

`analysis/frequencies.db` (SQLite):
- `frequencies` — all 874 rows, raw + parsed + quality flags.
- `v_clean` — analysis-safe view; bogus power already nulled, `power_valid` flag.
- `v_quarantine` — the 67 rejected rows with original bogus value, for audit.

## 7. Open question for the interference step

For the 342 FX/MUUT fixed links with no power, decide a policy:
- treat them purely as **protected receivers** (we only need their frequency,
  location, antenna gain, and a protection threshold — not their own TX power); or
- if they're ever the *source*, assume a **typical fixed-link EIRP** per band.

This only matters once we cross-compare against the ITU IFIC threats.

## 8. The Finland-relevance pipeline & PFD methodology

This is the end-to-end engine that turns IFIC 3074 (196 satellite notices) into
a short, ranked, human-reviewable queue. It is a **funnel**: each stage is
cheap-to-expensive, and every stage records provenance so a reviewer can audit
why a candidate was kept.

### Data model (which tables, how they join)
```
notice (196)            who filed it: ntc_id, adm (administration), provision
  -> grp (34k)          beam+band groups: emi_rcp (E=emission/downlink,
                        R=reception/uplink), freq_min/freq_max (MHz), pwr_max
                        (dBW), bdwdth (kHz = band width), beam_name
       -> s_beam        per-beam gain (dBi), pwr_max_1m (dBW/MHz); bore_lat/long
                        (beam pointing) are NULL here -> see "the missing angle"
       -> srv_area      declared service-area country/zone codes (a HINT only)
  -> orbit (11k)        inclin_ang, op_ht_km (altitude) -> non-GSO geometry
  -> geo                long_nom = GSO orbital slot longitude
  -> c_pfd (119)        administration's DECLARED PFD (dBW/m2) + its bdwdth (Hz)
```

### Stage 1 - frequency overlap  (script: freq_overlap.py)
Interval-intersect each satellite EMISSION band (`grp` where `emi_rcp='E'`, the
downlinks that raise power at Finnish *receivers*) against every Finnish
protected channel (`v_clean`, [tx - bw/2, tx + bw/2]). Necessary, cheap gate.
Result: **196 -> 130 notices**, 8,721 (notice x station) overlap pairs, written
to `srs3074.db :: fin_freq_overlap`.

### Stage 2 - geometry  (pfd.py)
Does the satellite actually illuminate that station, and at what elevation?
- **non-GSO**: reaches overhead (up to 90 deg) if station |lat| <= orbit
  inclination; else best elevation at its peak latitude. Elevations are swept.
- **GSO**: fixed elevation from station lat/lon vs the slot longitude
  (`geo.long_nom`); below the horizon -> `not_visible_gso` (dropped).
Slant range: `d = sqrt((R*sin e)^2 + h(2R+h)) - R*sin e`.

### Stage 3 - PFD vs Article-21 limit  (pfd_score.py, article21.py)
PFD link budget:  `PFD = EIRP_eff - 20*log10(d_m) - 10.99  [dBW/m2]`
compared to the **per-band** RR Article 21 Table 21-4 limit, which is strictest
at low elevation (Finland's regime) and carries a band-specific reference
bandwidth (4 kHz below ~15 GHz, 1 MHz above). Worst margin over swept
elevations; `margin = PFD - limit > 0` -> exceedance.

Power source is TIERED with provenance (`pfd_source`):
1. **declared** - `c_pfd.pfd`, band-matched to the overlap frequency and
   normalized to the limit's reference bandwidth. Most trustworthy.
2. **computed** - worst-case EIRP = `grp.pwr_max + s_beam.gain` (matched beam),
   as a power spectral density in the reference bandwidth. Conservative.

### Adjacent-band tier (co-channel is the floor, not the whole picture)
A satellite emission in a band *next to* a protected channel can still interfere
via transmitter out-of-band/spurious emission and victim receiver selectivity.
So Stage 1 also emits **adjacent** pairs (within a bandwidth-scaled guard but not
overlapping), and Stage 3 subtracts a **frequency-dependent rejection** from the
interfering PFD:  `PFD_effective = PFD - FDR(offset)`  (adjacent.py). FDR grows
with the frequency gap (simplified ITU-R SM.1541-style mask), so a close strong
neighbour still flags while a distant one self-attenuates out of the queue.
- Pairs: 8,721 co-channel + ~31k adjacent (most heavily rejected by FDR).
- Result on 3074: **179 adjacent-band exceedances**, but they fall on the SAME
  22 notices / 41 stations already flagged co-channel (0 new actors) -> adjacent
  analysis *reinforces* the co-channel candidates here rather than expanding
  them. The capability still matters (the brief asks for it; another IFIC could
  surface new actors) and strengthens the evidence on flagged candidates.
- Limitation: victim receiver selectivity (ACS) is not in the Finnish dataset,
  so FDR models the transmitter side with a conservative spurious floor.

### Two findings that shape the result (and are themselves deliverables)
1. **Declared PFD doesn't cover the Finnish-overlap frequencies.** 3074's
   declared PFD sits at 1.2 / 5 / 43 GHz; the Finnish overlaps are 1-3 and
   10-20 GHz. Band-matched intersection = **0**. So a *rigorous* Article-21
   check is impossible from the filing alone -> the pipeline must fall back to
   computed/geometry. (An earlier per-notice MAX approach cross-band
   contaminated and produced spurious exceedances; band-matching fixed it.)
2. **Beam pointing is absent -> we screen with a worst-case.** `bore_lat/long`
   are NULL, so we cannot compute the off-axis angle to Finland. We therefore
   assume the main beam points at the station. Consequence:
   `margin < 0` = **provably safe even worst-case**;
   `margin > 0` = **not provably safe -> review** (not "confirmed harmful").

### The four angles (do not conflate them)
| angle | what | in data? | role |
|---|---|---|---|
| elevation / arrival (delta) | height above the station's horizon | computed | **sets the Article-21 limit** |
| inclination | tilt of the orbital plane | orbit.inclin_ang | which latitudes the sat overflies |
| azimuth | compass bearing | ground antenna only | victim gain toward the sat |
| beam boresight | where the satellite antenna points | NULL | sat gain toward Finland (off-axis) |

The missing one is **beam boresight**. For steerable non-GSO beams that is
expected - such systems are defined by a **PFD mask** (ITU epfd / Article 22),
not a fixed pointing, and our worst-case assumption approximates that mask peak.

### Current output (triage queue), table `srs3074.db :: fin_pfd_score`
- **22 notices / 41 stations** with worst-case PFD exceedances -> FLAG for review
  (led by CHN 125520111 +35 dB, INS 124520197 +27 dB, Indian GSO filings).
- **48 notices** reach Finland but carry no usable power -> needs-data queue
  (e.g. a 160 km USA LEO nearly overhead).
- **454 pairs** at frequencies with no Table 21-4 band -> need another criterion.

"No concern" is NOT the state: there is a concrete flagged set; the worst-case
screen deliberately over-includes until off-axis / epfd refinement narrows it.

### Known limitations / next refinements
- Table 21-4 values are the long-standing ones; verify vs current RR, finer band
  edges. Bands outside the table (e.g. <1525 MHz, 12.75-17.7 GHz) are unscored.
- Replace worst-case gain with real off-axis gain using epfd / PFD masks
  (`epfd_param`, `mask_info`) for the non-GSO cases.
- Declared-PFD reference-bandwidth assumptions where `c_pfd.bdwdth` is absent.
