"""Validate a user-supplied metrics snapshot and apply explicit heuristic rules."""
import json
import math
from datetime import datetime

MAX_BYTES = 1024 * 1024


def analyze_db_snapshot(source):
    if len(source.encode("utf-8")) > MAX_BYTES:
        raise ValueError("Snapshot exceeds 1 MB.")
    try:
        data = json.loads(source)
    except (ValueError, RecursionError) as error:
        raise ValueError("Provide one valid JSON object.") from error
    if not isinstance(data, dict):
        raise ValueError("Snapshot must be a JSON object.")
    for key in ("database", "captured_at"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError(f"{key} must be a nonempty string.")
    try:
        captured = datetime.fromisoformat(data["captured_at"].replace("Z", "+00:00"))
        if captured.tzinfo is None:
            raise ValueError()
    except ValueError as error:
        raise ValueError("captured_at must be an ISO timestamp with timezone, e.g. 2026-09-24T10:30:00Z.") from error

    def number(obj, key, integer=False):
        value = obj.get(key)
        if type(value) not in (int, float) or (integer and type(value) is not int) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{key} must be a finite nonnegative {'integer' if integer else 'number'}.")
        return value

    current = number(data, "current_connections", True)
    maximum = number(data, "max_connections", True)
    waiting = number(data, "lock_wait_count", True)
    oldest = number(data, "oldest_lock_wait_ms")
    if maximum == 0 or current > maximum:
        raise ValueError("max_connections must be positive and at least current_connections.")
    if waiting == 0 and oldest != 0:
        raise ValueError("oldest_lock_wait_ms must be zero when lock_wait_count is zero.")
    queries = data.get("queries")
    if not isinstance(queries, list) or len(queries) > 100:
        raise ValueError("queries must be a list of at most 100 query samples (use [] if none were collected).")
    for query in queries:
        if not isinstance(query, dict) or not isinstance(query.get("query_id"), str) or not query["query_id"].strip():
            raise ValueError("Each query requires a nonempty query_id string.")
        number(query, "duration_ms")
    findings = []

    def finding(rule, title, evidence, fix):
        findings.append({"rule": rule, "severity": "HIGH", "title": title, "evidence": evidence, "suggested_fix": fix})

    utilization = current / maximum * 100
    if utilization >= 80:
        finding("DB_CONNECTION_USAGE", "High connection usage",
                f"current_connections={current}, max_connections={maximum}; usage={utilization:.2f}% (threshold >=80%).",
                "Inspect connection pool usage and connection lifecycle before changing capacity.")
    for index, query in enumerate(queries):
        if query["duration_ms"] >= 1000:
            finding("DB_SLOW_QUERY", "Slow query sample",
                    f"queries[{index}]: query_id={query['query_id']}, duration_ms={query['duration_ms']} (threshold >=1000 ms).",
                    "Inspect the query plan and relevant indexes; compare with its normal duration.")
    if waiting > 0 and oldest >= 1000:
        finding("DB_LOCK_WAIT", "Long lock wait",
                f"lock_wait_count={waiting}, oldest_lock_wait_ms={oldest} (threshold >=1000 ms).",
                "Inspect blocking transactions and transaction duration before taking corrective action.")
    return {"version": 1, "database": data["database"], "captured_at": captured.isoformat(),
            "connection_usage_percent": round(utilization, 2), "query_samples": len(queries),
            "findings": findings, "thresholds": {"connection_percent": 80, "query_ms": 1000, "lock_wait_ms": 1000}}
