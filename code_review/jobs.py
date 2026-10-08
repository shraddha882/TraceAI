"""Durable PostgreSQL queue; network calls run outside database transactions."""
import logging
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from .models import PRReviewJob, PullRequestReview
from .pr_analysis import analyze_public_pr
from .github import GitHubError

logger = logging.getLogger(__name__)


def run_next_job():
    # Interrupted workers do not leave jobs marked running forever. Never retry
    # automatically: the PR head may have changed since the original attempt.
    PRReviewJob.objects.filter(status='running', started_at__lt=timezone.now() - timedelta(minutes=15)).update(
        status='failed', finished_at=timezone.now(), error='Worker interrupted or time limit exceeded. Submit a new analysis.')
    with transaction.atomic():
        job = PRReviewJob.objects.select_for_update(skip_locked=True).filter(status='pending').order_by('created_at', 'pk').first()
        if job is None:
            return False
        job.status = 'running'
        job.started_at = timezone.now()
        job.save(update_fields=['status', 'started_at'])
    try:
        snapshot = analyze_public_pr(job.pr_url)
        with transaction.atomic():
            current = PRReviewJob.objects.select_for_update().get(pk=job.pk)
            if current.status == 'running':
                current.review = PullRequestReview.objects.create(snapshot=snapshot, owner_id=current.owner_id)
                current.status = 'completed'
                current.finished_at = timezone.now()
                current.save(update_fields=['review', 'status', 'finished_at'])
    except Exception as error:
        message = str(error) if isinstance(error, GitHubError) else 'Analysis failed unexpectedly. Please submit a new analysis.'
        logger.warning('PR job %s failed (%s)', job.pk, type(error).__name__)
        PRReviewJob.objects.filter(pk=job.pk, status='running').update(status='failed', error=message, finished_at=timezone.now())
    return True
