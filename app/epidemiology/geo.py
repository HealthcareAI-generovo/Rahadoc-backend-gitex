"""
Geospatial utilities for epidemiological surveillance.

Uses Uber H3 for hexagonal spatial indexing when coordinates are available,
falls back to ville (city name) when they are not.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# H3 resolution 7 ≈ 5.16 km² per hex — good for city-district level
DEFAULT_H3_RESOLUTION = 7

try:
    import h3
    H3_AVAILABLE = True
except ImportError:
    H3_AVAILABLE = False
    logger.warning("h3 package not installed — geospatial features disabled")


def lat_lng_to_h3(latitude: float, longitude: float, resolution: int = DEFAULT_H3_RESOLUTION) -> Optional[str]:
    """
    Convert latitude/longitude to an H3 hexagonal index.

    Args:
        latitude: Cabinet latitude
        longitude: Cabinet longitude
        resolution: H3 resolution (0-15). Default 7 ≈ 5.16 km²

    Returns:
        H3 index string, or None if h3 is not available or coords invalid.
    """
    if not H3_AVAILABLE:
        return None

    try:
        return h3.latlng_to_cell(latitude, longitude, resolution)
    except Exception as e:
        logger.warning(f"Failed to compute H3 index for ({latitude}, {longitude}): {e}")
        return None


def get_region_key(ville: Optional[str], latitude: Optional[float], longitude: Optional[float]) -> tuple[str, Optional[str]]:
    """
    Determine the region key for grouping.

    Returns:
        Tuple of (display_region, h3_index).
        - display_region: human-readable city name (always present)
        - h3_index: H3 hex index if coordinates were available, else None
    """
    h3_index = None
    if latitude is not None and longitude is not None:
        h3_index = lat_lng_to_h3(latitude, longitude)

    display_region = ville or "Inconnu"
    return display_region, h3_index


def h3_to_parent(h3_index: str, parent_resolution: int = 5) -> Optional[str]:
    """
    Get the parent H3 cell at a coarser resolution.
    Useful for zooming out when analyzing broader regional trends.

    Args:
        h3_index: Child H3 index
        parent_resolution: Target coarser resolution (default 5 ≈ 252 km²)

    Returns:
        Parent H3 index, or None if unavailable.
    """
    if not H3_AVAILABLE or not h3_index:
        return None

    try:
        return h3.cell_to_parent(h3_index, parent_resolution)
    except Exception as e:
        logger.warning(f"Failed to get H3 parent for {h3_index}: {e}")
        return None
