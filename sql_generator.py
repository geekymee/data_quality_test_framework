import logging
from typing import Any

logger = logging.getLogger(__name__)



def _qualify(database: str, table: str) -> str:
    return f'"{database}"."{table}"'


def _col(name: str) -> str:
    return f'"{name}"'



def sql_not_null_single(database: str, table: str, column: str, max_rows: int = 1000) -> str:
    sql = f"""
SELECT *,
       'not_null_single'          AS _test_type,
       {_col(column)!r}           AS _failed_column
FROM   {_qualify(database, table)}
WHERE  {_col(column)} IS NULL
LIMIT  {max_rows}
""".strip()
    logger.debug(f"[not_null_single] column={column}\n{sql}")
    return sql



def sql_not_null_composite(database: str, table: str, columns: list[str], max_rows: int = 1000) -> str:
    null_checks = " OR ".join(f"{_col(c)} IS NULL" for c in columns)
    case_parts  = [
        f"CASE WHEN {_col(c)} IS NULL THEN '{c}|' ELSE '' END"
        for c in columns
    ]
    failed_col_expr = " || ".join(case_parts)

    sql = f"""
SELECT *,
       'not_null_composite'       AS _test_type,
       ({failed_col_expr})        AS _failed_column
FROM   {_qualify(database, table)}
WHERE  {null_checks}
LIMIT  {max_rows}
""".strip()
    logger.debug(f"[not_null_composite] columns={columns}\n{sql}")
    return sql



def sql_no_duplicates(database: str, table: str, columns: list[str], max_rows: int = 1000) -> str:
    col_list   = ", ".join(_col(c) for c in columns)
    key_concat = " || '|' || ".join(f"CAST({_col(c)} AS VARCHAR)" for c in columns)

    sql = f"""
WITH counted AS (
    SELECT *,
           COUNT(*) OVER (PARTITION BY {col_list}) AS _dup_count,
           ({key_concat})                           AS _duplicate_key
    FROM   {_qualify(database, table)}
)
SELECT *,
       'no_duplicates'   AS _test_type,
       '{', '.join(columns)}' AS _failed_column
FROM   counted
WHERE  _dup_count > 1
ORDER  BY _duplicate_key
LIMIT  {max_rows}
""".strip()
    logger.debug(f"[no_duplicates] columns={columns}\n{sql}")
    return sql



_DTYPE_EXPRESSIONS: dict[str, str] = {
    "integer":   "TRY_CAST({col} AS BIGINT) IS NULL AND {col} IS NOT NULL",
    "decimal":   "TRY_CAST({col} AS DOUBLE) IS NULL AND {col} IS NOT NULL",
    "date":      "TRY(DATE_PARSE(CAST({col} AS VARCHAR), '%Y-%m-%d')) IS NULL AND {col} IS NOT NULL",
    "timestamp": "TRY_CAST({col} AS TIMESTAMP) IS NULL AND {col} IS NOT NULL",
    "boolean":   (
        "LOWER(CAST({col} AS VARCHAR)) NOT IN ('true','false','1','0') "
        "AND {col} IS NOT NULL"
    ),
    "varchar":   "FALSE",
}


def sql_datatype_check(
    database: str, table: str, column: str, expected_type: str, max_rows: int = 1000
) -> str:
    if expected_type not in _DTYPE_EXPRESSIONS:
        raise ValueError(
            f"Unsupported expected_type '{expected_type}'. "
            f"Choose from: {list(_DTYPE_EXPRESSIONS)}"
        )
    condition = _DTYPE_EXPRESSIONS[expected_type].format(col=_col(column))

    sql = f"""
SELECT *,
       'datatype_mismatch'        AS _test_type,
       {_col(column)!r}           AS _failed_column,
       '{expected_type}'          AS _expected_type,
       CAST({_col(column)} AS VARCHAR) AS _actual_value
FROM   {_qualify(database, table)}
WHERE  {condition}
LIMIT  {max_rows}
""".strip()
    logger.debug(f"[datatype_check] column={column}, expected={expected_type}\n{sql}")
    return sql



def sql_fetch_key_columns(database: str, table: str, columns: list[str]) -> str:
    col_list = ", ".join(_col(c) for c in columns)
    sql = f"""
SELECT {col_list}
FROM   {_qualify(database, table)}
""".strip()
    logger.debug(f"[fetch_key_columns] columns={columns}\n{sql}")
    return sql



def build_all_queries(
    database: str,
    table: str,
    not_null_single: list[dict],
    not_null_composite: list[dict],
    no_duplicates: list[dict],
    datatype_checks: list[dict],
    required_rows_config: dict,
    max_rows: int = 1000,
) -> dict[str, Any]:
    queries: dict[str, Any] = {}

    for cfg in not_null_single:
        queries[cfg["test_name"]] = {
            "test_name": cfg["test_name"],
            "test_type": "not_null_single",
            "sql": sql_not_null_single(database, table, cfg["column"], max_rows),
            "meta": {"column": cfg["column"]},
        }

    for cfg in not_null_composite:
        queries[cfg["test_name"]] = {
            "test_name": cfg["test_name"],
            "test_type": "not_null_composite",
            "sql": sql_not_null_composite(database, table, cfg["columns"], max_rows),
            "meta": {"columns": cfg["columns"]},
        }

    for cfg in no_duplicates:
        queries[cfg["test_name"]] = {
            "test_name": cfg["test_name"],
            "test_type": "no_duplicates",
            "sql": sql_no_duplicates(database, table, cfg["columns"], max_rows),
            "meta": {"columns": cfg["columns"]},
        }

    for cfg in datatype_checks:
        queries[cfg["test_name"]] = {
            "test_name": cfg["test_name"],
            "test_type": "datatype_mismatch",
            "sql": sql_datatype_check(
                database, table, cfg["column"], cfg["expected_type"], max_rows
            ),
            "meta": {"column": cfg["column"], "expected_type": cfg["expected_type"]},
        }

    if required_rows_config.get("enabled"):
        match_cols = required_rows_config["match_columns"]
        queries["__required_rows_fetch__"] = {
            "test_name": "__required_rows_fetch__",
            "test_type": "required_rows",
            "sql": sql_fetch_key_columns(database, table, match_cols),
            "meta": {
                "csv_path": required_rows_config["csv_path"],
                "match_columns": match_cols,
            },
        }

    logger.info(f"Generated {len(queries)} test queries for {database}.{table}")
    return queries
