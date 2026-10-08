from core.testing import StaffTestCase
import json
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from django.test import SimpleTestCase, TestCase, Client
from django.urls import reverse

from .github import GitHubError, fetch_public_pr, github_json, parse_pr_url
from .models import CodeReview


URL = "https://github.com/example/project/pull/12"
METADATA = {
    "title": "Fix a timeout", "user": {"login": "developer"},
    "state": "closed", "merged": True, "changed_files": 2,
    "head": {"sha": "a" * 40}, "base": {"sha": "b" * 40},
}
FILES = [
    {"filename": "app.py", "status": "renamed", "previous_filename": "old.py", "additions": 2, "deletions": 1},
    {"filename": "README.md", "status": "removed", "additions": 0, "deletions": 5},
]


class GitHubServiceTests(SimpleTestCase):
    def test_url_normalization_and_rejection(self):
        self.assertEqual(parse_pr_url(" " + URL + "/ "), ("example", "project", "12"))
        for value in ("http://github.com/a/b/pull/1", "https://evil.com/a/b/pull/1",
                      "https://github.com.evil.com/a/b/pull/1", "https://github.com@localhost/a/b/pull/1",
                      "https://github.com/a/../pull/1", "https://github.com/a/b/issues/1",
                      URL + "?redirect=evil", URL + "/files", "https://github.com/a/b/pull/0"):
            with self.subTest(value=value), self.assertRaises(GitHubError):
                parse_pr_url(value)

    @patch("code_review.github.github_json", side_effect=[METADATA, FILES])
    def test_preview_maps_metadata_and_files(self, request):
        pr = fetch_public_pr(URL)
        self.assertEqual(pr["state"], "merged")
        self.assertEqual(pr["files"][0]["previous_filename"], "old.py")
        self.assertTrue(pr["files"][0]["is_python"])
        self.assertFalse(pr["files"][1]["is_python"])
        self.assertFalse(pr["incomplete"])
        self.assertEqual(request.call_args_list[1].args[0], "/repos/example/project/pulls/12/files?per_page=100&page=1")

    def test_large_pr_marks_partial_list(self):
        with patch("code_review.github.github_json", side_effect=[{**METADATA, "changed_files": 150}, FILES]):
            self.assertTrue(fetch_public_pr(URL)["incomplete"])

    def test_malformed_response_is_a_friendly_error(self):
        for metadata, files in (({}, FILES), (METADATA, {}), (METADATA, [None])):
            with self.subTest(metadata=metadata), patch("code_review.github.github_json", side_effect=[metadata, files]):
                with self.assertRaises(GitHubError):
                    fetch_public_pr(URL)

    @patch("code_review.github.build_opener")
    def test_http_request_is_fixed_host_bounded_and_unauthenticated(self, factory):
        response = factory.return_value.open.return_value.__enter__.return_value
        response.read.return_value = b'{"ok": true}'
        self.assertEqual(github_json("/repos/example/project/pulls/12"), {"ok": True})
        call = factory.return_value.open.call_args
        self.assertEqual(call.args[0].full_url, "https://api.github.com/repos/example/project/pulls/12")
        self.assertEqual(call.kwargs["timeout"], 10)
        self.assertFalse(call.args[0].has_header("Authorization"))
        response.read.assert_called_once_with(4 * 1024 * 1024 + 1)
        handler = factory.call_args.args[0]
        self.assertIsNone(handler.redirect_request(None, None, 302, "", {}, "http://localhost"))

    def test_http_errors_and_network_failure(self):
        for error, message in ((HTTPError(URL, 404, "", {}, None), "not found"),
                               (HTTPError(URL, 429, "", {}, None), "limit"),
                               (HTTPError(URL, 301, "", {}, None), "moved"),
                               (HTTPError(URL, 500, "", {}, None), "try again"),
                               (URLError("offline"), "Unable to reach"),
                               (TimeoutError(), "timeout")):
            with self.subTest(error=error), patch("code_review.github.build_opener") as factory:
                factory.return_value.open.side_effect = error
                with self.assertRaisesRegex(GitHubError, message):
                    github_json("/repos/example/project/pulls/12")

    def test_invalid_json_and_oversized_response(self):
        for content in (b"not json", b"x" * (4 * 1024 * 1024 + 1)):
            with patch("code_review.github.build_opener") as factory:
                factory.return_value.open.return_value.__enter__.return_value.read.return_value = content
                with self.assertRaises(GitHubError):
                    github_json("/repos/example/project/pulls/12")


class GitHubPageTests(StaffTestCase):
    def setUp(self):
        self.url = reverse("code_review:github")

    @patch("code_review.views.fetch_public_pr")
    def test_get_and_invalid_post_do_not_fetch(self, fetch):
        self.assertContains(self.client.get(self.url), "Load Pull Request")
        for value in ("", "https://localhost/pull/1"):
            response = self.client.post(self.url, {"pr_url": value})
            self.assertTrue(response.context["form"].errors)
        fetch.assert_not_called()

    @patch("code_review.github.github_json", side_effect=[METADATA, FILES])
    def test_post_renders_pr_without_creating_review(self, fetch):
        response = self.client.post(self.url, {"pr_url": URL})
        for text in ("Fix a timeout", "app.py", "old.py", "README.md", "merged", "Python"):
            self.assertContains(response, text)
        self.assertEqual(CodeReview.objects.count(), 0)

    @patch("code_review.views.fetch_public_pr", side_effect=GitHubError("Please try again later."))
    def test_upstream_error_preserves_input(self, fetch):
        response = self.client.post(self.url, {"pr_url": URL})
        self.assertContains(response, "Please try again later.")
        self.assertContains(response, URL)
        self.assertIsNone(response.context["pr"])

    def test_upstream_text_is_escaped_and_limit_is_visible(self):
        metadata = {**METADATA, "title": "<script>alert(1)</script>", "changed_files": 101}
        with patch("code_review.github.github_json", side_effect=[metadata, FILES]):
            response = self.client.post(self.url, {"pr_url": URL})
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertContains(response, "&lt;script&gt;")
        self.assertContains(response, "partial file list")

    def test_navigation_and_csrf(self):
        self.assertContains(self.client.get(reverse("code_review:review")), self.url)
        self.assertEqual(Client(enforce_csrf_checks=True).post(self.url, {"pr_url": URL}).status_code, 403)
        self.assertEqual(self.client.put(self.url).status_code, 405)
