"""Deterministic extraction for timestamp + level + message text logs.

No code execution, network calls or inferred root causes. Unrecognized formats
remain unclassified. Repetition means exact message equality after stripping
the timestamp and level, not proof that events share a cause.
"""
import re
import json
from collections import Counter
from datetime import datetime

MAX_LOG_BYTES = 1024 * 1024
MAX_LOG_LINES = 10000
TIMESTAMP = re.compile(r"^\[?(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:\d{2})?)\]?\s*")
LEVEL = re.compile(r"^\[?(DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL|FATAL)\]?(?=\s|:|$)[:\s]*", re.I)


def parse_json_line(raw):
    """Primary keys take precedence over aliases, including invalid values."""
    try:
        data = json.loads(raw)
    except (ValueError, RecursionError):
        return raw, "UNKNOWN", None, "Malformed or excessively nested JSON."
    if not isinstance(data, dict):
        return raw, "UNKNOWN", None, "Expected one JSON object per line."
    message = data.get("message", data.get("msg"))
    level = data.get("level", data.get("severity"))
    if not isinstance(message, str) or not message.strip():
        return raw, "UNKNOWN", None, "Missing or invalid message/msg string."
    if not isinstance(level, str) or level.strip().upper() not in {"DEBUG", "INFO", "WARN", "WARNING", "ERROR", "CRITICAL", "FATAL"}:
        return message.strip(), "UNKNOWN", None, "Missing or unsupported level/severity."
    level = level.strip().upper()
    level = {"WARN": "WARNING", "FATAL": "CRITICAL"}.get(level, level)
    value = data.get("timestamp", data.get("time", data.get("@timestamp")))
    parsed = None
    issue = None
    if value is not None:
        try:
            if not isinstance(value, str) or not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:\d{2})?", value
            ):
                raise ValueError()
            parsed = datetime.fromisoformat(value.replace(",", ".").replace("Z", "+00:00"))
        except ValueError:
            issue = "Invalid timestamp; expected ISO date/time (numeric epochs are unsupported)."
    return message.strip(), level, parsed, issue


def analyze_logs(source):
    if not source.strip():
        raise ValueError("Provide nonempty logs.")
    if len(source.encode("utf-8")) > MAX_LOG_BYTES:
        raise ValueError("Logs exceed the 1 MB limit.")
    lines = source.splitlines()
    if len(lines) > MAX_LOG_LINES:
        raise ValueError("Logs exceed the 10,000 line limit.")
    counts = Counter()
    groups = {}
    timestamp_count = naive_count = 0
    evidence = []
    json_lines = diagnostic_count = 0
    diagnostics = []
    for number, raw in enumerate(lines, 1):
        if not raw.strip():
            continue
        message = raw.strip()
        timestamp = None
        if message.startswith(("{", "[")) and not LEVEL.match(message) and not TIMESTAMP.match(message):
            json_lines += 1
            message, level, parsed, issue = parse_json_line(message)
            if issue:
                diagnostic_count += 1
                if len(diagnostics) < 100:
                    diagnostics.append({"line": number, "message": issue})
            if parsed is not None:
                timestamp = parsed.isoformat()
                timestamp_count += 1
                naive_count += parsed.tzinfo is None
        else:
            match = TIMESTAMP.match(message)
            if match:
                try:
                    parsed = datetime.fromisoformat(match[1].replace(",", ".").replace("Z", "+00:00"))
                    timestamp = parsed.isoformat()
                    timestamp_count += 1
                    naive_count += parsed.tzinfo is None
                    message = message[match.end():]
                except ValueError:
                    pass
            match = LEVEL.match(message)
            level = "UNKNOWN"
            if match:
                level = {"WARN": "WARNING", "FATAL": "CRITICAL"}.get(match[1].upper(), match[1].upper())
                message = message[match.end():].strip()
        counts[level] += 1
        if level in {"ERROR", "CRITICAL"}:
            key = (level, message)
            group = groups.setdefault(key, {"level": level, "message": message, "count": 0, "lines": []})
            group["count"] += 1
            if len(group["lines"]) < 10:
                group["lines"].append(number)
            if len(evidence) < 100:
                evidence.append({"line": number, "level": level, "timestamp": timestamp, "message": message})
    ranked = sorted(groups.values(), key=lambda group: (-group["count"], group["lines"][0]))
    return {
        "version": 2, "total_lines": len(lines), "nonempty_lines": sum(counts.values()),
        "json_lines": json_lines, "diagnostic_count": diagnostic_count,
        "diagnostics": diagnostics, "diagnostics_truncated": diagnostic_count > 100,
        "counts": dict(counts), "timestamp_count": timestamp_count,
        "timestamps_without_timezone": naive_count,
        "error_count": counts["ERROR"] + counts["CRITICAL"],
        "groups": ranked[:100], "groups_truncated": len(ranked) > 100,
        "evidence": evidence, "evidence_truncated": counts["ERROR"] + counts["CRITICAL"] > 100,
    }
