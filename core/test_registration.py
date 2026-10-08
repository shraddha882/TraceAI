from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from code_review.models import CodeReview, PRReviewJob, PullRequestReview
from code_review.jobs import run_next_job
from incidents.models import Incident, LogEvidence, TraceEvidence, DatabaseEvidence, Deployment, RCAJob, RCAReport


class RegistrationTests(TestCase):
    password = 'Str0ng-Trace-Account!482'

    def test_signup_login_use_project_logout(self):
        self.assertContains(self.client.get(reverse('login')), 'Create an account')
        self.assertContains(self.client.get(reverse('signup')), 'Create your account')
        response = self.client.post(reverse('signup'), {
            'username': 'newuser', 'password1': self.password, 'password2': self.password,
            'is_staff': 'on', 'is_superuser': 'on',
        })
        self.assertRedirects(response, reverse('login'))
        user = get_user_model().objects.get(username='newuser')
        self.assertTrue(user.check_password(self.password))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertRedirects(self.client.post(reverse('login'), {'username': 'newuser', 'password': self.password}), '/')
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertRedirects(self.client.get(reverse('signup')), '/')
        self.client.post('/code-review/', {'code': 'x = 1', 'language': 'Python'})
        self.assertEqual(CodeReview.objects.get().owner, user)
        self.client.post('/incidents/new/', {'title': 'My incident', 'affected_service': 'api', 'description': 'Error', 'occurred_at': '2026-10-08T10:00'})
        self.assertEqual(Incident.objects.get().owner, user)
        self.client.post(reverse('logout'))
        self.assertEqual(self.client.get('/').status_code, 302)

    def test_registration_validation_and_csrf(self):
        get_user_model().objects.create_user('existing')
        for username, first, second in [('existing', self.password, self.password), ('other', self.password, 'mismatch'), ('other', '123', '123')]:
            response = self.client.post(reverse('signup'), {'username': username, 'password1': first, 'password2': second})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['form'].errors)
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertEqual(Client(enforce_csrf_checks=True).post(reverse('signup'), {}).status_code, 403)

    def test_inactive_login_denied(self):
        get_user_model().objects.create_user('inactive', password=self.password, is_active=False)
        self.assertEqual(self.client.post(reverse('login'), {'username': 'inactive', 'password': self.password}).status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)


class PrivacyTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user('owner')
        self.other = get_user_model().objects.create_user('other')
        self.client.force_login(self.other)
        self.incident = Incident.objects.create(owner=self.owner, title='Secret incident', affected_service='api', description='private', occurred_at=timezone.now())

    def test_review_history_details_and_job_status_are_private(self):
        review = CodeReview.objects.create(owner=self.owner, source_code='secret source')
        report = PullRequestReview.objects.create(owner=self.owner, snapshot={})
        job = PRReviewJob.objects.create(owner=self.owner, pr_url='https://github.com/acme/repo/pull/1', review=report)
        for name, pk in [('detail', review.pk), ('pr_detail', report.pk), ('job_detail', job.pk), ('job_status', job.pk)]:
            self.assertEqual(self.client.get(reverse('code_review:' + name, args=[pk])).status_code, 404)
        response = self.client.get(reverse('code_review:history'))
        for key in ['reviews', 'pr_reviews', 'jobs']:
            self.assertEqual(len(response.context[key]), 0)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('code_review:detail', args=[review.pk])).status_code, 200)

    def test_all_incident_resources_and_mutations_are_private(self):
        i = self.incident
        log = LogEvidence.objects.create(incident=i, source_name='secret', source_text='secret', analysis={})
        trace = TraceEvidence.objects.create(incident=i, source_text='secret', analysis={})
        database = DatabaseEvidence.objects.create(incident=i, source_text='secret', analysis={})
        deployment = Deployment.objects.create(incident=i, service='api', environment='prod', deployed_at=timezone.now(), repository='acme/repo', commit_sha='a'*40)
        report = RCAReport.objects.create(incident=i, snapshot={})
        job = RCAJob.objects.create(incident=i)
        routes = [('detail', []), ('correlation', []), ('log_detail', [log.pk]), ('trace_detail', [trace.pk]), ('database_detail', [database.pk]), ('deployment_detail', [deployment.pk]), ('rca_detail', [report.pk]), ('rca_job', [job.pk]), ('rca_job_status', [job.pk])]
        for name, args in routes:
            with self.subTest(route=name):
                self.assertEqual(self.client.get(reverse('incidents:'+name, args=[i.pk]+args)).status_code, 404)
        for name, args in [('rca_create', []), ('logs_create', []), ('trace_create', []), ('database_create', []), ('deployment_create', []), ('deployment_fetch_diff', [deployment.pk]), ('deployment_review', [deployment.pk])]:
            with self.subTest(route=name):
                self.assertEqual(self.client.post(reverse('incidents:'+name, args=[i.pk]+args), {}).status_code, 404)
        self.assertEqual(len(self.client.get(reverse('incidents:list')).context['page']), 0)

    def test_legacy_records_remain_staff_only(self):
        legacy = CodeReview.objects.create(source_code='legacy')
        url = reverse('code_review:detail', args=[legacy.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.other.is_staff = True
        self.other.save()
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get(reverse('incidents:detail', args=[self.incident.pk])).status_code, 404)

    @patch('code_review.jobs.analyze_public_pr', return_value={})
    def test_worker_report_inherits_job_owner(self, analyze):
        job = PRReviewJob.objects.create(owner=self.owner, pr_url='https://github.com/acme/repo/pull/1')
        self.assertTrue(run_next_job())
        job.refresh_from_db()
        self.assertEqual(job.review.owner, self.owner)

    def test_queued_job_has_requesting_owner(self):
        response = self.client.post(reverse('code_review:github'), {'pr_url': 'https://github.com/acme/repo/pull/1', 'action': 'analyze'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(PRReviewJob.objects.get().owner, self.other)

class DashboardCountTests(TestCase):
    def test_counts_include_only_accessible_records(self):
        user = get_user_model().objects.create_user('viewer')
        other = get_user_model().objects.create_user('someoneelse')
        CodeReview.objects.create(owner=user, source_code='demo', critical_count=1, high_count=3, medium_count=1)
        CodeReview.objects.create(owner=other, source_code='private', high_count=9)
        CodeReview.objects.create(source_code='legacy', high_count=10)
        Incident.objects.create(owner=user, title='demo', affected_service='api', occurred_at=timezone.now())
        Incident.objects.create(owner=other, title='private', affected_service='api', occurred_at=timezone.now())
        self.client.force_login(user)
        response = self.client.get('/')
        self.assertEqual(response.context['incident_count'], 1)
        self.assertEqual(response.context['review_count'], 1)
        self.assertEqual(response.context['risk_count'], 5)
