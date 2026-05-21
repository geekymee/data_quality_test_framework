import sys
import logging
import pandas as pd

from config.config import (
    TABLE_CONFIG,
    S3_OUTPUT_CONFIG,
    NOT_NULL_SINGLE,
    NOT_NULL_COMPOSITE,
    NO_DUPLICATES,
    DATATYPE_CHECKS,
    REQUIRED_ROWS_CONFIG,
    SETTINGS,
)
from connections import get_connectors
from functions import (
    configure_logging,
    make_result_record,
    enrich_violation_df,
    has_violations,
    find_missing_rows,
    build_s3_key,
    build_summary_s3_key,
    run_timestamp,
    summarise_results,
)
from sql_generator import build_all_queries

logger = logging.getLogger(__name__)

import os
AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "ap-south-1")

def run_tests() -> None:
    configure_logging(SETTINGS["log_level"])
    ts = run_timestamp()

    logger.info(f"Table  : {TABLE_CONFIG['database']}.{TABLE_CONFIG['table']}")
    logger.info(f"Run ID : {ts}")

    athena, s3 = get_connectors(
        region=AWS_REGION,
        athena_s3_output=S3_OUTPUT_CONFIG["athena_query_results"],
    )

    queries = build_all_queries(
        database=TABLE_CONFIG["database"],
        table=TABLE_CONFIG["table"],
        not_null_single=NOT_NULL_SINGLE,
        not_null_composite=NOT_NULL_COMPOSITE,
        no_duplicates=NO_DUPLICATES,
        datatype_checks=DATATYPE_CHECKS,
        required_rows_config=REQUIRED_ROWS_CONFIG,
        max_rows=SETTINGS["max_violations_per_test"],
    )

    results: list[dict] = []
    bucket = S3_OUTPUT_CONFIG["bucket"]
    prefix = S3_OUTPUT_CONFIG["prefix"]

    for test_name, query_info in queries.items():

        if test_name == "__required_rows_fetch__":
            continue

        test_type = query_info["test_type"]
        sql       = query_info["sql"]
        meta      = query_info["meta"]

        logger.info(f"Running [{test_type}] {test_name} …")

        try:
            violations_df = athena.run_query(sql, TABLE_CONFIG["database"])
        except Exception as exc:
            logger.error(f"  ERROR executing {test_name}: {exc}")
            results.append(
                make_result_record(test_name, test_type, "ERROR", error_message=str(exc), meta=meta)
            )
            if SETTINGS["fail_fast"]:
                break
            continue

        if has_violations(violations_df):
            violations_df = enrich_violation_df(violations_df, test_name, test_type)
            key = build_s3_key(prefix, test_name, ts)
            uri = s3.upload_dataframe_as_csv(violations_df, bucket, key)
            logger.warning(f"  FAIL — {len(violations_df)} violation(s) → {uri}")
            results.append(
                make_result_record(
                    test_name, test_type, "FAIL",
                    violation_count=len(violations_df),
                    s3_uri=uri,
                    meta=meta,
                )
            )
        else:
            logger.info("  PASS — no violations found.")
            results.append(make_result_record(test_name, test_type, "PASS", meta=meta))

        if SETTINGS["fail_fast"] and results[-1]["status"] == "FAIL":
            logger.warning("fail_fast=True — stopping after first failure.")
            break

    if REQUIRED_ROWS_CONFIG.get("enabled") and "__required_rows_fetch__" in queries:
        _run_required_rows_check(queries, athena, s3, bucket, prefix, ts, results)

    summary_df  = summarise_results(results)
    summary_key = build_summary_s3_key(prefix, ts)
    summary_uri = s3.upload_dataframe_as_csv(summary_df, bucket, summary_key)

    _print_summary(summary_df, summary_uri)




def _run_required_rows_check(
    queries: dict,
    athena,
    s3,
    bucket: str,
    prefix: str,
    ts: str,
    results: list[dict],
) -> None:
    rr_query      = queries["__required_rows_fetch__"]
    meta          = rr_query["meta"]
    csv_path      = meta["csv_path"]
    match_columns = meta["match_columns"]
    test_name     = "required_rows_check"
    test_type     = "required_rows"

    logger.info(f"Running [required_rows] {test_name} …")

    try:
        required_df = s3.read_local_csv(csv_path)
        table_df    = athena.run_query(rr_query["sql"], TABLE_CONFIG["database"])
        missing_df  = find_missing_rows(required_df, table_df, match_columns)
    except Exception as exc:
        logger.error(f"  ERROR in required_rows_check: {exc}")
        results.append(make_result_record(test_name, test_type, "ERROR", error_message=str(exc), meta=meta))
        return

    if has_violations(missing_df):
        missing_df = enrich_violation_df(missing_df, test_name, test_type)
        key = build_s3_key(prefix, test_name, ts)
        uri = s3.upload_dataframe_as_csv(missing_df, bucket, key)
        logger.warning(f"  FAIL — {len(missing_df)} required row(s) missing → {uri}")
        results.append(
            make_result_record(test_name, test_type, "FAIL",
                               violation_count=len(missing_df), s3_uri=uri, meta=meta)
        )
    else:
        logger.info("  PASS — all required rows present.")
        results.append(make_result_record(test_name, test_type, "PASS", meta=meta))


def _print_summary(summary_df: pd.DataFrame, summary_uri: str) -> None:
    total  = len(summary_df)
    passed = (summary_df["status"] == "PASS").sum()
    failed = (summary_df["status"] == "FAIL").sum()
    errors = (summary_df["status"] == "ERROR").sum()

    logger.info("")
    logger.info("=" * 60)
    logger.info("TEST RUN COMPLETE")
    logger.info(f"  Total  : {total}")
    logger.info(f"  PASS   : {passed}")
    logger.info(f"  FAIL   : {failed}")
    logger.info(f"  ERROR  : {errors}")
    logger.info(f"  Summary: {summary_uri}")
    logger.info("=" * 60)

    if failed or errors:
        print(summary_df[summary_df["status"] != "PASS"].to_string(index=False))
        sys.exit(1)


if __name__ == "__main__":
    run_tests()
