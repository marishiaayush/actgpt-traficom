"""
Phase 2 geography: which part of Finland (land + maritime/EEZ) a flagged
satellite can illuminate, and whether maritime areas are affected.

Boundaries bundled in analysis/data/ (land = Natural Earth, EEZ = Marine
Regions, simplified). To avoid projecting a huge GSO visibility cone into a
lon/lat polygon (which wraps near the poles), we test a GRID of Finnish
territory cells against the satellite's visibility cap -- robust and simple,
and it splits land vs sea directly.
"""

import json
import math
from functools import lru_cache
from pathlib import Path

import numpy as np
from shapely import contains_xy
from shapely.geometry import shape
from shapely.ops import unary_union

from pfd import (slant_range_km, elevation_from_central_angle,
                 central_angle_deg, GSO_ALT_KM)
import article21

DATA = Path(__file__).resolve().parent / "data"
R_E, GSO_ALT = 6371.0, 35786.0
FIN_LON, FIN_LAT = 25.0, 64.0            # representative overpass centre (non-GSO)
# grid over Finland's bounding box
GLON = np.arange(19.0, 32.01, 0.15)
GLAT = np.arange(58.5, 70.51, 0.10)


@lru_cache(maxsize=1)
def load():
    land = shape(json.load(open(DATA / "finland_land.geojson"))["geometry"]).buffer(0)
    eez = shape(json.load(open(DATA / "finland_eez.geojson"))["geometry"]).buffer(0)
    return dict(land=land, eez=eez, maritime=eez.difference(land),
                territory=unary_union([land, eez]))


@lru_cache(maxsize=1)
def _grid():
    """All territory grid cells, tagged land/maritime (computed once)."""
    g = load()
    lon, lat = np.meshgrid(GLON, GLAT)
    lon, lat = lon.ravel(), lat.ravel()
    in_land = contains_xy(g["land"], lon, lat)
    in_sea = contains_xy(g["eez"], lon, lat) & ~in_land
    keep = in_land | in_sea
    return lon[keep], lat[keep], np.where(in_land[keep], "land", "maritime")


@lru_cache(maxsize=2)
def outline(which="eez"):
    """lon/lat arrays of a boundary's exterior rings (None-separated) for plotting."""
    geom = load()[which]
    polys = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
    lon, lat = [], []
    for p in polys:
        x, y = p.exterior.xy
        lon += list(x) + [None]
        lat += list(y) + [None]
    return lon, lat


def classify_point(lat, lon):
    g = load()
    if contains_xy(g["land"], lon, lat):
        return "land"
    if contains_xy(g["eez"], lon, lat):
        return "maritime"
    return "outside"


def horizon_gamma(alt_km):
    return math.degrees(math.acos(R_E / (R_E + alt_km)))


def affected_region(is_gso, slot_lon=None, alt_km=None):
    """Grid cells of Finnish territory the satellite can see (elevation >= 0).
    Returns the illuminated cells + land/maritime split + coverage stats."""
    glon, glat, zone = _grid()
    if is_gso:
        slat, slon, gamma = 0.0, (slot_lon if slot_lon is not None else 25.0), horizon_gamma(GSO_ALT)
    else:
        slat, slon, gamma = FIN_LAT, FIN_LON, horizon_gamma(alt_km or 600.0)
    # great-circle angle from sub-satellite point to each cell
    p1, p2 = math.radians(slat), np.radians(glat)
    dl = np.radians(glon - slon)
    cosc = math.sin(p1)*np.sin(p2) + math.cos(p1)*np.cos(p2)*np.cos(dl)
    vis = np.degrees(np.arccos(np.clip(cosc, -1, 1))) <= gamma
    tot = len(glon)
    sea_tot = int((zone == "maritime").sum())
    aff_sea = int((vis & (zone == "maritime")).sum())
    return dict(
        lon=glon[vis], lat=glat[vis], zone=zone[vis],
        pct_territory=round(100.0 * vis.sum() / tot, 1) if tot else 0.0,
        includes_maritime=aff_sea > 0,
        pct_maritime=round(100.0 * aff_sea / sea_tot, 1) if sea_tot else 0.0,
        n_cells=int(vis.sum()))


