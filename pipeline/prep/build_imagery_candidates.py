"""
Selects facilities worth pulling real before/after satellite imagery for.

Criteria, chosen because they're what actually makes land-cover change
visible at Sentinel-2's 10m resolution - not an arbitrary top-N:
  - property_size_acres >= 100 (small colocation sites in existing
    buildings show no visible footprint change from orbit)
  - location_confidence == High (a loose coordinate produces a
    meaningless crop)
  - status is actively building or already built (Cancelled/Suspended
    sites were proposed but nothing was ever constructed to photograph)

Ranks by acreage and keeps the top N, one row per distinct
(facility_name, state) pair - several real FracTracker records share the
generic name "Tract Data Center" across different states/projects, which
a name-only filter would incorrectly conflate.

Usage:
    python build_imagery_candidates.py \
        --facilities ../../data/facility_proximity.parquet \
        --output ../../data/imagery_candidates.csv \
        --top-n 9
"""

import argparse

import pandas as pd

BUILT_OR_BUILDING_STATUSES = ["Operating", "Approved/Permitted/Under construction", "Expanding"]


def build(facilities_path: str, top_n: int) -> pd.DataFrame:
    df = pd.read_parquet(facilities_path)

    acres = pd.to_numeric(df["property_size_acres"].str.replace(",", "", regex=False).str.strip(), errors="coerce")
    df = df.assign(property_size_acres_num=acres)

    candidates = df[
        df["status"].isin(BUILT_OR_BUILDING_STATUSES)
        & (df["location_confidence"] == "High")
        & (df["property_size_acres_num"] >= 100)
    ].copy()

    candidates = candidates.drop_duplicates(subset=["facility_name", "state"])
    candidates = candidates.sort_values("property_size_acres_num", ascending=False).head(top_n)

    return candidates[
        ["facility_name", "state", "city", "status", "property_size_acres_num", "mw", "date_updated", "lat", "long"]
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--facilities", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--top-n", type=int, default=9)
    args = parser.parse_args()

    result = build(args.facilities, args.top_n)
    result.to_csv(args.output, index=False)
    print(f"Selected {len(result)} facilities for before/after imagery:")
    print(result[["facility_name", "state", "status", "property_size_acres_num"]].to_string(index=False))
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
