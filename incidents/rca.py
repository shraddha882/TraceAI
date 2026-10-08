"""Conservative investigation report built from saved temporal evidence."""
from datetime import datetime
from .correlation import correlate_incident
from .rca_rules import database_hypotheses


def json_safe(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


def build_rca_report(incident):
    correlation = correlate_incident(incident)
    hypotheses = database_hypotheses(correlation['events'])
    for relation in correlation["relationships"]:
        hypotheses.append({
            "title": "A deployment-related regression is possible",
            "confidence": "Low — temporal association only",
            "reason": "A same-service deployment at or before the incident preceded an error/slow span in the time window.",
            "evidence": [relation["deployment"], relation["trace"]],
            "limitations": "Environment is unverified. A pre-deployment baseline and causal mechanism are missing. Other deployments or dependencies could explain the symptom.",
            "checks": "Review the saved deployment diff and code findings, compare pre/post deployment traces, and confirm service/environment alignment before considering a change.",
        })
    observations = [row for row in correlation["events"] if row["signal"]]
    return json_safe({
        "version": 2,
        "incident": {"id": incident.pk, "title": incident.title, "service": incident.affected_service, "occurred_at": incident.occurred_at},
        "status": "Hypotheses available" if hypotheses else "Insufficient evidence",
        "summary": "No confirmed root cause. This report contains investigation leads derived from explicit rules.",
        "hypotheses": hypotheses, "observations": observations,
        "correlation": correlation,
        "next_steps": [
            "Align evidence timestamps and timezones with the incident window; do not change genuine event times merely to obtain matches.",
            "Confirm environment and service ownership for logs, database metrics and traces.",
            "Collect baseline observations before the incident and inspect upstream/downstream dependencies.",
            "Validate a suspected mechanism before choosing a fix; no code or deployment changes are applied by this report.",
        ],
    })
