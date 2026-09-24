"""
Exports the real, already-computed analysis results into the lean JSON/
GeoJSON files the static docs/ site reads directly (no server, no build
step - matches the pattern used by every other project in this
portfolio).

Usage:
    python build_docs_data.py \
        --facilities ../../data/facility_proximity.parquet \
        --imagery-dir ../../data/imagery \
        --docs-dir ../../docs
"""

import argparse
import json
import shutil
from pathlib import Path

import pandas as pd


def clean_value(v):
    if pd.isna(v):
        return None
    return v


def build_facilities_geojson(df: pd.DataFrame) -> dict:
    features = []
    for _, row in df.iterrows():
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [row["long"], row["lat"]]},
            "properties": {
                "name": row["facility_name"],
                "state": row["state"],
                "city": clean_value(row["city"]),
                "status": clean_value(row["status"]),
                "is_emerging": bool(row["is_emerging"]),
                "location_confidence": clean_value(row["location_confidence"]),
                "operator": clean_value(row["operator_name"]),
                "mw_min": clean_value(row["mw_min"]),
                "mw_max": clean_value(row["mw_max"]),
                "acres": clean_value(row.get("property_size_acres")),
                "community_pushback": clean_value(row["community_pushback"]),
                "resistance_status": clean_value(row["resistance_status"]),
                "petition_url": clean_value(row["petition_url"]),
                "pop_1mi": int(row["population_within_1mi"]),
                "pop_3mi": int(row["population_within_3mi"]),
                "pop_5mi": int(row["population_within_5mi"]),
                "pop_10mi": int(row["population_within_10mi"]),
            },
        })
    return {"type": "FeatureCollection", "features": features}


def build_state_summary(df: pd.DataFrame) -> list:
    rows = []
    for state, g in df.groupby("state"):
        mw_total = g["mw_min"].fillna(0).sum()
        rows.append({
            "state": state,
            "total_facilities": int(len(g)),
            "emerging": int(g["is_emerging"].sum()),
            "operating": int((g["status"] == "Operating").sum()),
            "cancelled": int((g["status"] == "Cancelled").sum()),
            "reported_mw": round(float(mw_total), 1),
            "median_pop_3mi": int(g["population_within_3mi"].median()),
            "pushback_count": int((g["community_pushback"] == "Yes").sum()),
        })
    rows.sort(key=lambda r: r["total_facilities"], reverse=True)
    return rows


def build_limitations(df: pd.DataFrame) -> dict:
    pushback = df[df["community_pushback"].isin(["Yes", "Unknown"])]
    by_pushback = pushback.groupby("community_pushback")[
        ["population_within_1mi", "population_within_3mi"]
    ].median()

    return {
        "dataset": {
            "source": "FracTracker Alliance National Data Centers Tracker",
            "total_records": int(len(df)),
            "location_confidence_counts": df["location_confidence"].value_counts().to_dict(),
            "mw_reported_pct": round(100 * df["mw_min"].notna().mean(), 1),
        },
        "census": {
            "source": "2020 Census (via Microsoft Planetary Computer us-census collection)",
            "total_population_verified": 334735155,
            "note": "Block-group population aggregated from real block-level counts; block group represented by its polygon's geometric centroid (equal-area projected), not an official population-weighted center of population.",
        },
        "proximity_method": {
            "note": "Counts the full population of any block group whose centroid falls within the radius - a coarser approximation than areal-weighted population, especially for large rural block groups.",
        },
        "pushback_finding": {
            "note": "Facilities with FracTracker-documented community pushback ('Yes') have LOWER median nearby population than facilities with unknown/unreported pushback status - the opposite of a naive 'more neighbors -> more opposition' hypothesis. Likely reflects organized opposition clustering in smaller rural/exurban communities rather than dense areas.",
            "median_pop_1mi_by_pushback": {k: int(v) for k, v in by_pushback["population_within_1mi"].items()},
            "median_pop_3mi_by_pushback": {k: int(v) for k, v in by_pushback["population_within_3mi"].items()},
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--facilities", required=True)
    parser.add_argument("--imagery-dir", required=True)
    parser.add_argument("--docs-dir", required=True)
    args = parser.parse_args()

    docs_dir = Path(args.docs_dir)
    docs_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_parquet(args.facilities)

    # allow_nan=False: fail loudly here if a NaN ever leaks into the export
    # instead of silently writing invalid JSON that only breaks in-browser
    # (real bug found this way - see build_facilities_geojson's status/
    # location_confidence fields).
    with open(docs_dir / "facilities.geojson", "w") as f:
        json.dump(build_facilities_geojson(df), f, allow_nan=False)

    with open(docs_dir / "state_summary.json", "w") as f:
        json.dump(build_state_summary(df), f, indent=2, allow_nan=False)

    with open(docs_dir / "limitations.json", "w") as f:
        json.dump(build_limitations(df), f, indent=2, allow_nan=False)

    # Imagery: copy PNG previews + manifest only (COGs stay local, too large for the site)
    imagery_out = docs_dir / "imagery"
    imagery_out.mkdir(exist_ok=True)
    imagery_dir = Path(args.imagery_dir)
    for png in imagery_dir.glob("*.png"):
        shutil.copy(png, imagery_out / png.name)
    shutil.copy(imagery_dir / "manifest.json", imagery_out / "manifest.json")

    print(f"Facilities: {len(df)}")
    print(f"States: {df['state'].nunique()}")
    print(f"Imagery pairs copied: {len(list(imagery_out.glob('*_before.png')))}")
    print(f"Wrote docs data to {docs_dir}")


if __name__ == "__main__":
    main()
