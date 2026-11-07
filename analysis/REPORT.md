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
  high inclination (thousands of orbital planes at 55-99 deg). A ground track
  reaches latitude = inclination (or 180-inclination if retrograde), so a
  constellation whose inclination covers ~62-70N **can pass over Finland**
  regardless of the declared service area -- *potential* reach, not proof the
  beam illuminates a given station (which needs orbital/beam detail we lack).
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
Receive-side protection: interval-intersect each satellite EMISSION band (`grp`
where `emi_rcp='E'`, the downlinks that raise power at Finnish *receivers*)
against each victim's **RECEIVE** channel `[rx - bw/2, rx + bw/2]` (`v_clean`).
Using RX (not TX) matters because fixed links are frequency-division duplex:
all 320 FX + ~250 others have TX != RX. **Broadcast stations (BC/BT) are
transmitters** (TX==RX in the synthetic data) -> tagged `station_role =
broadcast_tx`, NOT treated as genuine receivers; their interference model
(protecting coverage-area receivers) is different and out of scope here.
Result: **196 -> 150 notices**, ~8.9k co-channel pairs, written to
`srs3074.db :: fin_freq_overlap` (with `station_role`, `victim_freq_mhz`).

### Stage 2 - geometry  (pfd.py, geometry_sgp4.py)
Does the satellite become visible from Finland, and at what elevation?
- **non-GSO -- real SGP4 (geometry_sgp4.py, authoritative).** We synthesize a
  representative constellation from the notice's real orbital planes and
  propagate it with **SGP4 (Skyfield, MIT)** to get the true max elevation over
  Finland. If `max_elev < 5 deg` the notice **cannot be seen from Finland** ->
  `not_visible_sgp4` (dropped); otherwise the elevation sweep is capped at the
  real max. This REPLACED a crude latitude approximation that floored
  below-horizon cases to 5deg and **wrongly flagged 2 equatorial constellations**
  (NUSANTARA, incl 2deg, max elev -25deg) -- now correctly dropped.
  *(Fallback, if SGP4 not run: ground track reaches latitude = inclination, or
  180-incl for retrograde. Potential visibility only.)*
- **GSO**: fixed elevation from station lat/lon vs the slot longitude
  (`geo.long_nom`); below the horizon -> `not_visible_gso` (dropped).
Slant range: `d = sqrt((R*sin e)^2 + h(2R+h)) - R*sin e`.
Run order: `freq_overlap.py` -> `geometry_sgp4.py` -> `pfd_score.py`.
`geometry_sgp4.py` also yields real passes/day, view-minutes, coverage% per
notice (table `fin_geom_sgp4`) -- the temporal detail the crude model lacked.

### Stage 3 - PFD vs Article-21 limit  (pfd_score.py, article21.py)
PFD link budget:  `PFD = EIRP_eff - 20*log10(d_m) - 10.99  [dBW/m2]`
compared to the **per-band** RR Article 21 Table 21-4 limit, strictest at low
elevation (Finland's regime), in a band-specific reference bandwidth (4 kHz
below ~15 GHz, 1 MHz above). Worst margin over swept elevations;
`margin = PFD - limit > 0` -> a **screening alert** (not a confirmed exceedance).

