from core.testing import StaffTestCase
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from .ai import explain_rca
from .models import Incident, RCAJob, RCAReport
from .jobs import run_next_rca_job


SNAPSHOT = {'incident': {'title': 'PRIVATE'}, 'hypotheses': [{
    'title': 'Possible contention', 'confidence': 'Low', 'reason': 'Matching signals',
    'limitations': 'Ownership unknown', 'checks': 'Inspect blockers',
    'evidence': [{'title': 'SECRET RAW LOG', 'identity': 'private identifier'}]}]}


@override_settings(OPENAI_API_KEY='test-only', TRACEAI_AI_MODEL='test-model')
class AIExplanationTests(SimpleTestCase):
    @patch('openai.OpenAI')
    def test_opt_out_and_missing_key_never_call_provider(self, client):
        self.assertEqual(explain_rca(SNAPSHOT)['status'], 'not_requested')
        with override_settings(OPENAI_API_KEY=''):
            self.assertEqual(explain_rca(SNAPSHOT, True)['status'], 'unavailable')
        self.assertEqual(explain_rca({'hypotheses': []}, True)['status'], 'skipped')
        client.assert_not_called()

    @patch('openai.OpenAI')
    def test_success_is_bounded_and_excludes_raw_data(self, client):
        create = client.return_value.__enter__.return_value.responses.create
        create.return_value = SimpleNamespace(status='completed', output_text=json.dumps({'explanations': [
            {'hypothesis_id': 'H1', 'explanation': 'Possible issue, unconfirmed.', 'suggested_check': 'Inspect the evidence.'}]}))
        before = deepcopy(SNAPSHOT)
        result = explain_rca(SNAPSHOT, True)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(SNAPSHOT, before)
        args = create.call_args.kwargs
        self.assertFalse(args['store'])
        self.assertNotIn('PRIVATE', args['input'])
        self.assertNotIn('SECRET', args['input'])
        self.assertNotIn('private identifier', args['input'])
        self.assertEqual(client.call_args.kwargs['max_retries'], 0)

    @patch('openai.OpenAI')
    def test_invalid_or_incomplete_output_falls_back(self, client):
        create = client.return_value.__enter__.return_value.responses.create
        for status, body in [('incomplete', '{}'), ('completed', 'not json'), ('completed', '{"explanations":[]}'),
                             ('completed', '{"explanations":[{"hypothesis_id":"H999","explanation":"x","suggested_check":"y"}]}')]:
            create.return_value = SimpleNamespace(status=status, output_text=body)
            self.assertEqual(explain_rca(SNAPSHOT, True)['status'], 'unavailable')
        create.side_effect = TimeoutError('secret provider details')
        result = explain_rca(SNAPSHOT, True)
        self.assertNotIn('secret', json.dumps(result))


class AIJobTests(StaffTestCase):
    @override_settings(OPENAI_API_KEY='')
    def test_requested_ai_missing_key_still_saves_static_report(self):
        incident = Incident.objects.create(title='Test', affected_service='api', description='Error', occurred_at=timezone.now())
        self.client.post(reverse('incidents:rca_create', args=[incident.pk]), {'use_ai': 'on'})
        self.assertTrue(RCAJob.objects.get().use_ai)
        run_next_rca_job()
        job = RCAJob.objects.get()
        self.assertEqual(job.status, 'completed')
        report = RCAReport.objects.get()
        self.assertEqual(report.snapshot['status'], 'Insufficient evidence')
        self.assertEqual(report.snapshot['ai_enhancement']['status'], 'unavailable')
        report.snapshot['ai_enhancement'] = {'status': 'completed', 'explanations': [
            {'hypothesis_id': 'H1', 'explanation': '<script>bad</script>', 'suggested_check': 'Check'}]}
        report.save()
        response = self.client.get(reverse('incidents:rca_detail', args=[incident.pk, report.pk]))
        self.assertContains(response, '&lt;script&gt;')
        self.assertNotContains(response, '<script>bad</script>')
