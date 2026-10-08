"""Read-only temporal correlation of saved evidence; never infers causation."""
from datetime import datetime, timedelta
from django.urls import reverse
from django.utils import timezone


def correlate_incident(incident):
    events, excluded, gaps = [], [], []
    start = incident.occurred_at - timedelta(minutes=15)
    end = incident.occurred_at + timedelta(minutes=15)

    def collect(relation, label):
        rows = list(relation.order_by("-created_at", "-pk")[:21])
        if len(rows) > 20:
            gaps.append(f"{label}: only the newest 20 records were considered.")
        if not rows:
            gaps.append(f"No {label} records attached.")
        return rows[:20]

    def add(kind, identity, title, value, url, service=None, signal=False, findings=None):
        record = {"kind": kind, "identity": identity, "title": title, "url": url,
                  "service_match": "unknown" if service is None else ("match" if service == incident.affected_service else "different"),
                  "service": service, "signal": signal}
        if findings is not None:
            record['findings'] = findings
        try:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
            if not isinstance(timestamp, datetime) or timezone.is_naive(timestamp):
                raise ValueError()
        except (ValueError, TypeError):
            record["reason"] = "Missing, invalid or timezone-free event time; not correlated."
            excluded.append(record)
            return
        record["time"] = timestamp
        record["offset_seconds"] = (timestamp - incident.occurred_at).total_seconds()
        if not start <= timestamp <= end:
            record["reason"] = "Outside the incident ±15 minute window."
            excluded.append(record)
            return
        events.append(record)

    for item in collect(incident.log_evidence, "log evidence"):
        analysis = item.analysis
        url = reverse("incidents:log_detail", args=[incident.pk, item.pk])
        gaps.append(f"Log evidence #{item.pk}: service identity is not recorded; time-only matching is possible.")
        if analysis.get("evidence_truncated"):
            gaps.append(f"Log evidence #{item.pk}: saved error timeline is truncated to 100 lines.")
        if analysis.get("diagnostic_count") or analysis.get("counts", {}).get("UNKNOWN"):
            gaps.append(f"Log evidence #{item.pk}: unclassified lines or parsing diagnostics limit coverage.")
        for row in analysis.get("evidence", []):
            add("log", f"log:{item.pk}:line:{row['line']}", row["message"], row.get("timestamp"), url, signal=True)
    for item in collect(incident.database_evidence, "database evidence"):
        add("database", f"database:{item.pk}", f"{item.analysis['database']}: {len(item.analysis['findings'])} metric findings",
            item.analysis.get("captured_at"), reverse("incidents:database_detail", args=[incident.pk, item.pk]), signal=bool(item.analysis["findings"]), findings=item.analysis['findings'])
        gaps.append(f"Database evidence #{item.pk}: database-to-service mapping is unknown.")
    for item in collect(incident.trace_evidence, "trace evidence"):
        for span in item.analysis.get("spans", []):
            add("trace", f"trace:{item.pk}:{span['trace_id']}:{span['span_id']}",
                f"{span['operation']} · {span['status']} · {span['duration_ms']} ms",
                span.get("started_at"), reverse("incidents:trace_detail", args=[incident.pk, item.pk]),
                service=span["service"], signal=span["status"] == "ERROR" or span["duration_ms"] >= item.analysis.get("slow_threshold_ms", 1000))
    for item in collect(incident.deployments, "deployment"):
        add("deployment", f"deployment:{item.pk}", f"{item.service} / {item.environment} · {item.commit_sha}",
            item.deployed_at, reverse("incidents:deployment_detail", args=[incident.pk, item.pk]), service=item.service)
    events.sort(key=lambda row: (row["time"], row["identity"]))
    relationships = []
    for deployment in events:
        if deployment["kind"] != "deployment" or deployment["service_match"] != "match" or deployment["time"] > incident.occurred_at:
            continue
        following = [row for row in events if row["kind"] == "trace" and row["signal"] and row["service_match"] == "match" and row["time"] >= deployment["time"]]
        if following:
            relationships.append({"deployment": deployment, "trace": following[0], "matching_spans": len(following)})
    return {"start": start, "end": end, "events": events, "excluded": excluded,
            "relationships": relationships, "gaps": gaps,
            "policy": "Exact, case-sensitive service match; span start time; inclusive ±15 minutes. Supplied environment is not matched because incidents have no environment field."}
