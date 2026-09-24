"""
Pulls real Sentinel-2 true-color before/after imagery for a curated set of
large, high-confidence data center facilities (see data/imagery_candidates.csv).

Method (same STAC approach proven in seattle-tree-canopy-change):
  - Query Sentinel-2 L2A via Microsoft Planetary Computer for two windows:
    a fixed 2017-2018 "before" baseline (Sentinel-2 has solid global
    coverage from 2017 onward, and predates every facility in this
    dataset - none were proposed that early) and a recent 2025-2026
    "after" window, at each facility's real coordinates.
  - Pick the least-cloudy scene in each window (eo:cloud_cover).
  - Window-read just an AOI around the facility (sized off the real
    property_size_acres field, not a fixed crop, so a 40,000-acre site and
    a 400-acre site are each framed to actually show their footprint).
  - Export each crop as a Cloud-Optimized GeoTIFF and a PNG preview.

Real limitation, stated up front: a single least-cloudy scene per window
is not a cloud-free mosaic - some crops may still show partial cloud or
haze, and is noted per-facility in the manifest this script writes rather
than silently cropped out.

Usage:
    python build_before_after_imagery.py \
        --candidates ../../data/imagery_candidates.csv \
        --output-dir ../../data/imagery
"""

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import planetary_computer
import rasterio
from pystac_client import Client
from rasterio.enums import Resampling
from rasterio.windows import from_bounds
from rio_cogeo.cogeo import cog_translate
from rio_cogeo.profiles import cog_profiles

CATALOG_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
BEFORE_WINDOW = "2017-06-01/2018-09-30"
AFTER_WINDOW = "2025-06-01/2026-09-30"
MIN_BUFFER_M = 800
MAX_BUFFER_M = 8000


def aoi_buffer_meters(acres) -> float:
    if pd.isna(acres) or acres <= 0:
        return MIN_BUFFER_M
    side_m = math.sqrt(acres * 4046.86)
    buffer_m = side_m * 0.9
    return float(np.clip(buffer_m, MIN_BUFFER_M, MAX_BUFFER_M))


def utm_epsg_for(lon: float, lat: float) -> str:
    zone = int((lon + 180) / 6) + 1
    hemisphere = 326 if lat >= 0 else 327
    return f"EPSG:{hemisphere}{zone:02d}"


def candidate_scenes(catalog, lon, lat, buffer_m, window):
    """Least-cloudy scenes first. A bbox match doesn't guarantee the point
    falls inside the granule's actual (non-rectangular) swath - Sentinel-2
    tiles have angled no-data edges - so callers should fall through the
    list rather than trust the top result blindly."""
    bbox_deg = buffer_m / 111_000
    bbox = [lon - bbox_deg, lat - bbox_deg, lon + bbox_deg, lat + bbox_deg]
    search = catalog.search(
        collections=["sentinel-2-l2a"],
        bbox=bbox,
        datetime=window,
        query={"eo:cloud_cover": {"lt": 40}},
    )
    items = list(search.items())
    items.sort(key=lambda it: it.properties.get("eo:cloud_cover", 100))
    return items


MIN_RETRY_BUFFER_M = 500


def _read_crop(item, lon, lat, buffer_m):
    """Reads a single-tile true-color crop. Returns (stacked_array, transform, crs)."""
    signed = planetary_computer.sign(item)
    epsg = utm_epsg_for(lon, lat)

    import pyproj
    transformer = pyproj.Transformer.from_crs("EPSG:4326", epsg, always_xy=True)
    cx, cy = transformer.transform(lon, lat)
    minx, miny, maxx, maxy = cx - buffer_m, cy - buffer_m, cx + buffer_m, cy + buffer_m

    band_arrays = []
    ref_transform = ref_crs = None
    for band in ["B04", "B03", "B02"]:  # true color: R, G, B
        href = signed.assets[band].href
        with rasterio.open(href) as src:
            if src.crs.to_string() != epsg:
                # Sentinel-2 tiles are already in a local UTM zone; reuse it directly
                epsg = src.crs.to_string()
                transformer = pyproj.Transformer.from_crs("EPSG:4326", epsg, always_xy=True)
                cx, cy = transformer.transform(lon, lat)
                minx, miny, maxx, maxy = cx - buffer_m, cy - buffer_m, cx + buffer_m, cy + buffer_m
            window = from_bounds(minx, miny, maxx, maxy, src.transform)
            data = src.read(1, window=window, out_shape=(1, 600, 600), resampling=Resampling.bilinear)
            band_arrays.append(data)
            if ref_transform is None:
                ref_transform = src.window_transform(window) * src.transform.scale(
                    window.width / 600, window.height / 600
                )
                ref_crs = src.crs

    return np.stack(band_arrays).astype("uint16"), ref_transform, ref_crs


def _has_flat_band(stacked, min_std=5.0):
    """True if any band is essentially textureless (near-constant DN) over
    real terrain - a genuine per-band radiometric anomaly found in one
    real granule (Upper Burrell, PA: R and G both sat at ~1001, Sentinel-2's
    near-zero-reflectance offset, while B carried real variance), not
    reflected in eo:cloud_cover (that item reported 0%) or in the nodata
    check (pixels were nonzero, just flat)."""
    return any(band.std() < min_std for band in stacked)


