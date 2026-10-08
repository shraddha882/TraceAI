from core.testing import StaffTestCase
from html.parser import HTMLParser
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils.html import escape

from .models import CodeReview
from .analyzers.python_analyzer import analyze_python_code
from .services import analyze_code, create_code_review


class AnalysisServiceTests(SimpleTestCase):
    # SimpleTestCase forbids database queries, ensuring this path is reusable
    # without persisting an independent report for every incident code snippet.
    def test_analysis_matches_existing_engine_without_database_access(self):
        source = 'requests.get(url)\npassword = "demo"'
        self.assertEqual(analyze_code(source), analyze_python_code(source))

    def test_clean_code_is_a_successful_report(self):
        result = analyze_code('value = 1')
        self.assertTrue(result["success"])
        self.assertEqual(result["findings"], [])
        self.assertEqual(sum(result["counts"].values()), 0)

    def test_empty_input_and_unsupported_language_do_not_reach_analyzer(self):
        with patch("code_review.services.analyze_python_code") as analyzer:
            for source, language in (("", "Python"), (" \n\t", "Python"), ("SELECT 1", "SQL")):
                with self.subTest(source=source, language=language):
                    self.assertFalse(analyze_code(source, language)["success"])
            analyzer.assert_not_called()

    def test_syntax_details_are_preserved(self):
        result = analyze_code('def broken(')
        self.assertFalse(result["success"])
        self.assertEqual(result["syntax_error"]["line"], 1)


class ReviewServiceTests(StaffTestCase):
    def test_service_saves_matching_report_and_analyzes_once(self):
        source = 'requests.get(url)\neval(expression)'
        with patch("code_review.services.analyze_python_code", wraps=analyze_python_code) as analyzer:
            outcome = create_code_review(source)
            analyzer.assert_called_once_with(source)
        self.assertEqual(CodeReview.objects.count(), 1)
        saved = CodeReview.objects.get(pk=outcome.review.pk)
        self.assertEqual(saved.source_code, source)
        self.assertEqual(saved.language, "Python")
        self.assertEqual(saved.findings, outcome.result["findings"])
        self.assertEqual(saved.summary, outcome.result["summary"])
        for severity in ("critical", "high", "medium", "low"):
            self.assertEqual(getattr(saved, severity + "_count"), outcome.result["counts"][severity.upper()])

    def test_failed_inputs_never_create_reports(self):
        for source, language in (("", "Python"), ("def broken(", "Python"), ("SELECT 1", "SQL")):
            with self.subTest(source=source):
                outcome = create_code_review(source, language)
                self.assertFalse(outcome.result["success"])
                self.assertIsNone(outcome.review)
        self.assertEqual(CodeReview.objects.count(), 0)

    def test_clean_report_is_saved(self):
        outcome = create_code_review("value = 1")
        self.assertIsNotNone(outcome.review.pk)
        self.assertEqual(outcome.review.findings, [])

    def test_analyzer_failure_is_not_reported_as_success(self):
        with patch("code_review.services.analyze_python_code", side_effect=RuntimeError("analysis failed")):
            with self.assertRaisesRegex(RuntimeError, "analysis failed"):
                create_code_review("pass")
        self.assertEqual(CodeReview.objects.count(), 0)