**Caveats (expert-flagged):**
- **Article 21 Table 21-4 is NOT a universal criterion.** Its applicability
  depends on the service and provision of each notice (and non-GSO is often
  governed by **epfd / Article 22** when protecting GSO networks -- though here
  the victims are *terrestrial*, so Art-21 PFD is the candidate criterion). We do
  not yet check service/provision applicability. (Expert question #1.)
- **`pwr_max` definition unconfirmed.** We treat `grp.pwr_max` as transmitter
  power so `pwr_max + gain` = EIRP; if it were already EIRP or a power density,
  gain is double-counted / bandwidth mis-scaled. Verify vs SRS Preface / GIBC.

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
- Pairs: ~8.9k co-channel + ~31k adjacent (most heavily rejected by FDR).
- Result on 3074: **~165 adjacent-band SCREENING ALERTS** (not validated
  exceedances), falling on notices already flagged co-channel -> adjacent
  analysis *reinforces* the co-channel candidates rather than expanding them.
- **These are exploratory.** SM.1541 covers unwanted *out-of-band emissions*
  only; it is not a complete receiver-specific interference model, and victim
  receiver selectivity (ACS) is absent from the Finnish dataset. So FDR models
  the transmitter side with a conservative spurious floor -- call the results
  **adjacent-band screening alerts**, not validated exceedances.

### Two findings that shape the result (and are themselves deliverables)
1. **Declared PFD doesn't cover the Finnish-overlap frequencies.** 3074's
   declared PFD sits at 1.2 / 5 / 43 GHz; the Finnish overlaps are 1-3 and
   10-20 GHz. Band-matched intersection = **0**. So a *rigorous* Article-21
   check is impossible from the filing alone -> the pipeline must fall back to
   computed/geometry. (An earlier per-notice MAX approach cross-band
   contaminated and produced spurious exceedances; band-matching fixed it.)
2. **Beam pointing is absent -> we screen with a worst-case.** `bore_lat/long`
   are NULL, so we cannot compute the off-axis angle to Finland. We therefore
   assume the main beam points at the station. Interpret carefully (not a
   rigorous bound -- beam characteristics, aggregate emissions and the power
   definition are not all established):
   `margin < 0` = **below the screening threshold under the stated conservative
   assumptions** (NOT proven safe);
   `margin > 0` = a **screening alert for review** (NOT proof of interference).

### The four angles (do not conflate them)
| angle | what | in data? | role |
|---|---|---|---|
| elevation / arrival (delta) | height above the station's horizon | computed | **sets the Article-21 limit** |
| inclination | tilt of the orbital plane | orbit.inclin_ang | which latitudes the sat overflies |
| azimuth | compass bearing | ground antenna only | victim gain toward the sat |
| beam boresight | where the satellite antenna points | NULL | sat gain toward Finland (off-axis) |

The missing one is **beam boresight**. For steerable non-GSO beams that is
expected - such systems are characterized by a **PFD mask** rather than a fixed
pointing, and our worst-case assumption approximates that mask peak. (Note:
**Article 22 epfd** is a *distinct* examination for non-GSO systems protecting
**GSO networks** - a different victim class than our *terrestrial* stations - so
it is not directly the criterion here; see expert question #1.)

### Current output (triage queue), table `srs3074.db :: fin_pfd_score`
*(Receive-band / RX fix + geometry fix applied; plots suffixed `_v2`.)*
- **~23 notices / ~33 stations** raise **screening alerts** (worst-case PFD >
  limit under the stated assumptions) -> review. NOT confirmed interference.
  (SGP4 visibility dropped 2 equatorial false positives vs the pre-SGP4 run.)
- Many notices reach Finland but carry no usable power -> needs-data queue
  (e.g. a 160 km USA LEO nearly overhead).
- Pairs at frequencies with no Table 21-4 band -> need another criterion.

"No concern" is NOT the state, but neither is "confirmed interference": there is
a concrete set of screening alerts that the worst-case screen deliberately
over-includes, pending off-axis / epfd refinement and the expert validation in
[`QUESTIONS.md`](QUESTIONS.md).

### Scalability (the synthetic table is 874 rows; the real one is ~10^7)
- **Physics is per-notice, not per-pair.** Geometry (SGP4) and PFD power are
  computed once per satellite notice and reused -> they scale with ~hundreds of
  notices, not with stations.
- **Stage 1 is frequency-indexed, not brute-force.** Stations are sorted by
  frequency; each satellite band binary-searches only the stations near its
  frequency (`searchsorted`) instead of comparing all bands x all stations
  (O(10^10) on the real table). Verified identical output.
- **The irreducible cost is the number of matched pairs** (data-driven). Next
  steps for true scale: vectorized/bulk pair emission (not a Python append loop)
  and aggregating co-located, co-frequency stations into one PFD case.

### Known limitations / next refinements
- Table 21-4 values are the long-standing ones; verify vs current RR, finer band
  edges. Bands outside the table (e.g. <1525 MHz, 12.75-17.7 GHz) are unscored.
- Replace worst-case gain with real off-axis gain using epfd / PFD masks
  (`epfd_param`, `mask_info`) for the non-GSO cases.
- Declared-PFD reference-bandwidth assumptions where `c_pfd.bdwdth` is absent.