def crop_true_color(items, lon, lat, buffer_m, out_tif):
    # A single Sentinel-2 granule is one ~110km UTM tile with an angled
    # (non-rectangular) swath edge. Three real failure modes found by
    # visually checking output, not assumed away: (1) a large AOI - big
    # rural parcels get a bigger buffer, see aoi_buffer_meters - can run
    # past that tile's edge, fixed by shrinking the buffer and re-reading;
    # (2) the query point can fall in a no-data sliver of the single
    # least-cloudy granule even though its bbox matched the search, which
    # shrinking the buffer can't fix - only trying the next-least-cloudy
    # granule does; (3) a band can come back flat/textureless despite
    # passing the nodata and cloud-cover checks (see _has_flat_band) -
    # also only fixed by trying the next granule.
    chosen_item = None
    stacked = ref_transform = ref_crs = None
    for item in items:
        current_buffer = buffer_m
        while True:
            stacked, ref_transform, ref_crs = _read_crop(item, lon, lat, current_buffer)
            nodata_fraction = (stacked == 0).all(axis=0).mean()
            if nodata_fraction < 0.02 or current_buffer <= MIN_RETRY_BUFFER_M:
                break
            current_buffer = max(current_buffer * 0.6, MIN_RETRY_BUFFER_M)
            print(f"    retrying with smaller buffer ({current_buffer:.0f}m) - {nodata_fraction:.0%} nodata")
        flat = _has_flat_band(stacked)
        if nodata_fraction < 0.02 and not flat:
            chosen_item = item
            break
        reason = "flat band" if flat else f"{nodata_fraction:.0%} nodata"
        print(f"    {item.id}: {reason} even at minimum buffer, trying next scene")

    if chosen_item is None:
        chosen_item = items[-1] if items else None
        print(f"    (kept a bad crop - no clean scene found in window)")

    profile = {
        "driver": "GTiff", "height": 600, "width": 600, "count": 3,
        "dtype": "uint16", "crs": ref_crs, "transform": ref_transform, "nodata": 0,
    }
    tmp_path = out_tif.with_suffix(".tmp.tif")
    with rasterio.open(tmp_path, "w", **profile) as dst:
        dst.write(stacked)

    cog_translate(tmp_path, out_tif, cog_profiles.get("deflate"), quiet=True)
    tmp_path.unlink()

    # PNG preview (simple stretch)
    rgb = stacked.transpose(1, 2, 0).astype("float32")
    p2, p98 = np.percentile(rgb[rgb > 0], [2, 98]) if (rgb > 0).any() else (0, 3000)
    rgb = np.clip((rgb - p2) / (p98 - p2 + 1e-6), 0, 1)
    rgb_8bit = (rgb * 255).astype("uint8")
    from PIL import Image
    Image.fromarray(rgb_8bit).save(out_tif.with_suffix(".png"))

    return chosen_item, nodata_fraction


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    catalog = Client.open(CATALOG_URL)
    candidates = pd.read_csv(args.candidates)

    manifest = []
    for _, row in candidates.iterrows():
        slug = f"{row['state']}_{row['facility_name']}".replace(" ", "_").replace("/", "-")
        lon, lat = float(row["long"]), float(row["lat"])
        buffer_m = aoi_buffer_meters(row.get("property_size_acres_num"))
        print(f"\n{row['facility_name']} ({row['state']}) - buffer {buffer_m:.0f}m")

        record = {"facility_name": row["facility_name"], "state": row["state"], "slug": slug,
                   "lat": lat, "lon": lon, "buffer_m": buffer_m}

        for label, window in [("before", BEFORE_WINDOW), ("after", AFTER_WINDOW)]:
            items = candidate_scenes(catalog, lon, lat, buffer_m, window)[:5]
            if not items:
                print(f"  {label}: no scene found")
                record[f"{label}_status"] = "no_scene_found"
                continue
            print(f"  {label}: trying {len(items)} candidate scene(s), least cloudy first")
            out_tif = out_dir / f"{slug}_{label}.tif"
            try:
                chosen_item, nodata_fraction = crop_true_color(items, lon, lat, buffer_m, out_tif)
                record[f"{label}_status"] = "ok" if nodata_fraction < 0.02 else f"ok_partial_nodata_{nodata_fraction:.0%}"
                record[f"{label}_item_id"] = chosen_item.id
                record[f"{label}_date"] = chosen_item.properties.get("datetime")
                record[f"{label}_cloud_cover"] = chosen_item.properties.get("eo:cloud_cover")
            except Exception as exc:
                print(f"  {label}: FAILED - {exc}")
                record[f"{label}_status"] = f"error: {exc}"

        manifest.append(record)

    with open(out_dir / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2, default=str)
    print(f"\nWrote manifest for {len(manifest)} facilities to {out_dir / 'manifest.json'}")


if __name__ == "__main__":
    main()
