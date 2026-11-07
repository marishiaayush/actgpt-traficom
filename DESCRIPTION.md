# ACT-GPT — Saving Earth from Space Interferers

Every two weeks the ITU publishes hundreds of new satellite filings, and any one
of them can quietly interfere with the radio systems a country depends on — air-
traffic radar, maritime safety links, broadcasting, emergency networks. The
catch: once a satellite is launched and radiating, it cannot be recalled, so the
only moment to act is while it is still a paper filing. Today that means a
handful of human experts manually reading tens of thousands of entries, hunting
for the few that genuinely matter. As mega-constellations push filing volumes
into the stratosphere, that no longer scales. ACT-GPT is the auditable, AI-
assisted workflow that reads the mass for them — and hands back a short, ranked,
human-reviewable shortlist where every decision is traceable to a formula.

Point it at an ITU IFIC publication and it runs a transparent funnel. **Frequency
overlap** (co-channel *and* adjacent-band, with an out-of-band leakage model)
finds satellites whose emissions touch a country's protected spectrum. **Real
orbital geometry** — full SGP4 propagation via Skyfield, the same physics
satellite trackers use — determines whether each satellite actually passes over
the country and at what elevation, replacing crude heuristics with genuine
passes. **Power-flux-density** is then computed through a proper link budget and
checked against the ITU Radio Regulations Article 21, Table 21-4 limits. From
~200 filings in a single publication, roughly two dozen survive as a ranked queue
of concerns — not a black-box verdict, but a reviewable case file.

And it is genuinely auditable. For every flagged satellite you can trace the
whole chain — overlapping frequency → arrival elevation → slant range → PFD →
regulatory limit → margin — each number one click from its exact equation. That
rigor is not cosmetic: the real SGP4 geometry already caught false positives a
simpler approach would have raised (equatorial constellations that physically
never rise above the horizon at northern latitudes), and it surfaced an honest
finding — the filings' own declared power values do not cover the frequencies
that matter, so the tool refuses to fabricate a verdict and says so, clearly.

The whole thing is a polished, local, low-power app. A two-panel dashboard maps
the affected part of the country — land **and** maritime (EEZ / territorial
waters) — shows which exact frequency bands are hit versus the nation's intended
use, and visualises the interfering bandwidth down to channel granularity. A
human reviewer stays in control: relabel any satellite ALERT ↔ cleared with a
click, individually or in bulk, every change persisted and timestamped, then
export a one-click Excel report of what was analysed and what was decided. It
watches the ITU for new publications and can download and process a brand-new
filing in-app. You can even drop in your own receiver — a fixed tower, an
offshore platform, or a moving ship along a route — and ask, "when and where is
it at risk?"

Crucially, it is built to generalise. Finland is only the first profile: the
protected-station list, the frequency-allocation table, the Article-21 limits,
and the national boundary are all data-driven and swappable — upload a new
antenna list, edit the limits file, point it at another country. The same engine
that protects Finnish spectrum becomes a cross-border interference-coordination
tool for any administration on Earth.

Under the hood it is lean and reproducible — Python, SQLite, Streamlit, and uv —
cloneable and runnable on a laptop in minutes on macOS, Linux, or Windows, with a
free static export for sharing. It is, end to end, exactly what the challenge
asked for: an auditable, AI-assisted workflow that monitors ITU IFIC
information, identifies the cases relevant to a country, supports the real
frequency- and power-level analysis, and prepares expert-reviewable output —
turning a slow, manual, unscalable task into one that is transparent, repeatable,
and genuinely trustworthy. It does not replace the expert; it gives the expert
superpowers, and shows its working at every step.
