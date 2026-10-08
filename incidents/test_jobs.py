from core.testing import StaffTestCase
from datetime import timedelta
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from django.db import transaction, connections
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone
from .models import Incident, RCAJob, RCAReport
from .jobs import run_next_rca_job


def incident():
    return Incident.objects.create(title='Checkout failure', affected_service='api', description='Errors', occurred_at=timezone.now())


class RCAJobTests(StaffTestCase):
    def setUp(self):
        self.incident = incident()
        self.url = reverse('incidents:rca_create', args=[self.incident.pk])

    def test_enqueue_and_duplicate_submission_without_analysis(self):
        with patch('incidents.jobs.build_rca_report') as build:
            first = self.client.post(self.url)
            second = self.client.post(self.url)
            build.assert_not_called()
        self.assertEqual(first.url, second.url)
        self.assertEqual(RCAJob.objects.count(), 1)
        self.assertEqual(RCAReport.objects.count(), 0)
        self.assertContains(self.client.get(first.url), 'Pending')

    def test_completion_is_published_once_and_report_link_is_valid(self):
        self.client.post(self.url)
        job = RCAJob.objects.get()
        self.assertTrue(run_next_rca_job())
        self.assertFalse(run_next_rca_job())
        job.refresh_from_db()
        self.assertEqual(job.status, 'completed')
        self.assertEqual(job.report.incident_id, self.incident.pk)
        self.assertIsNotNone(job.finished_at)
        status = self.client.get(reverse('incidents:rca_job_status', args=[self.incident.pk, job.pk]))
        self.assertEqual(status['Cache-Control'], 'no-store')
        self.assertContains(self.client.get(status.json()['report_url']), 'Insufficient evidence')
        self.assertEqual(RCAReport.objects.count(), 1)

    def test_failure_is_sanitized_and_user_can_retry(self):
        self.client.post(self.url)
        job = RCAJob.objects.get()
        with patch('incidents.jobs.build_rca_report', side_effect=RuntimeError('private credentials')):
            run_next_rca_job()
        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')
        self.assertNotIn('private', job.error)
        self.assertFalse(RCAReport.objects.exists())
        self.client.post(self.url)
        self.assertTrue(run_next_rca_job())
        self.assertEqual(RCAReport.objects.count(), 1)

    def test_abandoned_job_recovered_and_no_late_report(self):
        job = RCAJob.objects.create(incident=self.incident, status='running', started_at=timezone.now() - timedelta(minutes=16))
        self.assertFalse(run_next_rca_job())
        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')
        self.assertIsNone(job.report_id)

    def test_late_completion_cannot_publish_failed_job(self):
        job = RCAJob.objects.create(incident=self.incident)
        def abandoned(_):
            RCAJob.objects.filter(pk=job.pk).update(status='failed')
            return {}
        with patch('incidents.jobs.build_rca_report', side_effect=abandoned):
            run_next_rca_job()
        self.assertFalse(RCAReport.objects.exists())

    def test_routes_are_scoped_to_incident_and_get_only(self):
        job = RCAJob.objects.create(incident=self.incident)
        other = incident()
        for name in ['rca_job', 'rca_job_status']:
            url = reverse('incidents:' + name, args=[self.incident.pk, job.pk])
            self.assertEqual(self.client.post(url).status_code, 405)
            self.assertEqual(self.client.get(reverse('incidents:' + name, args=[other.pk, job.pk])).status_code, 404)


class RCALockTests(TransactionTestCase):
    @skipUnlessDBFeature('has_select_for_update_skip_locked')
    def test_second_worker_skips_claimed_row(self):
        job = RCAJob.objects.create(incident=incident())
        def worker():
            try:
                return run_next_rca_job()
            finally:
                connections.close_all()
        with transaction.atomic():
            RCAJob.objects.select_for_update().get(pk=job.pk)
            with ThreadPoolExecutor(max_workers=1) as pool:
                self.assertFalse(pool.submit(worker).result(timeout=5))
        job.refresh_from_db()
        self.assertEqual(job.status, 'pending')
