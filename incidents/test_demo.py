from core.testing import StaffTestCase
from io import StringIO
from unittest.mock import patch
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from incidents.models import Incident, RCAReport
from incidents.correlation import correlate_incident


class DemoTests(StaffTestCase):
    def test_repeatable_positive_flow_and_saved_pages(self):
        call_command("create_demo_incident", stdout=StringIO())
        incident = Incident.objects.get()
        report = RCAReport.objects.get()
        result = correlate_incident(incident)
        self.assertEqual(len(result["events"]), 11)
        self.assertEqual(len(result["relationships"]), 1)
        self.assertEqual(report.snapshot["status"], "Hypotheses available")
        self.assertEqual(len(report.snapshot["hypotheses"]), 4)
        self.assertIn("SYNTHETIC", report.snapshot["summary"])
        call_command("create_demo_incident", stdout=StringIO())
        self.assertEqual(Incident.objects.count(), 1)
        self.assertEqual(RCAReport.objects.count(), 1)
        for name, args in (("detail", [incident.pk]), ("correlation", [incident.pk]), ("rca_detail", [incident.pk, report.pk])):
            self.assertEqual(self.client.get(reverse("incidents:" + name, args=args)).status_code, 200)

    def test_failed_build_rolls_back_all_demo_records(self):
        with patch("incidents.management.commands.create_demo_incident.build_rca_report", side_effect=RuntimeError("fail")):
            with self.assertRaises(RuntimeError):
                call_command("create_demo_incident", stdout=StringIO())
        self.assertEqual(Incident.objects.count(), 0)


    def test_owned_demo_is_repeatable_and_private(self):
        from django.contrib.auth import get_user_model
        owner = get_user_model().objects.create_user('demo-owner')
        other = get_user_model().objects.create_user('demo-other')
        call_command('create_demo_incident', username=owner.username, stdout=StringIO())
        call_command('create_demo_incident', username=owner.username, stdout=StringIO())
        incident = Incident.objects.get(owner=owner)
        self.assertEqual(Incident.objects.count(), 1)
        self.client.force_login(owner)
        self.assertEqual(self.client.get(reverse('incidents:detail', args=[incident.pk])).status_code, 200)
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse('incidents:detail', args=[incident.pk])).status_code, 404)
