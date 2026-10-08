from core.testing import StaffTestCase
from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.db import transaction, connections
from concurrent.futures import ThreadPoolExecutor
from django.urls import reverse
from django.utils import timezone
from .jobs import run_next_job
from .models import PRReviewJob, PullRequestReview
from .test_github import URL


class JobTests(StaffTestCase):
    def test_submission_is_durable_and_does_not_call_github(self):
        with patch('code_review.jobs.analyze_public_pr') as analyze:
            response = self.client.post(reverse('code_review:github'), {'pr_url': URL, 'action': 'analyze'})
            self.assertEqual(response.status_code, 302)
            analyze.assert_not_called()
        job = PRReviewJob.objects.get()
        self.assertEqual(job.status, 'pending')
        self.assertEqual(PullRequestReview.objects.count(), 0)
        self.assertContains(self.client.get(response.url), 'Pending')

    def test_worker_publishes_one_report_and_status(self):
        job = PRReviewJob.objects.create(pr_url=URL)
        def analyze(url):
            job.refresh_from_db()
            self.assertEqual(job.status, 'running')
            return {'files': []}
        with patch('code_review.jobs.analyze_public_pr', side_effect=analyze):
            self.assertTrue(run_next_job())
            self.assertFalse(run_next_job())
        job.refresh_from_db()
        self.assertEqual(job.status, 'completed')
        self.assertIsNotNone(job.finished_at)
        data = self.client.get(reverse('code_review:job_status', args=[job.pk])).json()
        self.assertEqual(data['report_url'], reverse('code_review:pr_detail', args=[job.review_id]))
        self.assertEqual(PullRequestReview.objects.count(), 1)

    def test_unexpected_failure_is_sanitized_and_next_job_can_run(self):
        first = PRReviewJob.objects.create(pr_url=URL)
        second = PRReviewJob.objects.create(pr_url=URL)
        with patch('code_review.jobs.analyze_public_pr', side_effect=[RuntimeError('private credentials'), {}]):
            run_next_job()
            run_next_job()
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, 'failed')
        self.assertNotIn('private', first.error)
        self.assertEqual(second.status, 'completed')

    def test_abandoned_job_fails_without_retry(self):
        job = PRReviewJob.objects.create(pr_url=URL, status='running', started_at=timezone.now() - timedelta(minutes=16))
        self.assertFalse(run_next_job())
        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')
        self.assertIsNone(job.review_id)

    def test_status_get_only_and_unknown_job(self):
        job = PRReviewJob.objects.create(pr_url=URL)
        url = reverse('code_review:job_status', args=[job.pk])
        self.assertEqual(self.client.post(url).status_code, 405)
        job.delete()
        self.assertEqual(self.client.get(url).status_code, 404)


class WorkerLockTests(TransactionTestCase):
    @skipUnlessDBFeature('has_select_for_update_skip_locked')
    def test_other_worker_skips_locked_job(self):
        job = PRReviewJob.objects.create(pr_url=URL)
        def other_worker():
            try:
                return run_next_job()
            finally:
                connections.close_all()
        with transaction.atomic():
            PRReviewJob.objects.select_for_update().get(pk=job.pk)
            with ThreadPoolExecutor(max_workers=1) as pool:
                self.assertFalse(pool.submit(other_worker).result(timeout=5))
        job.refresh_from_db()
        self.assertEqual(job.status, 'pending')
