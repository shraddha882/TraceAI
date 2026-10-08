"""Read-only public PR preview. No credentials or repository code execution."""
import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


class GitHubError(Exception):
    """A user-facing validation or upstream error."""


def parse_pr_url(value):
    match = re.fullmatch(
        r"https://github\.com/([A-Za-z0-9-]+)/([A-Za-z0-9_.-]+)/pull/([1-9][0-9]{0,9})/?",
        value.strip(),
    )
    if not match or match[2] in {".", ".."}:
        raise GitHubError("Enter a public PR URL such as https://github.com/owner/repo/pull/123.")
    return match.groups()


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def github_json(path):
    # Paths are constructed from validated URL components, never upstream links.
    request = Request("https://api.github.com" + path, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "TraceAI-Public-PR-Preview",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    try:
        with build_opener(NoRedirects()).open(request, timeout=10) as response:
            content = response.read(4 * 1024 * 1024 + 1)
            if len(content) > 4 * 1024 * 1024:
                raise GitHubError("This PR response is too large to preview. Try a smaller PR.")
            return json.loads(content)
    except HTTPError as error:
        if error.code == 404:
            message = "PR not found or not publicly accessible. Check the repository and PR number."
        elif error.code in {403, 429}:
            message = "GitHub denied the request or its public API limit was reached. Try again later."
        elif error.code in {301, 302, 307, 308}:
            message = "This repository may have moved. Use its current GitHub PR URL."
        else:
            message = "GitHub could not load this PR. Please try again later."
        raise GitHubError(message) from error
    except (URLError, TimeoutError, OSError) as error:
        raise GitHubError("Unable to reach GitHub within the request timeout. Please try again.") from error
    except (ValueError, UnicodeError) as error:
        raise GitHubError("GitHub returned an unreadable response. Please try again.") from error


def fetch_public_pr(url, *, verify_snapshot=False):
    owner, repo, number = parse_pr_url(url)
    path = f"/repos/{owner}/{repo}/pulls/{number}"
    try:
        data = github_json(path)
        rows = github_json(path + "/files?per_page=100&page=1")
        if verify_snapshot:
            latest = github_json(path)
            if any(latest[side]["sha"] != data[side]["sha"] for side in ("head", "base")):
                raise GitHubError("The PR changed while loading. Please analyze it again.")
        if not isinstance(data, dict) or not isinstance(rows, list):
            raise ValueError("Invalid response shape")
        files = []
        for row in rows:
            files.append({
                "filename": row["filename"], "status": row["status"],
                "additions": row["additions"], "deletions": row["deletions"],
                "previous_filename": row.get("previous_filename", ""),
                "is_python": row["filename"].lower().endswith(".py"),
                "sha": row.get("sha", ""),
            })
        total = data["changed_files"]
        if not isinstance(total, int) or total < 0:
            raise ValueError("Invalid file count")
        return {
            "url": f"https://github.com/{owner}/{repo}/pull/{number}",
            "repository": f"{owner}/{repo}", "number": number,
            "title": data["title"], "author": data["user"]["login"],
            "state": "merged" if data.get("merged") else data["state"],
            "head_sha": data["head"]["sha"], "base_sha": data["base"]["sha"],
            "head_repository": (data["head"].get("repo") or {}).get("full_name", f"{owner}/{repo}"),
            "files": files, "total_files": total,
            "incomplete": total > len(files),
        }
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise GitHubError("GitHub returned incomplete PR data. Please try again.") from error
