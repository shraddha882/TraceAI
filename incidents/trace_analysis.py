"""TraceAI snapshot schema v1; deterministic span checks, not OTLP ingestion."""
import json
import math
from datetime import datetime

from .db_forms import DatabaseEvidenceForm


def analyze_trace_snapshot(source):
    if len(source.encode("utf-8")) > 1024 * 1024:
        raise ValueError("Snapshot exceeds 1 MB.")
    try:
        data = json.loads(source)
    except (ValueError, RecursionError) as error:
        raise ValueError("Provide one valid JSON object.") from error
    spans = data.get("spans") if isinstance(data, dict) else None
    if not isinstance(spans, list) or not 1 <= len(spans) <= 100:
        raise ValueError("spans must contain 1 to 100 span objects.")
    findings, normalized, seen, services = [], [], set(), {}
    failed = slow = 0
    for index, span in enumerate(spans):
        prefix = f"spans[{index}]"
        if not isinstance(span, dict):
            raise ValueError(f"{prefix} must be an object.")
        for key in ("trace_id", "span_id", "service", "operation", "started_at", "status"):
            if not isinstance(span.get(key), str) or not span[key].strip() or len(span[key]) > 250:
                raise ValueError(f"{prefix}.{key} must be a nonempty string up to 250 characters.")
        identity = (span["trace_id"], span["span_id"])
        if identity in seen:
            raise ValueError(f"{prefix}: duplicate trace_id/span_id pair.")
        seen.add(identity)
        try:
            started = datetime.fromisoformat(span["started_at"].replace("Z", "+00:00"))
            if started.tzinfo is None:
                raise ValueError()
        except ValueError as error:
            raise ValueError(f"{prefix}.started_at requires an ISO timestamp with timezone.") from error
        duration = span.get("duration_ms")
        try:
            valid = type(duration) in (int, float) and math.isfinite(duration) and duration >= 0
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError(f"{prefix}.duration_ms must be finite and nonnegative.")
        status = span["status"].upper().strip()
        if status not in {"OK", "ERROR", "UNSET"}:
            raise ValueError(f"{prefix}.status must be OK, ERROR or UNSET.")
        record = {key: span[key] for key in ("trace_id", "span_id", "service", "operation")}
        record.update(started_at=started.isoformat(), duration_ms=duration, status=status, source_index=index)
        normalized.append(record)
        summary = services.setdefault(span["service"], {"service": span["service"], "spans": 0, "failed": 0, "slow": 0})
        summary["spans"] += 1
        if status == "ERROR":
            failed += 1
            summary["failed"] += 1
            findings.append({**record, "rule": "TRACE_ERROR", "title": "Span reported an error", "severity": "HIGH",
                "evidence": f"{prefix}.status=ERROR", "suggested_check": "Inspect this span's service logs using the trace ID; check upstream and downstream evidence."})
        if duration >= 1000:
            slow += 1
            summary["slow"] += 1
            findings.append({**record, "rule": "TRACE_SLOW", "title": "Slow span", "severity": "HIGH",
                "evidence": f"{prefix}.duration_ms={duration}; threshold >=1000 ms.", "suggested_check": "Compare duration with this operation's baseline and inspect dependency timing."})
    return {"version": 1, "span_count": len(spans), "trace_count": len({item[0] for item in seen}),
            "failed_spans": failed, "slow_spans": slow, "slow_threshold_ms": 1000,
            "services": list(services.values()), "spans": normalized, "findings": findings}


class TraceEvidenceForm(DatabaseEvidenceForm):
    analyzer = staticmethod(analyze_trace_snapshot)
