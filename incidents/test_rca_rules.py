from core.testing import StaffTestCase
from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from django.urls import reverse
from .models import Incident, DatabaseEvidence, LogEvidence, TraceEvidence, RCAReport
from .rca import build_rca_report


class CrossSourceRCATests(StaffTestCase):
    def setUp(self):
        self.time = timezone.now()
        self.incident = Incident.objects.create(title='Failure', affected_service='api', description='Errors', occurred_at=self.time)

    def evidence(self, rule='DB_CONNECTION_USAGE', message='connection pool exhausted', offset=0):
        db = DatabaseEvidence.objects.create(incident=self.incident, source_text='{}', analysis={
            'database': 'orders', 'captured_at': self.time.isoformat(),
            'findings': [{'rule': rule, 'evidence': 'Observed metric threshold exceeded'}]})
        log = LogEvidence.objects.create(incident=self.incident, source_name='sample', source_text=message, analysis={
            'evidence': [{'line': 1, 'message': message, 'timestamp': (self.time + timedelta(seconds=offset)).isoformat()}]})
        return db, log

    def test_three_specific_rules_and_linked_metric_evidence(self):
        for rule, message in [('DB_CONNECTION_USAGE', 'too many connections'), ('DB_LOCK_WAIT', 'deadlock detected'), ('DB_SLOW_QUERY', 'statement timeout')]:
            with self.subTest(rule=rule):
                db, log = self.evidence(rule, message)
                result = build_rca_report(self.incident)
                lead = next(h for h in result['hypotheses'] if h.get('rule') == rule)
                self.assertIn('Low', lead['confidence'])
                self.assertEqual(lead['matched_findings'][0]['rule'], rule)
                self.assertEqual(lead['evidence'][0]['url'], reverse('incidents:database_detail', args=[self.incident.pk, db.pk]))
                self.assertEqual(lead['evidence'][1]['identity'], f'log:{log.pk}:line:1')
                db.delete()
                log.delete()

    def test_generic_timeout_or_mismatched_rule_does_not_match(self):
        for message in ['HTTP timeout', 'statement timeout', 'everything is slow']:
            db, log = self.evidence(message=message)
            self.assertEqual(build_rca_report(self.incident)['hypotheses'], [])
            db.delete()
            log.delete()

    def test_pair_window_boundary_and_missing_or_outside_timestamp(self):
        db, log = self.evidence(offset=300)
        self.assertEqual(len(build_rca_report(self.incident)['hypotheses']), 1)
        for timestamp in [(self.time + timedelta(seconds=301)).isoformat(), (self.time + timedelta(minutes=16)).isoformat(), None]:
            log.analysis['evidence'][0]['timestamp'] = timestamp
            log.save()
            self.assertEqual(build_rca_report(self.incident)['hypotheses'], [])

    def test_only_matching_service_signal_trace_is_support(self):
        self.evidence()
        trace = TraceEvidence.objects.create(incident=self.incident, source_text='{}', analysis={'spans': [{
            'trace_id': 't', 'span_id': 's', 'service': 'other', 'operation': 'request',
            'status': 'ERROR', 'duration_ms': 10, 'started_at': self.time.isoformat()}]})
        self.assertEqual(len(build_rca_report(self.incident)['hypotheses'][0]['evidence']), 2)
        trace.analysis['spans'][0]['service'] = 'api'
        trace.save()
        self.assertEqual(len(build_rca_report(self.incident)['hypotheses'][0]['evidence']), 3)

    def test_new_report_renders_escaped_details_and_old_snapshot_is_unchanged(self):
        self.evidence(message='connection pool exhausted <script>bad</script>')
        old = RCAReport.objects.create(incident=self.incident, snapshot={'version': 1, 'hypotheses': []})
        report = RCAReport.objects.create(incident=self.incident, snapshot=build_rca_report(self.incident))
        response = self.client.get(reverse('incidents:rca_detail', args=[self.incident.pk, report.pk]))
        self.assertContains(response, 'Matched metric: DB_CONNECTION_USAGE')
        self.assertContains(response, '&lt;script&gt;')
        self.assertNotContains(response, '<script>bad</script>')
        old.refresh_from_db()
        self.assertEqual(old.snapshot, {'version': 1, 'hypotheses': []})
