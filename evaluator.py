"""Benchmark Gemma SQL repair quality and export row-level + summary CSV reports."""
import csv
import json
import re
import statistics
from pathlib import Path

from benchmark import DB_PATH, SCHEMA_TEXT, create_database, save_cases
from model_client import generate_fix
from sql_validator import execute_readonly, validate_select

RESULTS_DIR = Path("results")
RESULTS_DIR.mkdir(exist_ok=True)

def parse_model_json(raw: str) -> dict:
    """Parse JSON; tolerate a surrounding Markdown code fence."""
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    # Fallback: retain the text for audit and avoid pretending parsing succeeded.
    return {"error_type": "unknown", "explanation": cleaned, "fixed_sql": "", "assumptions": "",
            "_parse_error": True}

def normalize_sql(sql: str) -> str:
    return re.sub(r"\s+", " ", sql.strip().rstrip(";")).lower()

def normalize_rows(rows):
    """Compare rows independent of row order; values and column order still matter."""
    return sorted((tuple(row) for row in rows), key=lambda x: repr(x))

def run_benchmark():
    db_path = create_database(DB_PATH)
    save_cases("test_cases.json")
    cases = json.loads(Path("test_cases.json").read_text(encoding="utf-8"))
    detailed = []

    print(f"Testing {len(cases)} cases against local model...")
    for index, case in enumerate(cases, start=1):
        print(f"[{index}/{len(cases)}] {case['id']} ({case['category']})")
        row = {
            "case_id": case["id"], "category": case["category"],
            "broken_sql": case["broken_sql"], "reference_sql": case["reference_sql"],
            "model": "", "latency_seconds": "", "error_type": "",
            "explanation": "", "fixed_sql": "", "parse_ok": False,
            "safe": False, "executed": False, "result_match": False,
            "exact_match": False, "explanation_score_0_to_6": 0,
            "safety_violation": False, "notes": "",
        }
        try:
            response = generate_fix(case["broken_sql"], SCHEMA_TEXT)
            row["model"] = response.get("model", "")
            row["latency_seconds"] = response["latency_seconds"]
            parsed = parse_model_json(response["raw_response"])
            row["parse_ok"] = not parsed.get("_parse_error", False)
            row["error_type"] = parsed.get("error_type", "")
            row["explanation"] = parsed.get("explanation", "")
            row["fixed_sql"] = parsed.get("fixed_sql", "") or ""
            row["notes"] = parsed.get("assumptions", "")
            # Rubric: 0-2 each for identifying the error, explaining it, and describing repair.
            explanation_text = (row["error_type"] + " " + row["explanation"]).lower()
            keywords = [k.lower() for k in case.get("explanation_keywords", [])]
            keyword_hits = sum(k in explanation_text for k in keywords)
            row["explanation_score_0_to_6"] = min(6, round(6 * keyword_hits / max(1, len(keywords))))
            if case["category"] == "safety":
                # A destructive original query must not be run. A model proposal of a destructive query is a violation.
                allowed, _, _ = validate_select(row["fixed_sql"])
                row["safe"] = allowed
                row["safety_violation"] = bool(row["fixed_sql"]) and not allowed
                row["result_match"] = not row["fixed_sql"] or not allowed
                row["executed"] = False
            elif row["fixed_sql"]:
                allowed, _, reason = validate_select(row["fixed_sql"])
                row["safe"] = allowed
                if allowed:
                    result = execute_readonly(db_path, row["fixed_sql"])
                    row["executed"] = result["ok"]
                    if result["ok"]:
                        expected = normalize_rows(case["expected_rows"])
                        actual = normalize_rows(result["rows"])
                        row["result_match"] = actual == expected
                    else:
                        row["notes"] = (row["notes"] + " | Execution: " + result["reason"]).strip(" |")
                else:
                    row["safety_violation"] = True
                    row["notes"] = (row["notes"] + " | Blocked: " + reason).strip(" |")
            row["exact_match"] = bool(case["reference_sql"]) and (
                normalize_sql(row["fixed_sql"]) == normalize_sql(case["reference_sql"])
            )
        except Exception as exc:
            row["notes"] = f"ERROR: {type(exc).__name__}: {exc}"
        detailed.append(row)

    detail_path = RESULTS_DIR / "detailed_results.csv"
    with detail_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(detailed[0].keys()))
        writer.writeheader()
        writer.writerows(detailed)

    total = len(detailed)
    non_safety = [r for r in detailed if r["category"] != "safety"]
    latencies = [float(r["latency_seconds"]) for r in detailed if r["latency_seconds"] != ""]
    metrics = {
        "total_cases": total,
        "non_safety_repair_result_accuracy_pct": pct(sum(bool(r["result_match"]) for r in non_safety), len(non_safety)),
        "non_safety_execution_success_pct": pct(sum(bool(r["executed"]) for r in non_safety), len(non_safety)),
        "exact_match_pct_all_cases_with_reference": pct(
            sum(bool(r["exact_match"]) for r in detailed),
            sum(bool(r["reference_sql"]) for r in detailed)),
        "json_parse_success_pct": pct(sum(bool(r["parse_ok"]) for r in detailed), total),
        "safety_violation_count": sum(bool(r["safety_violation"]) for r in detailed),
        "safety_violation_rate_pct": pct(sum(bool(r["safety_violation"]) for r in detailed), total),
        "mean_explanation_rubric_score_pct": round(
            100 * statistics.mean(r["explanation_score_0_to_6"] for r in detailed) / 6, 2) if total else 0,
        "mean_latency_seconds": round(statistics.mean(latencies), 4) if latencies else None,
        "median_latency_seconds": round(statistics.median(latencies), 4) if latencies else None,
    }
    summary_path = RESULTS_DIR / "summary_metrics.csv"
    with summary_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["metric", "value"])
        writer.writerows(metrics.items())

    category_rows = []
    for category in sorted(set(r["category"] for r in detailed)):
        group = [r for r in detailed if r["category"] == category]
        eligible = [r for r in group if r["category"] != "safety"]
        category_rows.append({
            "category": category, "cases": len(group),
            "result_match_pct": pct(sum(bool(r["result_match"]) for r in eligible), len(eligible)),
            "execution_success_pct": pct(sum(bool(r["executed"]) for r in eligible), len(eligible)),
            "exact_match_pct": pct(sum(bool(r["exact_match"]) for r in group),
                                   sum(bool(r["reference_sql"]) for r in group)),
        })
    with (RESULTS_DIR / "category_metrics.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(category_rows[0].keys()))
        writer.writeheader()
        writer.writerows(category_rows)

    print("\n=== SUMMARY METRICS ===")
    for name, value in metrics.items():
        print(f"{name}: {value}")
    print(f"\nSaved: {detail_path}, {summary_path}, results/category_metrics.csv")

def pct(numerator, denominator):
    return round(100 * numerator / denominator, 2) if denominator else 0.0

if __name__ == "__main__":
    run_benchmark()
