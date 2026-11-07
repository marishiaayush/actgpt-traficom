"""
Adjacent-band interference: guard-band search + frequency-dependent rejection.

Co-channel overlap is the floor, not the whole picture. A satellite emission in
a band NEXT TO a protected channel can still interfere via:
  - transmitter out-of-band / spurious emission spilling into the victim band;
  - victim receiver imperfect selectivity / front-end overload.

We model the net attenuation as a Frequency-Dependent Rejection FDR(offset):
the effective interfering PFD at the victim is  PFD - FDR(offset).  FDR grows
with the frequency gap, so a close strong neighbour still flags while a distant
one self-attenuates out of the queue.

This is a SIMPLIFIED generic mask (shape after ITU-R SM.1541 out-of-band
domain); values are tunable parameters, not a specific equipment mask. The
victim receiver's own selectivity (ACS) is not in the Finnish dataset, so FDR
here represents the transmitter side with a conservative spurious floor.
"""

# OOB domain is taken as ~GUARD_BW_FACTOR satellite-bandwidths beyond the band
# edge; beyond that the emission is in the spurious floor.
GUARD_BW_FACTOR = 2.5          # how far out (in sat bandwidths) we still search
GUARD_FLOOR_MHZ = 1.0          # minimum guard, so narrowband sats still searched
OOB_SLOPE_DB_PER_BW = 30.0     # rejection rise per satellite-bandwidth of offset
SPURIOUS_FLOOR_DB = 60.0       # cap: max rejection we credit far out
MIN_BW_MHZ = 0.1               # floor for normalization (avoid /0 on tiny bands)


def guard_mhz(sat_bw_mhz: float) -> float:
    """How far beyond a satellite band edge to still look for a victim."""
    bw = max(sat_bw_mhz, MIN_BW_MHZ)
    return max(GUARD_FLOOR_MHZ, GUARD_BW_FACTOR * bw)


def fdr_db(offset_mhz: float, sat_bw_mhz: float) -> float:
    """Frequency-dependent rejection (dB) for an emission whose nearest band
    edge is `offset_mhz` away from the victim. offset<=0 => co-channel => 0 dB."""
    if offset_mhz <= 0:
        return 0.0
    u = offset_mhz / max(sat_bw_mhz, MIN_BW_MHZ)   # offset in bandwidths
    return min(SPURIOUS_FLOOR_DB, OOB_SLOPE_DB_PER_BW * u)


if __name__ == "__main__":
    for bw in [1.0, 40.0]:
        print(f"sat bandwidth {bw} MHz -> guard {guard_mhz(bw):.1f} MHz")
        for off in [0, bw*0.5, bw, bw*2, bw*5]:
            print(f"   offset {off:6.1f} MHz -> FDR {fdr_db(off, bw):5.1f} dB")
