import os
from datetime import datetime, timezone

CONFIG_DIR  = os.path.join(os.path.dirname(__file__), "config")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.py")

TABLE_CONFIG = {
    "database":    "sample_table",
    "table":       "input_table",
    "table_type":  "ICEBERG",
    "s3_location": "s3://input-table/iceberg/",
}

S3_OUTPUT_CONFIG = {
    "bucket":               "outputcsv-bucket-demo",
    "prefix":               "results_folder/",
    "athena_query_results": "s3://outputcsv-bucket-demo/athena-temp/",
}

SETTINGS = {
    "fail_fast":               False,
    "max_violations_per_test": 1000,
    "log_level":               "INFO",
}

# =============================================================================

VALID_TYPES = ["integer", "decimal", "timestamp", "date", "boolean", "varchar"]

AVAILABLE_TESTS = {
    "1": "not_null_single",
    "2": "not_null_composite",
    "3": "no_duplicates",
    "4": "datatype_checks",
    "5": "required_rows",
}

def prompt(msg, default=""):
    suffix = f" [{default}]" if default else ""
    val = input(f"  {msg}{suffix}: ").strip()
    return val if val else default

def prompt_yes_no(question, default=False):
    hint = "Y/n" if default else "y/N"
    while True:
        ans = input(f"  {question} [{hint}]: ").strip().lower()
        if ans == "":            return default
        if ans in ("y", "yes"): return True
        if ans in ("n", "no"):  return False
        print("    Please enter y or n.")

def prompt_columns(label, multi=True):
    hint = "comma-separated" if multi else "single column"
    raw  = input(f"  Column(s) ({hint}) for {label}: ").strip()
    cols = [c.strip() for c in raw.split(",") if c.strip()]
    if not cols:
        print("    No columns entered — skipping.")
    return cols

def prompt_datatype(column):
    print(f"    Valid types: {', '.join(VALID_TYPES)}")
    while True:
        dtype = input(f"    Expected type for '{column}': ").strip().lower()
        if dtype in VALID_TYPES:
            return dtype
        print(f"    '{dtype}' is not valid.")

def build_not_null_single():
    print("\n  ── Not-null checks (single column) ──")
    entries = []
    while True:
        cols = prompt_columns("not-null check", multi=False)
        if cols:
            col = cols[0]
            entries.append({"test_name": f"check_{col}_not_null", "column": col})
            print(f"    check_{col}_not_null")
        if not prompt_yes_no("Add another?"):
            break
    return entries

def build_not_null_composite():
    print("\n  ── Not-null checks (composite columns) ──")
    entries = []
    while True:
        name = prompt("Check name (e.g. order_fields)")
        cols = prompt_columns(f"'{name}'", multi=True)
        if cols:
            entries.append({"test_name": f"check_{name}_not_null", "columns": cols})
            print(f"    check_{name}_not_null -> {cols}")
        if not prompt_yes_no("Add another?"):
            break
    return entries

def build_no_duplicates():
    print("\n  ── No-duplicates checks ──")
    entries = []
    while True:
        name = prompt("Check name (e.g. id_unique)")
        cols = prompt_columns(f"'{name}'", multi=True)
        if cols:
            entries.append({"test_name": f"check_{name}", "columns": cols})
            print(f"    check_{name} -> {cols}")
        if not prompt_yes_no("Add another?"):
            break
    return entries

def build_datatype_checks():
    print("\n  ── Datatype checks ──")
    entries = []
    while True:
        cols = prompt_columns("datatype check", multi=False)
        if cols:
            col   = cols[0]
            dtype = prompt_datatype(col)
            entries.append({
                "test_name":     f"check_{col}_is_{dtype}",
                "column":        col,
                "expected_type": dtype,
            })
            print(f"    check_{col}_is_{dtype}")
        if not prompt_yes_no("Add another?"):
            break
    return entries

def build_required_rows():
    print("\n  ── Required rows check ──")
    csv_path   = prompt("Path to reference CSV", default="config/required_rows.csv")
    match_cols = prompt_columns("match columns (primary key)", multi=True)
    return {"enabled": True, "csv_path": csv_path, "match_columns": match_cols}

