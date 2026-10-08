"""Create a repeatable offline synthetic investigation, without touching user data."""
from datetime import datetime, timezone
from pathlib import Path
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from incidents.models import Incident, Deployment, LogEvidence, DatabaseEvidence, TraceEvidence, RCAReport
from incidents.log_analysis import analyze_logs
from incidents.db_analysis import analyze_db_snapshot
from incidents.trace_analysis import analyze_trace_snapshot
from incidents.rca import build_rca_report

TITLE = "[SYNTHETIC DEMO v1] Checkout timeout investigation"


class Command(BaseCommand):
    help = "Create one offline synthetic incident with aligned evidence and a saved RCA report."

    def add_arguments(self, parser):
        parser.add_argument('--username', help='Assign the demo to this existing account.')

    @transaction.atomic
    def handle(self, *args, **options):
        owner = None
        if options.get('username'):
            owner = get_user_model().objects.filter(username=options['username'], is_active=True).first()
            if owner is None:
                raise CommandError('An active account with that username was not found.')
        existing = Incident.objects.filter(title=TITLE, owner=owner).first()
        if existing:
            self.stdout.write(f"Demo already exists; no records changed. /incidents/{existing.pk}/")
            return
        examples = Path(settings.BASE_DIR) / "examples"
        logs = (examples / "incident_demo.log").read_text(encoding="utf-8")
        logs += '\n' + (examples / 'rca_database_signals.log').read_text(encoding='utf-8')
        database = (examples / "database_snapshot.json").read_text(encoding="utf-8")
        traces = (examples / "trace_snapshot.json").read_text(encoding="utf-8")
        incident = Incident.objects.create(
            owner=owner,
            title=TITLE, affected_service="checkout-api",
            occurred_at=datetime(2026, 9, 24, 10, 30, tzinfo=timezone.utc),
            description=("Synthetic training data, not a real outage. A fictional deployment at 10:20 UTC "
                         "precedes checkout errors at 10:30 UTC. This demonstrates a temporal hypothesis, "
                         "not proven causation. Git commits are placeholders; no verified Git diff is attached."),
        )
        Deployment.objects.create(incident=incident, service="checkout-api", environment="synthetic-demo",
            deployed_at=datetime(2026, 9, 24, 10, 20, tzinfo=timezone.utc), repository="synthetic-demo/checkout",
            previous_commit_sha="a" * 40, commit_sha="b" * 40,
            notes="SYNTHETIC deployment. Placeholder SHAs do not refer to verified GitHub commits. Do not fetch this fictional repository.")
        LogEvidence.objects.create(incident=incident, source_name="SYNTHETIC incident_demo.log", source_text=logs, analysis=analyze_logs(logs))
        DatabaseEvidence.objects.create(incident=incident, source_text=database, analysis=analyze_db_snapshot(database))
        TraceEvidence.objects.create(incident=incident, source_text=traces, analysis=analyze_trace_snapshot(traces))
        snapshot = build_rca_report(incident)
        snapshot["summary"] = "SYNTHETIC DEMO. " + snapshot["summary"]
        report = RCAReport.objects.create(incident=incident, snapshot=snapshot)
        self.stdout.write(self.style.SUCCESS(f"Created demo: /incidents/{incident.pk}/"))
        self.stdout.write(f"Correlation: /incidents/{incident.pk}/correlation/")
        self.stdout.write(f"Saved RCA: /incidents/{incident.pk}/rca/{report.pk}/")
