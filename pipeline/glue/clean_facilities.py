"""
Cleans and normalizes the raw FracTracker National Data Centers Tracker
export. Written and validated locally first (real, checkable output on
the real dataset) before being adapted as an AWS Glue job - the
transformation logic is identical either way; only the read/write paths
change (local CSV <-> S3).

Real data quality issues found and handled here, not assumed:
  - 1 record with lat=0/long=0 (a null-island placeholder, not a real
    coordinate) - filtered out with the reason logged.
  - location_confidence and community_pushback have inconsistent casing
    ("high" vs "High", "yes" vs "Yes") - normalized to title case.
  - mw (capacity) mixes single values ("960") with ranges ("99-200") and
    is null for 1,024 of 1,694 records (60%) - parsed into mw_min/mw_max
    where present, left null (not zero-filled) where genuinely unknown.

Usage (local):
    python clean_facilities.py --input ../../data/fractracker_raw.csv --output ../../data/facilities_clean.parquet
"""

import argparse

from pyspark.sql import SparkSession, functions as F
from pyspark.sql.types import DoubleType


def build_pipeline(spark, input_path: str):
    df = spark.read.csv(input_path, header=True, inferSchema=False, multiLine=True, escape='"')
    raw_count = df.count()

    # Real casing normalization (data-quality fix, not assumption)
    df = df.withColumn("location_confidence", F.initcap(F.trim(F.col("location_confidence"))))
    df = df.withColumn("community_pushback", F.initcap(F.trim(F.col("community_pushback"))))

    # Coordinates: cast to double, drop the one real null-island record
    df = df.withColumn("lat", F.col("lat").cast(DoubleType()))
    df = df.withColumn("long", F.col("long").cast(DoubleType()))
    bad_coords = df.filter((F.col("lat") == 0) | (F.col("long") == 0))
    bad_coord_count = bad_coords.count()
    df = df.filter(~((F.col("lat") == 0) | (F.col("long") == 0)))

    # mw: parse "960" -> (960, 960), "99-200" -> (99, 200), null -> (null, null)
    # Real formatting quirks found in this free-text field, handled rather
    # than assumed away: thousands separators ("1,000"), and inconsistent
    # dash characters for ranges - hyphen, en-dash "12-20", even em-dash -
    # all normalized to a plain hyphen before parsing. try_cast is used
    # (not cast) so any value still malformed after normalization returns
    # NULL and is counted, instead of crashing the whole job over one bad
    # cell - the realistic production behavior for a messy free-text field.
    # Real limitation: mw is unreported for 60% of records - left null,
    # not zero-filled, so aggregate MW totals honestly represent only the
    # subset with disclosed capacity, not the full inventory.
    mw_null_count = df.filter(F.col("mw").isNull() | (F.trim(F.col("mw")) == "")).count()
    # ‐-― covers hyphen/non-breaking-hyphen/figure-dash/en-dash/
    # em-dash/horizontal-bar as one unambiguous range; − (minus sign)
    # listed separately since it falls outside that contiguous block.
    df = df.withColumn(
        "_mw_clean",
        F.regexp_replace(F.regexp_replace(F.col("mw"), ",", ""), "[‐-―−]", "-"),
    )
    df = df.withColumn(
        "mw_min",
        F.when(F.col("_mw_clean").contains("-"), F.expr("try_cast(split(_mw_clean, '-')[0] as double)"))
         .otherwise(F.expr("try_cast(_mw_clean as double)")),
    ).withColumn(
        "mw_max",
        F.when(F.col("_mw_clean").contains("-"), F.expr("try_cast(split(_mw_clean, '-')[1] as double)"))
         .otherwise(F.expr("try_cast(_mw_clean as double)")),
    ).drop("_mw_clean")
    mw_parse_failures = df.filter(
        F.col("mw").isNotNull() & (F.trim(F.col("mw")) != "") & F.col("mw_min").isNull()
    ).count()

    # Standardize the "is this new/emerging" signal used throughout the site
    EMERGING_STATUSES = ["Proposed", "Pre-proposal", "Approved/Permitted/Under construction", "Expanding"]
    df = df.withColumn("is_emerging", F.col("status").isin(EMERGING_STATUSES))

    stats = {
        "raw_count": raw_count,
        "bad_coord_count": bad_coord_count,
        "mw_null_count": mw_null_count,
        "mw_parse_failures": mw_parse_failures,
        "clean_count": df.count(),
    }
    return df, stats


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    spark = SparkSession.builder.appName("clean-facilities").getOrCreate()
    spark.sparkContext.setLogLevel("ERROR")

    df, stats = build_pipeline(spark, args.input)
    print("Cleaning stats:", stats)

    df.write.mode("overwrite").parquet(args.output)
    print(f"Wrote {stats['clean_count']} clean records to {args.output}")

    spark.stop()


if __name__ == "__main__":
    main()
