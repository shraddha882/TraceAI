from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
from uuid import uuid4


class AccessTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user('owner', password='test-password-123', is_staff=True)

    def test_anonymous_pages_redirect_and_posts_do_not_run(self):
        for url in ['/', '/incidents/', '/incidents/1/', '/code-review/', '/code-review/history/', '/code-review/github/']:
            self.assertEqual(self.client.get(url).status_code, 302)
        self.assertEqual(self.client.post('/incidents/1/rca/new/').status_code, 302)

    def test_status_endpoints_require_login_before_lookup(self):
        for url in [reverse('code_review:job_status', args=[uuid4()]), reverse('incidents:rca_job_status', args=[1, uuid4()])]:
            self.assertEqual(self.client.get(url).status_code, 401)

    def test_registered_and_staff_allowed(self):
        user = get_user_model().objects.create_user('regular')
        self.client.force_login(user)
        self.assertEqual(self.client.get('/incidents/').status_code, 200)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get('/incidents/').status_code, 200)

    def test_login_safe_redirect_and_logout(self):
        response = self.client.post(reverse('login'), {'username': 'owner', 'password': 'test-password-123', 'next': 'https://example.org'})
        self.assertRedirects(response, '/')
        self.assertEqual(self.client.get(reverse('logout')).status_code, 405)
        self.client.post(reverse('logout'))
        self.assertEqual(self.client.get('/').status_code, 302)

    def test_login_and_logout_csrf(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post(reverse('login'), {}).status_code, 403)
        client.force_login(self.staff)
        self.assertEqual(client.post(reverse('logout')).status_code, 403)
