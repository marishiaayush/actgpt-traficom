# The project in plain language

A friendly walkthrough — no jargon. For the technical detail see
[`REPORT.md`](REPORT.md); for term definitions see [`GLOSSARY.md`](GLOSSARY.md).

## The problem

Radios on the ground in Finland (TV/radio masts, microwave links between towers,
maritime stations) listen on certain frequencies. A **satellite** passing over
or near Finland that transmits on the **same or a nearby frequency** can drown
out those ground radios — like someone shouting over your phone call.

Two things make this hard:
1. **You can't fix it after launch.** Once a satellite is up and transmitting,
   you can't recall it. So the time to act is *before* launch, while the
   satellite is still a paper application at the ITU (the UN body for radio).
2. **There are too many to check by hand.** Companies file thousands of
   satellites (think Starlink-style mega-constellations). A human expert can't
   read every filing.

**Our job:** build a tool that reads the filings automatically and hands the
expert a *short, ranked list* of the ones worth a closer look — with the
reasoning shown, so they can trust and check it.

## How it works — a funnel

We start with ~200 satellite filings in one ITU publication and narrow them
down in three steps, cheap checks first:

1. **"Do they even share a frequency?"**
   Keep only satellites that transmit on a frequency a Finnish receiver is
   listening on (including *nearby* frequencies, which can still leak in).
   → cuts ~200 filings down to ~150.

2. **"Can the satellite actually reach Finland?"**
   A satellite over Australia can't interfere with Finland. We check the orbit:
   does it ever pass over / become visible from Finland's far-north location?
   → drops the ones that never come into view.

3. **"Is it strong enough to matter?"**
   Even a visible, same-frequency satellite is only a problem if the power
   arriving on the ground is too high. We calculate that power (called **PFD**)
   and compare it to the international legal limit.
   → produces the final ranked list of concerns.

Think of it as airport security: a quick metal detector (frequency), then a
look at who's actually heading to your gate (geometry), then a bag search for
the few that beep (power).

## What we found (for the test publication, "IFIC 3074")

- Of ~200 filings, a couple of dozen raise a **flag worth an expert's review**.
- The majority of filings are **non-GSO constellations** (lots of moving
  satellites), which is exactly the modern challenge the experts care about.
- Our newest check (real orbit simulation) already **caught mistakes**: a few
  "flagged" satellites actually orbit over the equator and **never rise above
  Finland's horizon** — so they can't interfere at all. We removed them.

## Being honest about what a "flag" means

This is a **screening tool**, not a judge. A flag means *"we can't rule this one
out — a human should look,"* **not** *"this will definitely cause interference."*
We deliberately err on the side of flagging too much rather than missing a real
case. Several pieces of information are missing from the public filings (exactly
how a satellite's antenna points, its precise power definition), so we make
careful worst-case assumptions and label them clearly.

Everything is **auditable**: for every flagged satellite we record *why* — which
frequency, which Finnish station, the geometry, the power number, and the
assumptions. An expert can follow and challenge every step.

## Where the data comes from

- **The satellites:** ITU's published filing databases (the "IFIC").
- **What to protect:** a list of Finnish ground stations + Finland's official
  frequency-allocation table.
- **Orbits:** we simulate them from the filed orbital parameters using the same
  standard physics (SGP4) that satellite trackers use.

## What's next

- Confirm the right legal yardstick with the experts (there are a few possible
  rules depending on the satellite type).
- Replace worst-case guesses with better data where we can get it.
- Build a dashboard so an expert can click through the ranked list.
