

import logging
import pandas as pd
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)




def run_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")




def make_result_record(
    test_name: str,
    test_type: str,
    status: str,
    violation_count: int = 0,
    s3_uri: str | None = None,
    error_message: str | None = None,
    meta: dict | None = None,
) -> dict:
    return {
        "test_name":       test_name,
        "test_type":       test_type,
        "status":          status,
        "violation_count": violation_count,
        "output_s3_uri":   s3_uri or "",
        "error_message":   error_message or "",
        "meta":            str(meta or {}),
        "run_at":          run_timestamp(),
    }


def summarise_results(results: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(results)


def enrich_violation_df(df: pd.DataFrame, test_name: str, test_type: str) -> pd.DataFrame:
    df = df.copy()
    df.insert(0, "_test_name", test_name)
    df.insert(1, "_run_at", run_timestamp())
    if "_test_type" not in df.columns:
        df.insert(2, "_test_type", test_type)
    return df


def has_violations(df: pd.DataFrame) -> bool:
    return len(df) > 0



def find_missing_rows(
    required_df: pd.DataFrame,
    table_df: pd.DataFrame,
    match_columns: list[str],
) -> pd.DataFrame:
    req = required_df[match_columns].astype(str).copy()
    tbl = table_df[match_columns].astype(str).copy()

    req["_key"] = req[match_columns].apply(lambda r: "|".join(r.values), axis=1)
    tbl["_key"] = tbl[match_columns].apply(lambda r: "|".join(r.values), axis=1)

    missing_keys = set(req["_key"]) - set(tbl["_key"])
    if not missing_keys:
        return pd.DataFrame(columns=required_df.columns)

    req_with_key = required_df.copy()
    req_with_key["_key"] = req["_key"]
    missing = req_with_key[req_with_key["_key"].isin(missing_keys)].drop(columns=["_key"])
    logger.warning(f"Found {len(missing)} missing required row(s).")
    return missing



def build_s3_key(prefix: str, test_name: str, timestamp: str) -> str:
    return f"{prefix.rstrip('/')}/{timestamp}/{test_name}.csv"


def build_summary_s3_key(prefix: str, timestamp: str) -> str:
    return f"{prefix.rstrip('/')}/{timestamp}/_summary.csv"



def parse_athena_schema(describe_df: pd.DataFrame) -> dict[str, str]:
    schema: dict[str, str] = {}
    for _, row in describe_df.iterrows():
        col_name  = str(row.iloc[0]).strip()
        data_type = str(row.iloc[1]).strip()
        if col_name.startswith("#") or col_name == "":
            continue
        schema[col_name] = data_type
    return schema


def configure_logging(level: str = "INFO") -> None:
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