class HTTPTimeoutTests(SimpleTestCase):
    def findings(self, source):
        result = analyze_python_code(source)
        self.assertTrue(result["success"])
        return [item for item in result["findings"]
                if item["title"] == "HTTP request has no timeout"]

    def test_all_methods_and_import_styles(self):
        for method in ("get", "post", "put", "patch", "delete", "request", "head", "options"):
            args = '"GET", url' if method == "request" else 'url'
            for source in (f'requests.{method}({args})',
                           f'import requests as http\nhttp.{method}({args})',
                           f'from requests import {method}\n{method}({args})',
                           f'from requests import {method} as fetch\nfetch({args})'):
                with self.subTest(source=source):
                    findings = self.findings(source)
                    self.assertEqual(len(findings), 1)
                    self.assertEqual(findings[0]["severity"], "HIGH")
                    self.assertEqual(findings[0]["line"], len(source.splitlines()))

    def test_none_disables_timeout(self):
        findings = self.findings('requests.get(url, timeout=None)')
        self.assertEqual(len(findings), 1)
        self.assertIn("timeout=None", findings[0]["description"])

    def test_explicit_and_unknown_timeouts_are_not_reported(self):
        for source in ('requests.get(url, timeout=5)',
                       'requests.get(url, timeout=(3, 10))',
                       'requests.get(url, timeout=configured_timeout)',
                       'requests.get(url, **options)'):
            with self.subTest(source=source):
                self.assertEqual(self.findings(source), [])

    def test_unrelated_and_shadowed_names_are_ignored(self):
        for source in ('get(url)', 'cache.get(key)',
                       'from other import get\nget(url)',
                       'import other as requests\nrequests.get(url)',
                       'from requests import get\nget = other\nget(url)',
                       'import requests as http\ndef f(http):\n    http.get(url)',
                       'from requests import get\ndef f():\n    get(url)\n    get = other',
                       'from requests import get\nf = lambda get: get(url)',
                       '# requests.get(url)', '\'\'\'requests.get(url)\'\'\''):
            with self.subTest(source=source):
                self.assertEqual(self.findings(source), [])

    def test_function_import_does_not_leak_and_parent_binding_is_restored(self):
        source = ('from requests import get\n'
                  'def first(get):\n    get(url)\n'
                  'def second():\n    import requests as http\n    http.head(url)\n'
                  'http.head(url)\nget(url)')
        self.assertEqual([item["line"] for item in self.findings(source)], [6, 8])

    def test_async_function_keeps_module_alias(self):
        self.assertEqual(len(self.findings('import requests as http\nasync def f():\n    http.get(url)')), 1)

    def test_demo_has_five_high_findings(self):
        source = (Path(__file__).resolve().parent.parent / "examples" / "http_timeout_demo.py").read_text()
        result = analyze_python_code(source)
        self.assertEqual(len(self.findings(source)), 5)
        self.assertEqual(result["counts"]["HIGH"], 5)


class SecretAnalysisTests(SimpleTestCase):
    def findings(self, source):
        result = analyze_python_code(source)
        self.assertTrue(result["success"])
        return [item for item in result["findings"]
                if item["title"] == "Potential hard-coded secret"]

    def test_sensitive_name_variants(self):
        for name in ("password", "API_KEY", "DB_PASSWORD", "SECRET_KEY",
                     "apiKey", "clientSecret", "dbPassword", "serviceAPIKey",
                     "PRIVATE_KEY", "refresh_token", "auth_token", "pwd"):
            with self.subTest(name=name):
                findings = self.findings(f'{name} = "fixture-value"')
                self.assertEqual(len(findings), 1)
                self.assertEqual(findings[0]["severity"], "CRITICAL")

    def test_supported_assignment_forms(self):
        sources = [
            'api_key: str = "fixture-value"',
            'self.api_key = "fixture-value"',
            'config["password"] = "fixture-value"',
            'config = {"database": {"password": "fixture-value"}}',
            'authenticate(password="fixture-value")',
            'authenticate(**{"api_key": "fixture-value"})',
        ]
        for source in sources:
            with self.subTest(source=source):
                self.assertEqual(len(self.findings(source)), 1)

    def test_runtime_values_and_empty_literals_are_ignored(self):
        for source in ('password = os.getenv("DB_PASSWORD")',
                       'api_key = os.environ["API_KEY"]',
                       'config = {"password": supplied_password}',
                       'authenticate(password=get_password())',
                       'password = ""', 'password = "   "',
                       'password = None', 'password = 123', 'api_key: str'):
            with self.subTest(source=source):
                self.assertEqual(self.findings(source), [])

    def test_unrelated_names_comments_and_docstrings_are_ignored(self):
        for source in ('password_hint = "remember me"',
                       'secretary = "Ada"', 'token_count = "10"',
                       'api_key_name = "API_KEY"',
                       '# password = "fixture-value"',
                       '\'\'\'password = "fixture-value"\'\'\''):
            with self.subTest(source=source):
                self.assertEqual(self.findings(source), [])

    def test_finding_does_not_repeat_literal_or_sensitive_key(self):
        value = "unique-credential-fixture"
        source = f'config = {{"{value}_password": "{value}"}}'
        findings = self.findings(source)
        self.assertEqual(len(findings), 1)
        self.assertNotIn(value, str(findings))

    def test_multiline_value_location_and_counts(self):
        result = analyze_python_code('config = {\n    "password":\n        "fixture-value",\n    "api_key": "another-fixture",\n}')
        self.assertEqual([item["line"] for item in result["findings"]], [3, 4])
        self.assertEqual(result["counts"]["CRITICAL"], 2)

    def test_demo_has_five_findings(self):
        source = (Path(__file__).resolve().parent.parent / "examples" / "secret_review_demo.py").read_text()
        self.assertEqual(len(self.findings(source)), 5)