def select_tests():
    print("\nAvailable test types:")
    for k, v in AVAILABLE_TESTS.items():
        print(f"  [{k}] {v}")
    raw = input("\n  Which tests to configure? (e.g. 1,2,3,4 or 'all'): ").strip().lower()
    if raw == "all":
        return list(AVAILABLE_TESTS.values())
    selected = []
    for token in raw.split(","):
        token = token.strip()
        if token in AVAILABLE_TESTS:
            selected.append(AVAILABLE_TESTS[token])
        else:
            print(f"  '{token}' is not valid — skipping.")
    return selected

def _repr_dict(d):
    pad   = "    "
    lines = ["{"]
    for k, v in d.items():
        lines.append(f"{pad}{repr(k)}: {repr(v)},")
    lines.append("}")
    return "\n".join(lines)

def _repr_list_of_dicts(data):
    if not data:
        return "[]"
    pad   = "    "
    lines = ["["]
    for item in data:
        lines.append(f"{pad}{{")
        for k, v in item.items():
            lines.append(f"{pad}    {repr(k)}: {repr(v)},")
        lines.append(f"{pad}}},")
    lines.append("]")
    return "\n".join(lines)


def write_config(not_null_single, not_null_composite, no_duplicates,
                 datatype_checks, required_rows):
    os.makedirs(CONFIG_DIR, exist_ok=True)

    init_path = os.path.join(CONFIG_DIR, "__init__.py")
    if not os.path.exists(init_path):
        open(init_path, "w").close()

    rr = required_rows
    ts = datetime.now(timezone.utc).isoformat()

    sections = [
        f"# Generated : {ts}",
        f"TABLE_CONFIG = {_repr_dict(TABLE_CONFIG)}",
        "",
        f"S3_OUTPUT_CONFIG = {_repr_dict(S3_OUTPUT_CONFIG)}",
        "",
        f"NOT_NULL_SINGLE = {_repr_list_of_dicts(not_null_single)}",
        "",
        f"NOT_NULL_COMPOSITE = {_repr_list_of_dicts(not_null_composite)}",
        "",
        f"NO_DUPLICATES = {_repr_list_of_dicts(no_duplicates)}",
        "",
        f"DATATYPE_CHECKS = {_repr_list_of_dicts(datatype_checks)}",
        "",
        "REQUIRED_ROWS_CONFIG = {",
        f"    'enabled':       {rr.get('enabled', False)},",
        f"    'csv_path':      {repr(rr.get('csv_path', ''))},",
        f"    'match_columns': {repr(rr.get('match_columns', []))},",
        "}",
        "",
    ]

    with open(CONFIG_PATH, "w") as f:
        f.write("\n".join(sections))

    print(f"\n  config/config.py written -> {CONFIG_PATH}")


def main():
    print(f"  Table : {TABLE_CONFIG['database']}.{TABLE_CONFIG['table']}")
    print(f"  Bucket: {S3_OUTPUT_CONFIG['bucket']}")
    print()

    chosen = select_tests()
    if not chosen:
        print("\n  No tests selected. Exiting.")
        return

    builders = {
        "not_null_single":    build_not_null_single,
        "not_null_composite": build_not_null_composite,
        "no_duplicates":      build_no_duplicates,
        "datatype_checks":    build_datatype_checks,
    }

    not_null_single    = []
    not_null_composite = []
    no_duplicates      = []
    datatype_checks    = []
    required_rows      = {"enabled": False, "csv_path": "", "match_columns": []}

    for test_key in chosen:
        if test_key == "required_rows":
            required_rows = build_required_rows()
        else:
            data = builders[test_key]()
            if test_key == "not_null_single":    not_null_single    = data
            if test_key == "not_null_composite": not_null_composite = data
            if test_key == "no_duplicates":      no_duplicates      = data
            if test_key == "datatype_checks":    datatype_checks    = data

    write_config(
        not_null_single=not_null_single,
        not_null_composite=not_null_composite,
        no_duplicates=no_duplicates,
        datatype_checks=datatype_checks,
        required_rows=required_rows,
    )

    print("  Done. Run  python run_tests.py  to execute the test suite.")


if __name__ == "__main__":
    main()