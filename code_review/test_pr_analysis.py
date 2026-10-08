from core.testing import StaffTestCase
import base64
from copy import deepcopy
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .github import GitHubError, fetch_public_pr
from .models import CodeReview
from .pr_analysis import analyze_public_pr, fetch_python_source
from .test_github import URL, METADATA, FILES
from .jobs import run_next_job
from .models import PRReviewJob


def preview():
    return {
        "url": URL, "repository": "example/project", "number": "12",
        "title": "Example", "author": "author", "state": "open",
        "head_repository": "contributor/fork", "head_sha": "a" * 40,
        "base_sha": "b" * 40, "incomplete": False, "total_files": 1,
        "files": [{"filename": "src/test file.py", "sha": "c" * 40,
                   "status": "modified", "is_python": True, "additions": 1, "deletions": 0}],
    }


def content(source=b'requests.get(url)'):
    return {"type": "file", "size": len(source), "sha": "c" * 40,
            "encoding": "base64", "content": base64.b64encode(source).decode()}


class PRAnalysisTests(SimpleTestCase):
    @patch("code_review.pr_analysis.github_json", return_value=content())
    def test_fetch_uses_fork_and_exact_sha_with_encoded_path(self, fetch):
        pr = preview()
        self.assertEqual(fetch_python_source(pr, pr["files"][0]), 'requests.get(url)')
        fetch.assert_called_once_with('/repos/contributor/fork/contents/src/test%20file.py?ref=' + 'a' * 40)

    def test_invalid_or_unsupported_content_is_not_analyzed(self):
        for changes in ({"size": 1024 * 1024 + 1}, {"type": "symlink"},
                        {"sha": "d" * 40}, {"encoding": "none"}, {"content": "!!!"}):
            with self.subTest(changes=changes), patch("code_review.pr_analysis.github_json", return_value={**content(), **changes}):
                pr = preview()
                with self.assertRaises(GitHubError):
                    fetch_python_source(pr, pr["files"][0])

    def test_non_utf8_and_bom(self):
        pr = preview()
        with patch("code_review.pr_analysis.github_json", return_value=content(b'\xff')):
            with self.assertRaisesRegex(GitHubError, "UTF-8"):
                fetch_python_source(pr, pr["files"][0])
        with patch("code_review.pr_analysis.github_json", return_value=content(b'\xef\xbb\xbfpass')):
            self.assertEqual(fetch_python_source(pr, pr["files"][0]), "pass")

    def test_snapshot_change_aborts(self):
        latest = deepcopy(METADATA)
        latest["head"]["sha"] = "d" * 40
        with patch("code_review.github.github_json", side_effect=[METADATA, FILES, latest]):
            with self.assertRaisesRegex(GitHubError, "changed while loading"):
                fetch_public_pr(URL, verify_snapshot=True)

    def test_aggregation_and_non_python_deleted_files(self):
        pr = preview()
        pr["files"] += [
            {"filename": "gone.py", "status": "removed", "is_python": True},
            {"filename": "readme.md", "status": "modified", "is_python": False},
        ]
        with patch("code_review.pr_analysis.fetch_public_pr", return_value=pr) as fetch:
            with patch("code_review.pr_analysis.fetch_python_source", return_value='requests.get(url)') as source:
                result = analyze_public_pr(URL)
        fetch.assert_called_once_with(URL, verify_snapshot=True)
        source.assert_called_once()
        self.assertEqual(result["analysis_summary"]["analyzed"], 1)
        self.assertEqual(result["analysis_summary"]["skipped"], 2)
        self.assertEqual(result["analysis_summary"]["counts"]["HIGH"], 1)

    def test_file_limit_is_explicit(self):
        pr = preview()
        pr["files"] = [dict(pr["files"][0], filename=f"file{i}.py") for i in range(6)]
        with patch("code_review.pr_analysis.fetch_public_pr", return_value=pr), patch("code_review.pr_analysis.fetch_python_source", return_value="pass") as fetch:
            result = analyze_public_pr(URL)
        self.assertEqual(fetch.call_count, 5)
        self.assertTrue(result["analysis_summary"]["partial"])
        self.assertEqual(result["files"][-1]["analysis_status"], "skipped")

    def test_failure_does_not_hide_successful_file(self):
        pr = preview()
        pr["files"].append(dict(pr["files"][0], filename="second.py"))
        with patch("code_review.pr_analysis.fetch_public_pr", return_value=pr), patch("code_review.pr_analysis.fetch_python_source", side_effect=[GitHubError("Unavailable"), "pass"]):
            result = analyze_public_pr(URL)
        self.assertEqual(result["analysis_summary"]["failed"], 1)
        self.assertEqual(result["analysis_summary"]["analyzed"], 1)
        self.assertTrue(result["analysis_summary"]["partial"])

    def test_syntax_failure_is_not_clean(self):
        with patch("code_review.pr_analysis.fetch_public_pr", return_value=preview()), patch("code_review.pr_analysis.fetch_python_source", return_value="def broken("):
            result = analyze_public_pr(URL)
        self.assertEqual(result["analysis_summary"]["analyzed"], 0)
        self.assertEqual(result["analysis_summary"]["failed"], 1)
        self.assertIn("syntax_error", result["files"][0]["analysis"])


class PRAnalysisPageTests(StaffTestCase):
    def test_analysis_renders_findings_without_saving(self):
        with patch("code_review.pr_analysis.fetch_public_pr", return_value=preview()), patch("code_review.pr_analysis.fetch_python_source", return_value="requests.get(url)"):
            response = self.client.post(reverse("code_review:github"), {"pr_url": URL, "action": "analyze"}, follow=True)
            run_next_job()
            response = self.client.get(reverse('code_review:pr_detail', args=[PRReviewJob.objects.get().review_id]))
        self.assertContains(response, "HTTP request has no timeout")
        self.assertContains(response, "Line 1")
        self.assertContains(response, "src/test file.py")
        self.assertContains(response, "Suggested fix:")
        self.assertEqual(CodeReview.objects.count(), 0)

    def test_all_failed_message_and_escaping(self):
        with patch("code_review.pr_analysis.fetch_public_pr", return_value=preview()), patch("code_review.pr_analysis.fetch_python_source", side_effect=GitHubError("<script>bad</script>")):
            response = self.client.post(reverse("code_review:github"), {"pr_url": URL, "action": "analyze"}, follow=True)
            run_next_job()
            response = self.client.get(reverse('code_review:pr_detail', args=[PRReviewJob.objects.get().review_id]))
        self.assertContains(response, "This is not a clean review")
        self.assertContains(response, "Partial analysis")
        self.assertNotContains(response, "<script>bad</script>")
