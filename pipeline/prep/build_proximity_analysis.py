"""
Computes residential-proximity exposure for every real FracTracker facility
against real 2020 Census block-group population.

Method: for each facility, sum the population of every block group whose
centroid falls within a set of distance bands (1, 3, 5, 10 miles). Uses a
haversine BallTree (scikit-learn) over the 242,305 block-group centroids
for efficient nationwide radius queries, rather than a brute-force
O(facilities x block groups) distance matrix.

Real limitation, stated up front (same "Limitations, Tested" pattern used
elsewhere in this portfolio): this counts a block group's ENTIRE
population when its centroid falls inside the radius, and none of it when
the centroid falls just outside - even though the block group's actual
area, and the people in it, may straddle the boundary. This is a coarser
approximation than a true areal-weighted population estimate. It also
inherits the block-group-centroid limitation documented in
build_census_population.py (geometric centroid of a generalized 500k
polygon, not an official population-weighted center of population).
Both are acceptable for a comparative "which facilities have more/fewer
nearby residents" ranking, not for precise exposure counts.

Usage:
    python build_proximity_analysis.py \
        --facilities ../../data/facilities_clean.parquet \
        --population ../../data/census_bg_population_flat.parquet \
        --output ../../data/facility_proximity.parquet
"""

import argparse

import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree

EARTH_RADIUS_MILES = 3958.8
DISTANCE_BANDS_MILES = [1, 3, 5, 10]


def build(facilities_path: str, population_path: str) -> pd.DataFrame:
    facilities = pd.read_parquet(facilities_path)
    facilities = facilities.dropna(subset=["lat", "long"]).copy()

    pop = pd.read_parquet(population_path)
    pop = pop[pop["population"] > 0].copy()

    bg_coords_rad = np.radians(pop[["centroid_lat", "centroid_lon"]].to_numpy())
    tree = BallTree(bg_coords_rad, metric="haversine")

    fac_coords_rad = np.radians(facilities[["lat", "long"]].to_numpy())

    results = {f"population_within_{m}mi": np.zeros(len(facilities), dtype="int64") for m in DISTANCE_BANDS_MILES}
    results["block_groups_within_10mi"] = np.zeros(len(facilities), dtype="int64")

    pop_values = pop["population"].to_numpy()

    for band in DISTANCE_BANDS_MILES:
        radius_rad = band / EARTH_RADIUS_MILES
        indices = tree.query_radius(fac_coords_rad, r=radius_rad)
        counts = np.array([pop_values[idx].sum() for idx in indices])
        results[f"population_within_{band}mi"] = counts
        if band == 10:
            results["block_groups_within_10mi"] = np.array([len(idx) for idx in indices])

    for key, values in results.items():
        facilities[key] = values

    return facilities


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--facilities", required=True)
    parser.add_argument("--population", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = build(args.facilities, args.population)
    result.to_parquet(args.output)

    print(f"Facilities scored: {len(result)}")
    for band in DISTANCE_BANDS_MILES:
        col = f"population_within_{band}mi"
        print(f"  median population within {band}mi: {result[col].median():,.0f}")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
