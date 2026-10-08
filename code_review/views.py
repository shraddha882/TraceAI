from core.ownership import owned_by
from django.shortcuts import render, redirect

from .services import create_code_review
from .models import CodeReview, PullRequestReview, PRReviewJob
from django.http import JsonResponse
from django.urls import reverse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_http_methods
from .forms import GitHubPRForm
from .github import GitHubError, fetch_public_pr


@require_http_methods(["GET", "POST"])
def github_pr(request):
    form = GitHubPRForm(request.POST if request.method == "POST" else None)
    pr = None
    if request.method == "POST" and form.is_valid():
        try:
            if request.POST.get("action") == "analyze":
                job = PRReviewJob.objects.create(owner=request.user, pr_url=form.cleaned_data["pr_url"])
                return redirect("code_review:job_detail", job_id=job.pk)
            else:
                pr = fetch_public_pr(form.cleaned_data["pr_url"])
        except GitHubError as error:
            form.add_error(None, str(error))
    return render(request, "code_review/github_pr.html", {"form": form, "pr": pr})


@require_http_methods(["GET"])
def job_detail(request, job_id):
    job = get_object_or_404(owned_by(PRReviewJob.objects.all(), request.user), pk=job_id)
    return render(request, 'code_review/job.html', {'job': job})


@require_http_methods(["GET"])
def job_status(request, job_id):
    job = get_object_or_404(owned_by(PRReviewJob.objects.all(), request.user), pk=job_id)
    response = JsonResponse({'status': job.status, 'error': job.error,
        'report_url': reverse('code_review:pr_detail', args=[job.review_id]) if job.review_id else None})
    response['Cache-Control'] = 'no-store'
    return response


@require_http_methods(["GET"])
def pr_review_detail(request, review_id):
    saved = get_object_or_404(owned_by(PullRequestReview.objects.all(), request.user), pk=review_id)
    return render(request, "code_review/github_pr.html", {
        "pr": saved.snapshot, "saved_pr_review": saved,
    })

def review_code(request):

    submitted_code = ""
    selected_language = "Python"
    review_result = None
    saved_review = None
    upload_error = None

    if request.method == "POST":

        selected_language = request.POST.get(
            "language",
            "Python"
        )

        submitted_code = request.POST.get(
            "code",
            ""
        )

        uploaded_file = request.FILES.get(
            "code_file"
        )

        # If a file is uploaded, use file content
        if uploaded_file:

            if not uploaded_file.name.lower().endswith(".py"):

                upload_error = (
                    "Only Python (.py) files are currently supported."
                )

            elif uploaded_file.size > 1024 * 1024:

                upload_error = (
                    "File is too large. Maximum size is 1 MB."
                )

            else:

                try:

                    submitted_code = uploaded_file.read().decode(
                        "utf-8-sig"
                    )

                    selected_language = "Python"

                except UnicodeDecodeError:

                    upload_error = (
                        "Unable to read this file. "
                        "Please upload a valid UTF-8 Python file."
                    )

        if not upload_error and not submitted_code.strip():
            upload_error = (
                "The uploaded file is empty. Please choose a Python file containing code."
                if uploaded_file
                else "Please upload a Python (.py) file or paste code to analyze."
            )

        if (
            submitted_code.strip()
            and not upload_error
        ):

            outcome = create_code_review(submitted_code, selected_language, owner=request.user)
            review_result = outcome.result
            saved_review = outcome.review

    context = {
        "submitted_code": submitted_code,
        "selected_language": selected_language,
        "review_result": review_result,
        "saved_review": saved_review,
        "upload_error": upload_error,
    }

    return render(
        request,
        "code_review/review.html",
        context
    )




def review_history(request):

    reviews = owned_by(CodeReview.objects.all(), request.user).order_by("-created_at")

    return render(
        request,
        "code_review/history.html",
        {
            "reviews": reviews,
            "pr_reviews": owned_by(PullRequestReview.objects.all(), request.user),
            "jobs": owned_by(PRReviewJob.objects.all(), request.user).order_by('-created_at')[:20],
        }
    )


def review_detail(request, review_id):

    review = get_object_or_404(
        owned_by(CodeReview.objects.all(), request.user),
        id=review_id
    )

    return render(
        request,
        "code_review/review_detail.html",
        {
            "review": review
        }
    )
