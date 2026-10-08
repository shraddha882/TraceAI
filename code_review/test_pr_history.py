from core.testing import StaffTestCase
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from .github import GitHubError
from .models import PullRequestReview
from .pr_analysis import create_pr_review
from .test_pr_analysis import preview
from .test_github import URL
from .jobs import run_next_job
from .models import PRReviewJob


class PRHistoryTests(StaffTestCase):
    def create_report(self, source="requests.get(url)"):
        with patch("code_review.pr_analysis.fetch_public_pr", return_value=preview()), patch("code_review.pr_analysis.fetch_python_source", return_value=source):
            return create_pr_review(URL)

    def test_snapshot_preserves_details_and_reopens_without_network(self):
        saved = self.create_report()
        saved.refresh_from_db()
        self.assertEqual(saved.snapshot["head_sha"], "a" * 40)
        self.assertEqual(saved.snapshot["files"][0]["analysis_status"], "analyzed")
        self.assertEqual(saved.snapshot["analysis_summary"]["counts"]["HIGH"], 1)
        before = saved.snapshot
        with patch("code_review.github.github_json", side_effect=AssertionError("Must not fetch")):
            page = self.client.get(reverse("code_review:pr_detail", args=[saved.pk]))
        self.assertContains(page, "HTTP request has no timeout")
        self.assertContains(page, "historical snapshot")
        self.assertContains(page, "Line 1")
        self.assertNotContains(page, "Load Pull Request")
        saved.refresh_from_db()
        self.assertEqual(saved.snapshot, before)

    def test_analysis_redirect_and_refresh_do_not_duplicate(self):
        with patch("code_review.pr_analysis.fetch_public_pr", return_value=preview()) as fetch, patch("code_review.pr_analysis.fetch_python_source", return_value="pass"):
            response = self.client.post(reverse("code_review:github"), {"pr_url": URL, "action": "analyze"})
            self.assertEqual(response.status_code, 302)
            fetch.assert_not_called()
            run_next_job()
            self.client.get(response.url)
            self.client.get(response.url)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(PullRequestReview.objects.count(), 1)

    def test_failed_file_run_is_saved_honestly(self):
        saved = self.create_report("def broken(")
        self.assertEqual(saved.snapshot["analysis_summary"]["failed"], 1)
        page = self.client.get(reverse("code_review:pr_detail", args=[saved.pk]))
        self.assertContains(page, "This is not a clean review")
        self.assertContains(page, "Syntax error")

    def test_pr_fetch_failure_does_not_save(self):
        with patch("code_review.pr_analysis.fetch_public_pr", side_effect=GitHubError("Unavailable")):
            response = self.client.post(reverse("code_review:github"), {"pr_url": URL, "action": "analyze"})
            run_next_job()
            response = self.client.get(response.url)
        self.assertContains(response, "Unavailable")
        self.assertEqual(PullRequestReview.objects.count(), 0)

    def test_history_links_and_newest_first(self):
        older = self.create_report()
        newer = self.create_report()
        response = self.client.get(reverse("code_review:history"))
        self.assertEqual(list(response.context["pr_reviews"]), [newer, older])
        for saved in (older, newer):
            self.assertContains(response, reverse("code_review:pr_detail", args=[saved.pk]))

    def test_missing_report_is_404_and_get_only(self):
        url = reverse("code_review:pr_detail", args=[999])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url).status_code, 405)

    def test_saved_upstream_text_is_escaped(self):
        saved = self.create_report()
        saved.snapshot["title"] = "<script>alert(1)</script>"
        saved.save()
        for url in (reverse("code_review:history"), reverse("code_review:pr_detail", args=[saved.pk])):
            page = self.client.get(url)
            self.assertContains(page, "&lt;script&gt;")
            self.assertNotContains(page, "<script>alert(1)</script>")