def over_limit_region(is_gso, eirp_eff, freq_mhz, slot_lon=None,
                      alt_km=None, incl=None, max_elev=None):
    """Grid cells where the satellite's PFD would EXCEED the Article-21 limit
    (per-cell geometry), i.e. *which part of Finland is actually over the
    limit*. Varies across Finland (unlike all-or-nothing horizon visibility)."""
    _, ref_bw = article21.limit(freq_mhz, 10.0)
    if ref_bw is None:                       # no Art-21 band -> fall back
        return affected_region(is_gso, slot_lon, alt_km)
    glon, glat, zone = _grid()
    aff = np.zeros(len(glon), bool)
    mtl = None if incl is None else (incl if incl <= 90 else 180 - incl)
    spread = 10.0 * math.log10(4 * math.pi)
    sweep = np.arange(5, 91, 5)               # match pfd_score's elevation sweep

    def exceeds(elev, alt):
        """True if PFD at this elevation exceeds the limit."""
        d = slant_range_km(elev, alt)
        pfd = eirp_eff - 20.0 * math.log10(d * 1000.0) - spread
        lim, _ = article21.limit(freq_mhz, elev)
        return pfd - lim > 0

    for i in range(len(glon)):
        if is_gso:
            # GSO elevation from a cell is fixed geometry -> single value
            elev = elevation_from_central_angle(
                central_angle_deg(glat[i], glon[i], 0.0, slot_lon), GSO_ALT_KM)
            if elev > 0 and exceeds(elev, GSO_ALT_KM):
                aff[i] = True
        else:
            # non-GSO: a cell sees the satellite across a RANGE of elevations as
            # it passes. The worst case (and strictest Art-21 limit) is often the
            # low grazing angle -- so sweep, like the station scorer does.
            # Cap at the SGP4 max elevation when known: it reflects the FULL
            # constellation's real reach (a notice can have several inclination
            # shells; the stored `incl` is only one of them). This keeps the
            # shaded area consistent with the flagged stations.
            if max_elev is not None:
                emax = max_elev
            elif mtl is None or abs(glat[i]) <= mtl:
                emax = 90.0
            else:
                emax = elevation_from_central_angle(abs(glat[i]) - mtl, alt_km)
            if emax <= 5:
                continue
            if any(exceeds(e, alt_km) for e in sweep if e <= emax):
                aff[i] = True
    tot = len(glon)
    sea_tot = int((zone == "maritime").sum())
    aff_sea = int((aff & (zone == "maritime")).sum())
    return dict(lon=glon[aff], lat=glat[aff], zone=zone[aff],
                pct_territory=round(100.0 * aff.sum() / tot, 1) if tot else 0.0,
                includes_maritime=aff_sea > 0,
                pct_maritime=round(100.0 * aff_sea / sea_tot, 1) if sea_tot else 0.0,
                n_cells=int(aff.sum()))


if __name__ == "__main__":
    g = load()
    print("land/eez/maritime/territory areas (deg^2):",
          *[round(g[k].area, 2) for k in ("land", "eez", "maritime", "territory")])
    glon, _, zone = _grid()
    print(f"grid cells: {len(glon)} ({int((zone=='land').sum())} land, "
          f"{int((zone=='maritime').sum())} maritime)")
    for lab, kw in [("GSO slot 60.5E", dict(is_gso=True, slot_lon=60.5)),
                    ("non-GSO 525km", dict(is_gso=False, alt_km=525))]:
        r = affected_region(**kw)
        print(f"{lab}: {r['pct_territory']}% of territory, maritime "
              f"{r['includes_maritime']} ({r['pct_maritime']}% of sea)")
