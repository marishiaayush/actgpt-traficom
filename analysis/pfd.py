"""
Power-flux-density (PFD) calculator — the deterministic, auditable physics for
"is a satellite emission strong enough to matter at a Finnish station?"

Everything here is pure geometry + a link budget. No ML, no black box: every
number can be hand-checked. Units are stated on every function.

The chain (see analysis/REPORT.md section on PFD):
    EIRP (dBW)  --spreading over 4*pi*d^2-->  PFD at surface (dBW/m^2)
    scale to a reference bandwidth, then compare to the Article-21 limit,
    which itself depends on the arrival elevation angle.

Run as a script for a worked GSO-vs-LEO example:
    uv run python analysis/pfd.py
"""

import math

R_E_KM = 6371.0          # mean Earth radius
GSO_ALT_KM = 35786.0     # geostationary altitude
SPREAD_CONST_DB = 10.0 * math.log10(4.0 * math.pi)   # 10.99 dB


# --------------------------------------------------------------------------
# geometry
# --------------------------------------------------------------------------
def slant_range_km(elev_deg: float, alt_km: float) -> float:
    """Distance from a ground point to a satellite at altitude `alt_km` seen at
    elevation angle `elev_deg` (0 = horizon, 90 = overhead).

    Solves the Earth-centre triangle (law of cosines):
        d = sqrt( (R*sin e)^2 + h(2R+h) ) - R*sin e
    Check: e=90 -> d=h (overhead);  e=0 -> d=sqrt(h(2R+h)) (horizon).
    """
    e = math.radians(elev_deg)
    rs = R_E_KM * math.sin(e)
    return math.sqrt(rs * rs + alt_km * (2 * R_E_KM + alt_km)) - rs


def elevation_from_central_angle(gamma_deg: float, alt_km: float) -> float:
    """Elevation angle of a satellite at altitude `alt_km` whose sub-satellite
    point is `gamma_deg` of great-circle arc away from the ground station.
    gamma=0 -> overhead (90 deg). Negative result = below horizon (not visible).
    """
    g = math.radians(gamma_deg)
    ratio = R_E_KM / (R_E_KM + alt_km)
    return math.degrees(math.atan2(math.cos(g) - ratio, math.sin(g)))


def central_angle_deg(lat1, lon1, lat2, lon2) -> float:
    """Great-circle angle (deg) between two lat/lon points."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    c = math.sin(p1)*math.sin(p2) + math.cos(p1)*math.cos(p2)*math.cos(dl)
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def gso_max_elevation_deg(lat_deg: float, dlon_deg: float = 0.0) -> float:
    """Max elevation at which a GSO satellite (over the equator) can be seen
    from latitude `lat_deg`, with `dlon_deg` = longitude difference between the
    station and the satellite's orbital slot. For Finland (~60-70N) this is low
    (~10-25 deg), which is exactly why strict low-elevation PFD limits apply.
    """
    lat = math.radians(lat_deg)
    dlon = math.radians(dlon_deg)
    # angle between station and sub-satellite point (both on their radii)
    cos_gamma = math.cos(lat) * math.cos(dlon)
    gamma = math.acos(cos_gamma)
    ratio = R_E_KM / (R_E_KM + GSO_ALT_KM)
    # elevation of a GSO sat at great-circle angle gamma from sub-sat point
    el = math.atan2(math.cos(gamma) - ratio, math.sin(gamma))
    return math.degrees(el)


# --------------------------------------------------------------------------
# link budget
# --------------------------------------------------------------------------
def pfd_dbw_m2(eirp_dbw: float, d_km: float,
               emission_bw_mhz: float | None = None,
               ref_bw_mhz: float | None = None) -> float:
    """PFD at the surface from an emission of EIRP `eirp_dbw` at slant range
    `d_km`. If both bandwidths are given, the result is scaled to `ref_bw_mhz`
    (assumes power spread uniformly across `emission_bw_mhz`).

        PFD = EIRP - 20*log10(d_m) - 10*log10(4*pi)   [dBW/m^2]
    """
    d_m = d_km * 1000.0
    pfd = eirp_dbw - 20.0 * math.log10(d_m) - SPREAD_CONST_DB
    if emission_bw_mhz and ref_bw_mhz and emission_bw_mhz > 0:
        pfd -= 10.0 * math.log10(emission_bw_mhz / ref_bw_mhz)
    return pfd


def article21_limit_dbw_m2(elev_deg: float,
                           l_low: float = -132.0,
                           slope_db_per_deg: float = 0.5,
                           e1: float = 5.0, e2: float = 25.0) -> float:
    """Article-21-style PFD limit vs arrival elevation (illustrative shape;
    the actual L0/slope are band-specific in RR Table 21-4). Strictest at low
    elevation, relaxing with elevation:
        e <= e1 : l_low
        e1<e<e2 : l_low + slope*(e-e1)
        e >= e2 : l_low + slope*(e2-e1)
    """
    if elev_deg <= e1:
        return l_low
    if elev_deg >= e2:
        return l_low + slope_db_per_deg * (e2 - e1)
    return l_low + slope_db_per_deg * (elev_deg - e1)


def margin_db(eirp_dbw: float, elev_deg: float, alt_km: float,
              emission_bw_mhz: float | None = None,
              ref_bw_mhz: float | None = None, **limit_kw) -> dict:
    """Full one-shot evaluation. margin > 0 => PFD exceeds limit => flag."""
    d = slant_range_km(elev_deg, alt_km)
    pfd = pfd_dbw_m2(eirp_dbw, d, emission_bw_mhz, ref_bw_mhz)
    lim = article21_limit_dbw_m2(elev_deg, **limit_kw)
    return {"slant_km": d, "pfd_dbw_m2": pfd, "limit_dbw_m2": lim,
            "margin_db": pfd - lim, "exceeds": pfd > lim}


if __name__ == "__main__":
    EIRP = 10.0   # dBW per MHz, illustrative downlink spectral density
    print("Worked example: EIRP = %.0f dBW/MHz, limit shape default\n" % EIRP)
    print(f"GSO max elevation from 62N (same longitude): "
          f"{gso_max_elevation_deg(62):.1f} deg\n")
    for name, alt, elev in [("GSO @ 20 deg el", GSO_ALT_KM, 20),
                            ("LEO 600km @ 20 deg el", 600, 20),
                            ("LEO 600km @ 80 deg el", 600, 80)]:
        r = margin_db(EIRP, elev, alt, ref_bw_mhz=1.0)
        print(f"{name:24s}  d={r['slant_km']:8.0f} km  "
              f"PFD={r['pfd_dbw_m2']:7.1f}  limit={r['limit_dbw_m2']:7.1f}  "
              f"margin={r['margin_db']:+6.1f} dB  "
              f"{'EXCEEDS' if r['exceeds'] else 'ok'}")
    # the 36 dB GSO->LEO gap at equal EIRP/elevation
    g = pfd_dbw_m2(EIRP, slant_range_km(20, GSO_ALT_KM), ref_bw_mhz=1.0)
    l = pfd_dbw_m2(EIRP, slant_range_km(20, 600), ref_bw_mhz=1.0)
    print(f"\nLEO is {l - g:+.1f} dB hotter than GSO at equal EIRP (20 deg el)")
