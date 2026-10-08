"""Bounded, read-only static analysis of changed files at a PR head commit."""
import base64
import binascii
import re
from urllib.parse import quote

from .github import GitHubError, fetch_public_pr, github_json, parse_pr_url
from .services import analyze_code
from .models import PullRequestReview


MAX_FILES = 5
MAX_BYTES = 1024 * 1024


def create_pr_review(url):
    """Persist a completed run, including partial or all-failed file results.

    A PR-level fetch failure raises before any record is created. The snapshot
    contains findings and metadata, not downloaded source file contents.
    """
    snapshot = analyze_public_pr(url)
    return PullRequestReview.objects.create(snapshot=snapshot)


def fetch_python_source(pr, file):
    repository = pr["head_repository"]
    # Validate upstream repository metadata before constructing API paths.
    parse_pr_url(f"https://github.com/{repository}/pull/1")
    sha = pr["head_sha"]
    if not re.fullmatch(r"[0-9a-fA-F]{40}", sha):
        raise GitHubError("The PR has an invalid head commit.")
    filename = file["filename"]
    if any(part in {"", ".", ".."} for part in filename.split("/")):
        raise GitHubError("Unsupported file path.")
    data = github_json(f"/repos/{repository}/contents/{quote(filename, safe='/')}?ref={sha}")
    try:
        if data["type"] != "file" or data.get("submodule_git_url"):
            raise GitHubError("Only regular source files can be analyzed.")
        if data["size"] > MAX_BYTES:
            raise GitHubError("File exceeds the 1 MB analysis limit.")
        if data["sha"] != file["sha"]:
            raise GitHubError("File revision does not match the PR snapshot. Please retry.")
        if data["encoding"] != "base64":
            raise GitHubError("GitHub did not provide supported inline file content.")
        raw = base64.b64decode("".join(data["content"].split()), validate=True)
        if len(raw) > MAX_BYTES:
            raise GitHubError("File exceeds the 1 MB analysis limit.")
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise GitHubError("File is not UTF-8 Python source.") from error
    except (KeyError, TypeError, ValueError, binascii.Error, AttributeError) as error:
        raise GitHubError("GitHub returned invalid file content.") from error


def analyze_public_pr(url):
    pr = fetch_public_pr(url, verify_snapshot=True)
    return analyze_file_snapshot(pr)


def analyze_file_snapshot(pr):
    """Analyze commit-pinned files for PR and deployment callers."""
    counts = dict.fromkeys(("CRITICAL", "HIGH", "MEDIUM", "LOW"), 0)
    attempted = analyzed = failed = skipped = 0
    for file in pr["files"]:
        file["analysis_status"] = "skipped"
        if not file["is_python"]:
            file["analysis_message"] = "Not a Python file."
        elif file["status"] == "removed":
            file["analysis_message"] = "Deleted file; no source exists at the head commit."
        elif attempted >= MAX_FILES:
            file["analysis_message"] = "Skipped: maximum 5 Python files per run."
        else:
            attempted += 1
            try:
                result = analyze_code(fetch_python_source(pr, file))
                file["analysis"] = result
                if result["success"]:
                    file["analysis_status"] = "analyzed"
                    analyzed += 1
                    for severity, count in result["counts"].items():
                        counts[severity] += count
                    continue
                file["analysis_message"] = result["summary"]
            except GitHubError as error:
                file["analysis_message"] = str(error)
            except (RecursionError, ValueError):
                file["analysis_message"] = "Source could not be parsed safely by the Python analyzer."
            file["analysis_status"] = "failed"
            failed += 1
            continue
        skipped += 1
    pr["analysis_summary"] = {
        "analyzed": analyzed, "failed": failed, "skipped": skipped,
        "counts": counts, "total_findings": sum(counts.values()),
        "partial": pr["incomplete"] or failed > 0 or any(
            f["is_python"] and f["status"] != "removed" and f["analysis_status"] == "skipped"
            for f in pr["files"]
        ),
    }
    return pr
