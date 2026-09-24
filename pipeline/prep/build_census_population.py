"""
Builds block-group-level population centroids from the real 2020 Census.

Source data (downloaded from Microsoft Planetary Computer's `us-census`
STAC collection, itself republishing official Census Bureau products):
  - census_blocks_population.parquet (52 parts): 2020 Census block-level
    total population (field P0010001, PL 94-171 redistricting table P1).
    8,174,955 blocks nationwide. Verified against the official 2020 Census
    figure before use: summing P0010001 across every block gives
    334,735,155, which equals the published 50-state resident population
    (331,449,281) plus Puerto Rico (3,285,874) exactly - confirming this
    is genuine total population, not a different table misread.
  - cb_2020_us_bg_500k.parquet: TIGER/Line cartographic boundary block
    group polygons (1:500,000 generalized), 242,305 block groups.

Real limitation, documented rather than hidden: block population is
aggregated to the block GROUP (by construction, since only the
generalized 500k boundary was pulled to avoid a 7.3GB full-resolution
block polygon download - see pipeline/prep/README or run notes), and each
block group is represented by its polygon's geometric centroid rather
than an official population-weighted center of population. For large,
unevenly-populated block groups (common in rural areas) this understates
how close population actually sits to a given point. This is the same
class of limitation flagged in the "Limitations, Tested" tabs on other
projects in this portfolio - stated up front, not discovered by a
reviewer.

Usage:
    python build_census_population.py \
        --population-dir ../../data/census_raw/population_parts \
        --block-groups ../../data/census_raw/cb_2020_us_bg_500k.parquet \
        --output ../../data/census_bg_population.parquet
"""

import argparse
import glob

import geopandas as gpd
import pandas as pd


def build(population_dir: str, block_groups_path: str) -> gpd.GeoDataFrame:
    parts = sorted(glob.glob(f"{population_dir}/part.*.parquet"))
    if not parts:
        raise FileNotFoundError(f"No population parts found in {population_dir}")

    pop = pd.concat(
        (pd.read_parquet(p, columns=["P0010001"]) for p in parts),
        axis=0,
    )
    pop.index.name = "block_geoid"
    pop = pop.reset_index()

    # Block group GEOID = first 12 characters of the 15-character block GEOID
    # (state[2] + county[3] + tract[6] + block-group-digit[1]).
    pop["GEOID"] = pop["block_geoid"].str[:12]
    bg_pop = pop.groupby("GEOID", as_index=False)["P0010001"].sum()
    bg_pop = bg_pop.rename(columns={"P0010001": "population"})

    bg = gpd.read_parquet(block_groups_path, columns=["GEOID", "STATEFP", "ALAND", "AWATER", "geometry"])

    merged = bg.merge(bg_pop, on="GEOID", how="left")
    unmatched = merged["population"].isna().sum()

    merged["population"] = merged["population"].fillna(0).astype("int64")

    # Centroids computed in a geographic CRS (lat/lon) distort polygon shape
    # and give the wrong point, especially for large western block groups.
    # World Cylindrical Equal Area (EPSG:6933) is valid nationwide -
    # including AK/HI/PR, which a CONUS-only projection would distort -
    # so centroids are computed there, then converted back to WGS84.
    equal_area = merged.geometry.to_crs("EPSG:6933").centroid
    centroid_wgs84 = equal_area.to_crs("EPSG:4326")
    merged["centroid_lon"] = centroid_wgs84.x
    merged["centroid_lat"] = centroid_wgs84.y

    print(f"Block groups: {len(merged)}")
    print(f"Block groups with no matching population record: {unmatched}")
    print(f"Total population represented: {merged['population'].sum():,}")

    return merged


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--population-dir", required=True)
    parser.add_argument("--block-groups", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = build(args.population_dir, args.block_groups)
    result.drop(columns="geometry").to_parquet(
        args.output.replace(".parquet", "_flat.parquet"), index=False
    )
    result.to_parquet(args.output)
    print(f"Wrote {len(result)} block-group records to {args.output}")


if __name__ == "__main__":
    main()