class DatabaseConnectionTests(SimpleTestCase):
    def leak_lines(self, source):
        result = analyze_python_code(dedent(source).strip())
        self.assertTrue(result["success"])
        return [item["line"] for item in result["findings"]
                if item["title"] == "Database connection may not be closed"]

    def test_close_in_another_function_does_not_hide_leak(self):
        self.assertEqual(self.leak_lines('''
            def leaking():
                conn = psycopg2.connect()
            def cleaned():
                conn = psycopg2.connect()
                conn.close()
        '''), [2])

    def test_each_function_retains_its_own_acquisition(self):
        self.assertEqual(self.leak_lines('''
            def first():
                conn = psycopg2.connect()
            async def second():
                conn = psycopg2.connect()
        '''), [2, 4])

    def test_nested_function_and_lambda_do_not_close_parent(self):
        for cleanup in ('def cleanup():\n    conn.close()', 'cleanup = lambda: conn.close()'):
            with self.subTest(cleanup=cleanup):
                self.assertEqual(self.leak_lines('conn = sqlite3.connect()\n' + cleanup), [1])

    def test_reassignment_preserves_previous_leak(self):
        self.assertEqual(self.leak_lines('''
            conn = psycopg2.connect()
            conn = psycopg2.connect()
            conn.close()
        '''), [1])

    def test_unrelated_reassignment_does_not_close_original(self):
        self.assertEqual(self.leak_lines('''
            conn = psycopg2.connect()
            conn = other_resource
            conn.close()
        '''), [1])

    def test_earlier_close_does_not_close_new_connection(self):
        self.assertEqual(self.leak_lines('''
            conn.close()
            conn = psycopg2.connect()
        '''), [2])

    def test_finally_cleanup_and_sequential_reuse(self):
        self.assertEqual(self.leak_lines('''
            def cleaned():
                conn = psycopg2.connect()
                try:
                    work(conn)
                finally:
                    conn.close()
                conn = psycopg2.connect()
                conn.close()
        '''), [])

    def test_annotated_connection_is_tracked(self):
        self.assertEqual(self.leak_lines('conn: Connection = psycopg2.connect()'), [1])

    def test_methods_have_separate_scopes(self):
        self.assertEqual(self.leak_lines('''
            class Repository:
                def first(self):
                    conn = psycopg2.connect()
                def second(self):
                    conn = psycopg2.connect()
                    conn.close()
        '''), [3])

    def test_demo_has_two_leaks(self):
        source = (Path(__file__).resolve().parent.parent / "examples" / "resource_leak_demo.py").read_text()
        self.assertEqual(len(self.leak_lines(source)), 2)


class SQLAnalysisTests(SimpleTestCase):
    def sql_findings(self, code):
        result = analyze_python_code(code)
        self.assertTrue(result["success"])
        return [finding for finding in result["findings"]
                if finding["title"] == "Potential SQL injection"]

    def test_dynamic_query_construction(self):
        expressions = [
            'f"SELECT * FROM users WHERE id = {user_id}"',
            '"SELECT * FROM users WHERE id = " + user_id',
            '"SELECT * FROM users WHERE id = %s" % user_id',
            '"SELECT * FROM users WHERE id = {}".format(user_id)',
            '"INSERT INTO users(name) VALUES (\'%s\')" % name',
            'f"UPDATE users SET name = \'{name}\'"',
            '"DELETE FROM users WHERE id = {id}".format(id=user_id)',
        ]
        for expression in expressions:
            with self.subTest(expression=expression):
                findings = self.sql_findings("query = " + expression)
                self.assertEqual(len(findings), 1)
                self.assertEqual(findings[0]["severity"], "CRITICAL")
                self.assertEqual(findings[0]["line"], 1)

    def test_multiline_query_reports_expression_start(self):
        source = '\nquery = (\n    f"""SELECT *\n    FROM users\n    WHERE id = {user_id}"""\n)'
        findings = self.sql_findings(source)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["line"], 3)

    def test_safe_queries_and_non_code_are_ignored(self):
        sources = [
            'cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))',
            'cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))',
            'query = f"SELECT * FROM users"',
            'query = "SELECT * " + "FROM users"',
            '# query = f"SELECT * FROM users WHERE id = {user_id}"',
            '\'\'\'Example: f"SELECT * FROM users WHERE id = {user_id}"\'\'\'',
            'message = f"Updated {count} records"',
            'message = f"Selection for {name}"',
        ]
        for source in sources:
            with self.subTest(source=source):
                self.assertEqual(self.sql_findings(source), [])

    def test_nested_concatenation_is_not_duplicated(self):
        findings = self.sql_findings(
            'query = "SELECT * FROM users WHERE name = " + name + " AND id = " + user_id'
        )
        self.assertEqual(len(findings), 1)

    def test_separate_queries_counts_and_order(self):
        result = analyze_python_code(
            'first = f"SELECT * FROM users WHERE id = {user_id}"\n'
            'second = "DELETE FROM users WHERE id = %s" % user_id'
        )
        self.assertEqual([item["line"] for item in result["findings"]], [1, 2])
        self.assertEqual(result["counts"]["CRITICAL"], 2)

    def test_submitted_code_is_never_executed(self):
        with patch("builtins.print") as output:
            self.sql_findings('print("must not execute")\nquery = f"SELECT * FROM t WHERE id = {value}"')
        output.assert_not_called()

    def test_invalid_python_keeps_syntax_error_response(self):
        result = analyze_python_code('query = f"SELECT * FROM users WHERE id = {"')
        self.assertFalse(result["success"])
        self.assertEqual(result["findings"], [])
        self.assertIn("syntax_error", result)


class FormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = []

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


class CodeReviewTests(StaffTestCase):
    source = 'eval("1 + 1")\ntry:\n    pass\nexcept:\n    pass\n'

    def setUp(self):
        self.url = reverse("code_review:review")

    def upload(self, content, name="example.py", **data):
        return self.client.post(self.url, {
            **data,
            "code_file": SimpleUploadedFile(name, content),
        })

    def assert_saved_result(self, response, source):
        self.assertEqual(response.status_code, 200)
        result = response.context["review_result"]
        self.assertTrue(result["success"])
        review = CodeReview.objects.latest("id")
        self.assertEqual(review.source_code, source)
        self.assertEqual(review.language, "Python")
        self.assertEqual(review.summary, result["summary"])
        self.assertEqual(review.findings, result["findings"])
        for severity in ("critical", "high", "medium", "low"):
            self.assertEqual(getattr(review, severity + "_count"),
                             result["counts"][severity.upper()])
        return review

    def test_form_allows_file_only_and_paste_only(self):
        response = self.client.get(self.url)
        parser = FormParser()
        parser.feed(response.content.decode())
        form = next(attrs for tag, attrs in parser.elements if tag == "form" and attrs.get('enctype') == 'multipart/form-data')
        self.assertEqual(form["enctype"], "multipart/form-data")
        for name in ("code", "code_file"):
            attrs = next(attrs for _, attrs in parser.elements if attrs.get("name") == name)
            self.assertNotIn("required", attrs)
        self.assertContains(response, 'name="csrfmiddlewaretoken"')

    def test_pasted_code_is_analyzed_and_saved(self):
        response = self.client.post(self.url, {"code": self.source, "language": "Python"})
        self.assert_saved_result(response, self.source)
        self.assertEqual(CodeReview.objects.count(), 1)

    def test_sql_findings_are_rendered_and_saved_for_paste_and_upload(self):
        source = 'query = "SELECT * FROM users WHERE id = {}".format(user_id)'
        for response in (self.client.post(self.url, {"code": source}),
                         self.upload(source.encode())):
            review = self.assert_saved_result(response, source)
            self.assertEqual(review.critical_count, 1)
            self.assertContains(response, "Potential SQL injection")
            detail = self.client.get(reverse("code_review:detail", args=[review.pk]))
            self.assertContains(detail, "Potential SQL injection")

    def test_file_only_is_analyzed_and_saved(self):
        self.assert_saved_result(self.upload(self.source.encode()), self.source)
        self.assertEqual(CodeReview.objects.count(), 1)

    def test_http_timeout_findings_are_saved_for_paste_and_upload(self):
        source = 'from requests import get as fetch\nfetch(url, timeout=None)'
        for mode in ("paste", "upload"):
            with self.subTest(mode=mode):
                response = (self.client.post(self.url, {"code": source})
                            if mode == "paste" else self.upload(source.encode()))
                review = self.assert_saved_result(response, source)
                self.assertEqual(review.high_count, 1)
                self.assertContains(response, "HTTP request has no timeout")
                detail = self.client.get(reverse("code_review:detail", args=[review.pk]))
                self.assertContains(detail, "timeout=None")

    def test_secret_findings_are_saved_without_repeating_value(self):
        source = 'config = {"DB_PASSWORD": "unique-fixture-credential"}'
        response = self.upload(source.encode())
        review = self.assert_saved_result(response, source)
        self.assertEqual(review.critical_count, 1)
        self.assertNotIn("unique-fixture-credential", str(review.findings))
        self.assertContains(response, "Potential hard-coded secret")
        detail = self.client.get(reverse("code_review:detail", args=[review.pk]))
        self.assertContains(detail, "Potential hard-coded secret")

    def test_database_leak_report_is_saved_and_rendered(self):
        source = 'def leaking():\n    conn = psycopg2.connect()\ndef other():\n    conn.close()'
        response = self.upload(source.encode())
        review = self.assert_saved_result(response, source)
        self.assertEqual(review.high_count, 1)
        self.assertEqual(review.findings[0]["line"], 2)
        self.assertContains(response, "Database connection may not be closed")
        detail = self.client.get(reverse("code_review:detail", args=[review.pk]))
        self.assertContains(detail, "Database connection may not be closed")

    def test_upload_takes_precedence_and_selects_python(self):
        response = self.upload(self.source.encode(), code="different pasted code", language="SQL")
        self.assert_saved_result(response, self.source)
        self.assertEqual(response.context["selected_language"], "Python")

    def test_utf8_bom_unicode_and_uppercase_extension(self):
        source = 'message = "caf\u00e9"\n'
        self.assert_saved_result(self.upload(source.encode("utf-8-sig"), "EXAMPLE.PY"), source)

    def test_invalid_uploads_do_not_analyze_or_save_pasted_code(self):
        cases = [
            ("example.txt", b"pass", "Only Python"),
            ("example.py.exe", b"pass", "Only Python"),
            ("large.py", b"#" * (1024 * 1024 + 1), "too large"),
            ("invalid.py", b"\xff\xfe", "valid UTF-8"),
            ("empty.py", b"", "empty"),
            ("blank.py", b" \r\n\t", "empty"),
        ]
        for name, content, error in cases:
            with self.subTest(name=name), patch("code_review.views.create_code_review") as analyzer:
                response = self.upload(content, name, code=self.source)
                self.assertContains(response, error)
                self.assertIsNone(response.context["review_result"])
                analyzer.assert_not_called()
                self.assertEqual(CodeReview.objects.count(), 0)

    def test_invalid_file_preserves_paste_and_language(self):
        response = self.upload(b"pass", "example.txt", code=self.source, language="SQL")
        self.assertEqual(response.context["submitted_code"], self.source)
        self.assertContains(response, "<option selected>SQL</option>", html=True)

    def test_one_megabyte_file_is_accepted(self):
        source = "#" * (1024 * 1024)
        self.assert_saved_result(self.upload(source.encode()), source)

    def test_empty_pasted_input_shows_error(self):
        for source in ("", " \n\t"):
            response = self.client.post(self.url, {"code": source})
            self.assertContains(response, "Please upload a Python (.py) file or paste code")
        self.assertEqual(CodeReview.objects.count(), 0)

    def test_syntax_errors_are_displayed_without_saving(self):
        for response in (self.upload(b"def broken("),
                         self.client.post(self.url, {"code": "def broken("})):
            self.assertContains(response, "Syntax Error")
            self.assertFalse(response.context["review_result"]["success"])
        self.assertEqual(CodeReview.objects.count(), 0)

    def test_unsupported_paste_language_keeps_existing_behavior(self):
        response = self.client.post(self.url, {"code": "SELECT 1", "language": "SQL"})
        self.assertContains(response, "SQL analysis is not available yet.")
        self.assertEqual(CodeReview.objects.count(), 0)

    def test_existing_reports_and_new_upload_appear_in_history(self):
        old = CodeReview.objects.create(source_code="pass", summary="Existing saved report",
                                        findings=[], low_count=2)
        before = CodeReview.objects.filter(pk=old.pk).values().get()
        new = self.assert_saved_result(self.upload(self.source.encode()), self.source)
        history = self.client.get(reverse("code_review:history"))
        self.assertEqual(list(history.context["reviews"]), [new, old])
        for review in (old, new):
            url = reverse("code_review:detail", args=[review.pk])
            self.assertContains(history, url)
            report = self.client.get(url)
            self.assertContains(report, escape(review.source_code))
            self.assertContains(report, review.summary)
            for finding in review.findings:
                self.assertContains(report, escape(finding["title"]))
        self.assertEqual(CodeReview.objects.filter(pk=old.pk).values().get(), before)

    def test_source_is_escaped_in_review_and_saved_report(self):
        source = 'message = "</textarea><script>alert(1)</script>"'
        response = self.upload(source.encode())
        review = self.assert_saved_result(response, source)
        for page in (response, self.client.get(reverse("code_review:detail", args=[review.pk]))):
            self.assertNotContains(page, "<script>alert(1)</script>")
            self.assertContains(page, escape(source))

    def test_missing_saved_report_returns_404(self):
        self.assertEqual(self.client.get(reverse("code_review:detail", args=[999])).status_code, 404)
