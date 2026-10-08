import re
from copy import deepcopy
from code_review.pr_analysis import analyze_file_snapshot
from code_review.github import GitHubError, github_json, parse_pr_url
from .models import DeploymentDiff


def review_deployment_diff(deployment):
    saved = DeploymentDiff.objects.filter(deployment=deployment).first()
    if saved is None:
        raise GitHubError("Fetch and save the Git diff before running code review.")
    if saved.code_review is not None:
        return saved
    snapshot = saved.snapshot
    files = deepcopy(snapshot["files"])
    for file in files:
        file["is_python"] = file["filename"].lower().endswith(".py")
    result = analyze_file_snapshot({
        "head_repository": snapshot["repository"], "head_sha": snapshot["head_sha"],
        "base_sha": snapshot["base_sha"], "files": files,
        "incomplete": snapshot["file_list_limited"],
    })
    # Preserve the first result if concurrent requests finish together.
    DeploymentDiff.objects.filter(pk=saved.pk, code_review__isnull=True).update(code_review=result)
    saved.refresh_from_db()
    return saved


def fetch_deployment_diff(deployment):
    repo = deployment.repository
    parse_pr_url(f"https://github.com/{repo}/pull/1")
    base, head = deployment.previous_commit_sha.lower(), deployment.commit_sha.lower()
    if not all(re.fullmatch(r"[a-f0-9]{40}", sha) for sha in (base, head)):
        raise GitHubError("A full previous and deployed commit SHA are required. Create a deployment record with both real SHAs.")
    try:
        head_data = github_json(f"/repos/{repo}/commits/{head}")
        data = github_json(f"/repos/{repo}/compare/{base}...{head}?per_page=1&page=1")
        if head_data["sha"] != head or data["base_commit"]["sha"] != base:
            raise GitHubError("GitHub returned a different commit revision. No diff was saved.")
        if data["status"] not in {"ahead", "identical"} or data["merge_base_commit"]["sha"] != base:
            raise GitHubError("Rollback or diverged history is not supported by this comparison yet. No diff was saved.")
        rows = data["files"]
        if not isinstance(rows, list):
            raise ValueError()
        files = []
        for row in rows[:100]:
            patch = row.get("patch")
            if patch is not None and not isinstance(patch, str):
                raise ValueError()
            files.append({
                "filename": row["filename"], "previous_filename": row.get("previous_filename", ""),
                "status": row["status"], "sha": row["sha"],
                "additions": row["additions"], "deletions": row["deletions"],
                "patch": (patch or "")[:20000], "patch_missing": not patch,
                "patch_truncated": bool(patch and len(patch) > 20000),
            })
        return {"version": 1, "repository": repo, "base_sha": base, "head_sha": head,
                "status": data["status"], "files": files,
                "file_list_limited": len(rows) >= 100,
                "url": f"https://github.com/{repo}/compare/{base}...{head}"}
    except (KeyError, TypeError, ValueError) as error:
        raise GitHubError("GitHub returned invalid comparison data. No diff was saved.") from error


def save_deployment_diff(deployment):
    existing = DeploymentDiff.objects.filter(deployment=deployment).first()
    if existing:
        return existing
    snapshot = fetch_deployment_diff(deployment)
    record, _ = DeploymentDiff.objects.get_or_create(deployment=deployment, defaults={"snapshot": snapshot})
    return record
