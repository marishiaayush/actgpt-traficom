# Expert validation — questions & confirmations

Questions for the Traficom / spectrum experts to check we're going in the right
direction. Each maps to a concrete assumption in our pipeline (see
[`REPORT.md`](REPORT.md)). Ask the top 3 first; the rest are backup.

**Opening line:**
> "We built an auditable funnel — frequency overlap → orbital geometry → PFD vs
> Article 21 — that turns an IFIC into a ranked review queue, and I want to
> check our protection criterion and calibrate against how you actually assess
> 3074."

---

## Top 3 (highest leverage)

### 1. Is PFD-at-surface vs Article 21 the right yardstick — or epfd / I-over-N?
Validates our entire Stage 3. We use **RR Article 21, Table 21-4 hard PFD
limits**. But non-GSO is usually governed by **epfd (Article 22)**, and
coordination is often triggered by **ΔT/T (Appendix 5)** or an **I/N at the
victim receiver**, not a hard PFD.
- Which criterion applies to which case (GSO downlink vs non-GSO vs
  AP30/30A/30B plan bands)?
- If epfd for non-GSO: that reshapes how we score the LEO constellations, which
  are the bulk of our flags.

### 2. For IFIC 3074 specifically — which notices are actual concerns?
The single most valuable ask. 3074 is the accuracy-scored case; their answer is
**ground truth** to calibrate our funnel against (overlap with our 22-notice
flag set? false positives? misses?). Get notice numbers if possible.

### 3. How do you get PFD when the filing doesn't declare it at the overlap frequency?
Our biggest gap: declared PFD (`c_pfd`) never sits at the Finnish-overlap
frequencies, and beam pointing (`bore_lat/long`) is null, so we fell back to a
worst-case computed EIRP (`pwr_max` + peak gain).
- Do you recompute from the SRS, run **GIBC**, or use the **PFD / epfd masks**
  (`epfd_param`, `mask_info`)?
- Is our worst-case fallback how you'd do it, or is there a field/tool we missed?

---

## Confirmations on direction (quick yes/no)

- **Product framing:** an auditable, human-in-the-loop **triage queue** that
  *ranks notices for expert review* — right deliverable? (vs. automated decision)
- **Relevance gate:** we deliberately do **not** filter on the FIN service-area
  label — we use frequency + orbital geometry, because ~57% of notices are LEO
  constellations overflying Finland. Agree?
- **Direction:** we test satellite **downlink emissions** against Finnish
  **receivers** as the protection case. Right focus?
- **Worst-case screen:** where we lack beam pointing we assume
  main-beam-on-station (conservative — a flag means "not provably safe").
  Acceptable for triage?

---

## Technical refinements (if time allows)

- **Notice types / provisions:** should we weight or prioritize by provision —
  API/A vs CR/C vs Article 11 notification vs **AP30/30A/30B**? Do AP30 plan
  bands use their own limits rather than Article 21?
- **Adjacent-band:** what guard band / emission mask do you actually use —
  ITU-R SM.1541, or service-specific guard bands? Is receiver selectivity (ACS)
  data available anywhere?
- **Reference bandwidth:** we compare in Table 21-4's reference bandwidth
  (4 kHz / 1 MHz) and normalize the declared PFD's bandwidth accordingly — is
  that handled correctly?
- **Protected set:** beyond the synthetic special-interest list + M4, is there a
  per-station sensitivity / protection threshold we should factor in?

---

## Answers (fill in during the meeting)

| # | Question | Expert answer / action |
|---|----------|------------------------|
| 1 | Protection criterion (Art 21 / epfd / I-N) | |
| 2 | 3074 real concerns (notice numbers) | |
| 3 | PFD when not declared (recompute / GIBC / mask) | |
| — | Triage-queue framing | |
| — | Geometry-not-FIN gate | |
| — | Downlink-vs-receiver focus | |
| — | Worst-case screen acceptable? | |
| — | Provision / notice-type weighting | |
| — | Adjacent-band guard / mask | |
| — | Reference-bandwidth handling | |
| — | Per-station protection threshold | |
