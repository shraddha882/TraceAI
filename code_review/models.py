from django.conf import settings
from django.db import models
import uuid


class PRReviewJob(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE)

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        RUNNING = 'running', 'Running'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pr_url = models.URLField(max_length=500)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)
    error = models.TextField(blank=True)
    review = models.OneToOneField('PullRequestReview', null=True, on_delete=models.PROTECT)


class PullRequestReview(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE)

    """A historical analysis snapshot, independent of subsequent PR changes."""
    snapshot = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"PR Review #{self.pk}"

# Create your models here.
class CodeReview(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE)


    LANGUAGE_CHOICES = [
        ("Python", "Python"),
        ("JavaScript", "JavaScript"),
        ("Java", "Java"),
        ("SQL", "SQL"),
    ]

    language = models.CharField(
        max_length=30,
        choices=LANGUAGE_CHOICES,
        default="Python",
    )

    source_code = models.TextField()

    summary = models.TextField(
        blank=True
    )

    findings = models.JSONField(
        default=list,
        blank=True,
    )

    critical_count = models.PositiveIntegerField(
        default=0
    )

    high_count = models.PositiveIntegerField(
        default=0
    )

    medium_count = models.PositiveIntegerField(
        default=0
    )

    low_count = models.PositiveIntegerField(
        default=0
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return (
            f"{self.language} Review "
            f"#{self.pk}"
        )
