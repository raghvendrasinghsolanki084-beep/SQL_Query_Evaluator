"""Conservative SQL validation for a disposable SQLite evaluation database."""
import re
import sqlite3

# Deliberately conservative: this project automatically executes SELECT only.
FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|TRUNCATE|ATTACH|DETACH|"
    r"PRAGMA|VACUUM|REINDEX|GRANT|REVOKE|BEGIN|COMMIT|ROLLBACK)\b",
    re.IGNORECASE,
)

def strip_sql_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql.strip()

def validate_select(sql: str) -> tuple[bool, str, str]:
    """Return (allowed, cleaned_sql, reason). Conservative by design."""
    if not isinstance(sql, str) or not sql.strip():
        return False, "", "No SQL was returned."
    cleaned = strip_sql_comments(sql).strip()
    # Allow at most one statement; permit a single trailing semicolon.
    body = cleaned[:-1].strip() if cleaned.endswith(";") else cleaned
    if ";" in body:
        return False, cleaned, "Multiple SQL statements are blocked."
    if not re.match(r"^(SELECT|WITH)\b", body, flags=re.IGNORECASE):
        return False, cleaned, "Only SELECT queries (including WITH ... SELECT) are allowed."
    if FORBIDDEN.search(body):
        return False, cleaned, "A prohibited SQL operation was detected."
    if re.search(r"\bINTO\s+OUTFILE\b", body, re.IGNORECASE):
        return False, cleaned, "File-writing SQL is blocked."
    return True, body, "Allowed for read-only evaluation."

def execute_readonly(db_path: str, sql: str, max_rows: int = 1000) -> dict:
    """Execute only validated SQL using SQLite read-only mode and a row cap."""
    allowed, cleaned, reason = validate_select(sql)
    if not allowed:
        return {"ok": False, "blocked": True, "reason": reason, "rows": [], "columns": []}
    uri = "file:" + db_path.replace("\\", "/") + "?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True, timeout=3)
        con.set_authorizer(_read_only_authorizer)
        con.set_progress_handler(lambda: 1, 100_000)  # Interrupt unusually expensive queries.
        cur = con.cursor()
        cur.execute(cleaned)
        columns = [d[0] for d in (cur.description or [])]
        rows = cur.fetchmany(max_rows + 1)
        if len(rows) > max_rows:
            con.close()
            return {"ok": False, "blocked": True, "reason": f"Result exceeded {max_rows} rows.",
                    "rows": [], "columns": columns}
        con.close()
        return {"ok": True, "blocked": False, "reason": "Executed successfully.",
                "rows": [list(r) for r in rows], "columns": columns}
    except sqlite3.Error as exc:
        return {"ok": False, "blocked": False, "reason": str(exc), "rows": [], "columns": []}

def _read_only_authorizer(action, arg1, arg2, db_name, trigger_name):
    """SQLite authorizer: reject writes and schema changes even if SQL checks miss them."""
    writes = {
        sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE,
        sqlite3.SQLITE_CREATE_INDEX, sqlite3.SQLITE_CREATE_TABLE,
        sqlite3.SQLITE_CREATE_TEMP_INDEX, sqlite3.SQLITE_CREATE_TEMP_TABLE,
        sqlite3.SQLITE_CREATE_TEMP_TRIGGER, sqlite3.SQLITE_CREATE_TEMP_VIEW,
        sqlite3.SQLITE_CREATE_TRIGGER, sqlite3.SQLITE_CREATE_VIEW,
        sqlite3.SQLITE_DROP_INDEX, sqlite3.SQLITE_DROP_TABLE,
        sqlite3.SQLITE_DROP_TEMP_INDEX, sqlite3.SQLITE_DROP_TEMP_TABLE,
        sqlite3.SQLITE_DROP_TEMP_TRIGGER, sqlite3.SQLITE_DROP_TEMP_VIEW,
        sqlite3.SQLITE_DROP_TRIGGER, sqlite3.SQLITE_DROP_VIEW,
        sqlite3.SQLITE_ALTER_TABLE, sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH,
        sqlite3.SQLITE_PRAGMA, sqlite3.SQLITE_TRANSACTION,
    }
    return sqlite3.SQLITE_DENY if action in writes else sqlite3.SQLITE_OK
