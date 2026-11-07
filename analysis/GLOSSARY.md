# Glossary — abbreviations & definitions

Quick reference for the terms used across [`REPORT.md`](REPORT.md),
[`QUESTIONS.md`](QUESTIONS.md) and the code.

## ITU & regulatory

| Term | Meaning |
|------|---------|
| ITU | International Telecommunication Union — UN agency for global spectrum |
| ITU-R | ITU Radiocommunication Sector |
| BR | Radiocommunication **B**ureau — the ITU body that processes filings |
| RR | **R**adio **R**egulations — the binding international spectrum treaty |
| IFIC | International Frequency Information Circular — BR's bi-weekly publication of filings (space + terrestrial), the data we ingest |
| MIFR | Master International Frequency Register — the official record of assignments |
| API/A | Advance Publication Information — the **earliest** satellite filing stage |
| CR/C | Coordination Request — the later filing stage requiring coordination |
| Article 9 / 11 | RR articles: coordination (9) and notification (11) of assignments |
| Article 21 | RR article with **hard PFD limits** at the Earth's surface (Table 21-4) |
| Article 22 | RR article governing **epfd** limits for non-GSO systems |
| Appendix 4 (AP4) | The notice data format filed with the BR |
| Appendix 5 | Coordination criteria / thresholds (e.g. ΔT/T) |
| AP30 / AP30A / AP30B | Appendices for the **broadcasting- and fixed-satellite plans** (own limits, not Art 21) |
| GE06 | Geneva 2006 Agreement — digital terrestrial **broadcasting** plan |
| ECC T/R 25-08 | CEPT/ECC recommendation — a terrestrial coordination/protection criterion |
| CEPT / ECC | European Conference of Postal & Telecoms Administrations / its Electronic Communications Committee |
| Traficom | Finnish Transport and Communications Agency (the regulator) |
| M4 / M15 | Traficom regulations: M4 = frequency allocation table; M15 = licence-exempt |
| Taajuusjakotaulukko | (Finnish) the frequency **allocation table** — the M4 annex / API dataset |

## Orbital & geometry

| Term | Meaning |
|------|---------|
| GSO | **G**eo**s**tationary **o**rbit — fixed over the equator at ~35 786 km |
| non-GSO / NGSO | Non-geostationary (moving) satellites — LEO/MEO constellations |
| LEO / MEO | Low / Medium Earth Orbit (~300–2 000 km / ~2 000–35 000 km) |
| inclination | Tilt of the **orbital plane** vs the equator → which latitudes it overflies |
| elevation / arrival angle (δ) | Height of the satellite **above the horizon** from a ground point → **sets the Art-21 limit** |
| azimuth | Compass bearing (N/E/S/W) to the satellite or of an antenna |
| boresight | The direction an antenna's **main beam points** |
| slant range | Straight-line distance from ground station to satellite |
| footprint | The area on Earth a satellite illuminates / is visible from |
| sub-satellite point | The point on Earth directly below the satellite |
| long_nom | Nominal orbital **longitude** (GSO slot) — SRS field |
| WGS84 | The geodetic coordinate system (the lon/lat datum) |

## RF & interference

| Term | Meaning |
|------|---------|
| RF | Radio frequency |
| TX / RX | Transmit / Receive frequency |
| FDD | Frequency-Division Duplex — paired TX/RX frequencies (fixed links) |
| PFD | **P**ower **F**lux **D**ensity — received power per unit area (dBW/m²); the Art-21 regulated quantity |
| epfd | **Equivalent** PFD — aggregate PFD from a whole non-GSO constellation (Art 22) |
| EIRP | Effective Isotropic Radiated Power = TX power + antenna gain |
| co-channel | Interferer on the **same** frequency as the victim |
| adjacent-channel | Interferer on a **nearby** frequency (spills in via OOBE / receiver selectivity) |
| OOBE | Out-Of-Band Emission — a transmitter's spectral spill beyond its band |
| ACIR | Adjacent-Channel Interference Ratio = combination of ACLR and ACS |
| ACLR | Adjacent-Channel Leakage Ratio (transmitter side) |
| ACS | Adjacent-Channel Selectivity (receiver side) |
| FDR | **F**requency-**D**ependent **R**ejection — attenuation vs frequency offset (our adjacent-band penalty) |
| I/N | Interference-to-Noise ratio — a victim-specific protection metric |
| ΔT/T | Fractional increase in receiver noise temperature — a coordination trigger |
| main beam / sidelobe | Antenna's peak direction / the weaker off-axis lobes |
| emission designator | ITU code for an emission, e.g. **D7W** (digital, multi-channel), **F3E** (FM telephony), **A3E** (AM) |
| reference bandwidth | The bandwidth a limit is specified "in" (Art 21: 4 kHz below ~15 GHz, 1 MHz above) |
| HF / VHF / UHF / SHF / EHF | Frequency bands: <30 / 30–300 MHz / 0.3–3 / 3–30 / >30 GHz |

## Units

| Unit | Meaning |
|------|---------|
| dBW | Power relative to 1 watt (decibels): `10·log₁₀(P/1 W)` |
| dBi | Antenna gain relative to an isotropic radiator |
| dBW/m² | PFD — power per square metre, in dB |
| dBW/m²/4kHz, /MHz | PFD in a stated reference bandwidth |
| margin (dB) | `PFD − limit`; **> 0 means the limit is exceeded** (a flag) |

## Finnish dataset — licence / field codes

| Code | Meaning |
|------|---------|
| FX | Fixed service (point-to-point microwave links) |
| BC / BT | Broadcasting (transmitter variants) |
| MVV | Maritime / mobile stations |
| MUUT | (Finnish) "other" |
| KIINTEÄ | (Finnish) "fixed" (mast type) |
| ND / D | Non-directional / Directional antenna |
| H / V / D (polarisation) | Horizontal / Vertical / (dual) |

## ITU software & SRS database

| Term | Meaning |
|------|---------|
| SNS / SRS | Space Network System / Space Radiocommunication Stations — the satellite filing **database** (`srs.mdb`) |
| SpaceCap / SpaceQry / SpacePub | ITU Windows tools to capture / query / publish space filings |
| GIBC | ITU tool that **computes PFD / interference** from the SRS |
| TerRaQ / TerRaNotices | ITU tools for the **terrestrial** IFIC database |
| mdbtools | Open-source tool we use to read MS-Access `.mdb` on macOS |
| notice / grp / freq | SRS tables: a filing / beam+band groups / frequency assignments |
| s_beam | SRS table: per-beam antenna gain, power density, pointing |
| c_pfd | SRS table: the administration's **declared PFD** values |
| srv_area | SRS table: declared service-area country/zone codes |
| orbit / geo | SRS tables: non-GSO orbital params / GSO slot longitude |

## Our pipeline terms

| Term | Meaning |
|------|---------|
| victim | A protected Finnish station that could receive interference |
| threat | A satellite notice that could cause interference |
| triage | Ranking notices so a human expert reviews the few that matter |
| worst-case screen | Assuming the main beam points at the station (conservative); a flag = "not provably safe", not "confirmed harmful" |
| the funnel | frequency overlap → geometry → PFD vs Article 21 |
