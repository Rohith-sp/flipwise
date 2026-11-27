"""Display names of the datacentre sites, shared by the live dashboard and the services.

Display only: nothing here feeds a simulation. A site is named by its dc_id, because two sites
may share a grid region (configs/regions5.yaml puts Chennai and Hyderabad both on SR, D66). The
city is used only when the config's region for that dc_id matches the one below; any other
layout falls back to the region's grid name, so a reordered config never shows a wrong city.
"""

from __future__ import annotations

# dc_id -> (city, grid, region_id), in the dc order of configs/base.yaml and configs/regions5.yaml.
SITES: dict[int, tuple[str, str, int]] = {
    0: ("Delhi NCR", "Northern grid", 1),
    1: ("Mumbai", "Western grid", 2),
    2: ("Chennai", "Southern grid", 3),
    3: ("Kolkata", "Eastern grid", 4),
    4: ("Hyderabad", "Southern grid", 3),
}
GRIDS: dict[int, str] = {
    1: "Northern grid",
    2: "Western grid",
    3: "Southern grid",
    4: "Eastern grid",
}


def site(dc_id: int, region_id: int | None = None) -> tuple[str, str]:
    """(short name, grid) of one site. Without `region_id` the dc_id alone decides."""
    known = SITES.get(dc_id)
    if known is not None and (region_id is None or known[2] == region_id):
        return known[0], known[1]
    grid = "" if region_id is None else GRIDS.get(region_id, f"region {region_id}")
    return f"Datacentre {dc_id}", grid


def site_name(dc_id: int, region_id: int | None = None) -> str:
    """'City (grid)': the UI shows the part before ' (' as the short name."""
    short, grid = site(dc_id, region_id)
    return f"{short} ({grid})" if grid else short
