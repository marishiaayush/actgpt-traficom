"""
ITU Radio Regulations Article 21, Table 21-4 — PFD limits at the Earth's
surface produced by space stations, as a function of frequency band and the
angle of arrival (elevation) above the horizontal plane.

Each band's limit has the standard three-segment form in the arrival angle d:
    d <= 5 deg      : L0
    5 < d < 25 deg  : L0 + slope*(d - 5)
    d >= 25 deg     : L0 + slope*20   (== the tabulated 25-90 value)
given in a REFERENCE BANDWIDTH that differs by band (4 kHz lower down, 1 MHz
higher up). Comparisons must be made in that reference bandwidth.

SOURCE: RR Article 21, Table 21-4 (long-standing values). These should be
re-verified against the current RR edition for a production tool; band edges in
the real table are finer than the consolidated rows below.
"""

# (f_lo_MHz, f_hi_MHz, L0_dBW_m2, slope_dB_per_deg, ref_bw_Hz)
# L_25to90 is implied = L0 + slope*20.
TABLE_21_4 = [
    (1525,   2500,  -154.0, 0.50, 4_000),
    (2500,   2690,  -152.0, 0.75, 4_000),
    (3400,   7750,  -152.0, 0.50, 4_000),
    (8025,   8500,  -150.0, 0.50, 4_000),
    (10700, 11700,  -150.0, 0.50, 4_000),
    (12200, 12750,  -150.0, 0.50, 4_000),
    (17700, 19700,  -115.0, 0.50, 1_000_000),
    (21400, 22000,  -115.0, 0.50, 1_000_000),
    (25250, 27500,  -115.0, 0.50, 1_000_000),
]

E1, E2 = 5.0, 25.0


def limit(freq_mhz: float, elev_deg: float):
    """Return (limit_dBW_m2, ref_bw_Hz) for this frequency and arrival angle,
    or (None, None) if the frequency falls in no Table-21-4 band."""
    for f_lo, f_hi, l0, slope, ref_bw in TABLE_21_4:
        if f_lo <= freq_mhz < f_hi:
            if elev_deg <= E1:
                lim = l0
            elif elev_deg >= E2:
                lim = l0 + slope * (E2 - E1)
            else:
                lim = l0 + slope * (elev_deg - E1)
            return lim, ref_bw
    return None, None


def normalize_pfd_to_ref(pfd_dbw_m2: float, decl_bw_hz: float,
                         ref_bw_hz: float) -> float:
    """Express a declared PFD (measured in `decl_bw_hz`) in the limit's
    `ref_bw_hz`. If the emission bandwidth is NARROWER than the reference, all
    its power already fits in the reference band -> no change. If WIDER, only
    the reference-bandwidth slice counts (uniform-density assumption):
        PFD_ref = PFD_decl - 10*log10(decl_bw / ref_bw)   when decl_bw > ref_bw
    """
    import math
    if not decl_bw_hz or decl_bw_hz <= ref_bw_hz:
        return pfd_dbw_m2
    return pfd_dbw_m2 - 10.0 * math.log10(decl_bw_hz / ref_bw_hz)


if __name__ == "__main__":
    for f in [2000, 2600, 5000, 8100, 12500, 18000, 26000, 40000]:
        for e in [5, 15, 25, 60]:
            lim, bw = limit(f, e)
            s = f"{lim:.1f} dBW/m2 /{int(bw)}Hz" if lim is not None else "no band"
            print(f"{f:6d} MHz  {e:2d} deg -> {s}")
        print()
