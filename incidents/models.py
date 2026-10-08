from django.conf import settings
from django.db import models
import uuid


class RCAJob(models.Model):
    use_ai = models.BooleanField(default=False)
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        RUNNING = 'running', 'Running'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    incident = models.ForeignKey('Incident', on_delete=models.CASCADE, related_name='rca_jobs')
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)
    error = models.TextField(blank=True)
    report = models.OneToOneField('RCAReport', null=True, on_delete=models.PROTECT)

    class Meta:
        ordering = ['-created_at', '-pk']
        constraints = [models.UniqueConstraint(fields=['incident'], condition=models.Q(status__in=['pending', 'running']), name='one_active_rca_per_incident')]

from django.core.validators import RegexValidator


class Deployment(models.Model):
    incident = models.ForeignKey("Incident", on_delete=models.CASCADE, related_name="deployments")
    service = models.CharField(max_length=120)
    environment = models.CharField(max_length=80)
    deployed_at = models.DateTimeField()
    repository = models.CharField(max_length=200)
    commit_sha = models.CharField(max_length=40, validators=[RegexValidator(r"\A[0-9a-fA-F]{40}\Z", "Enter a full 40-character Git commit SHA.")])
    previous_commit_sha = models.CharField(max_length=40, blank=True, validators=[RegexValidator(r"\A[0-9a-fA-F]{40}\Z", "Enter a full 40-character Git commit SHA.")])
    notes = models.TextField(blank=True, max_length=5000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["deployed_at", "pk"]

    @property
    def relative_time(self):
        seconds = (self.deployed_at - self.incident.occurred_at).total_seconds()
        if seconds == 0:
            return "At the incident occurrence time"
        direction = "before" if seconds < 0 else "after"
        return f"{abs(seconds):g} seconds {direction} incident"


class Incident(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE)

    title = models.CharField(max_length=200)
    affected_service = models.CharField(max_length=120)
    description = models.TextField(max_length=10000)
    occurred_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return self.title


class DeploymentDiff(models.Model):
    deployment = models.OneToOneField(Deployment, on_delete=models.CASCADE, related_name="saved_diff")
    snapshot = models.JSONField()
    code_review = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class RCAReport(models.Model):
    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, related_name="rca_reports")
    snapshot = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]


class LogEvidence(models.Model):
    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, related_name="log_evidence")
    source_name = models.CharField(max_length=255)
    source_text = models.TextField()
    analysis = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]


class TraceEvidence(models.Model):
    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, related_name="trace_evidence")
    source_text = models.TextField()
    analysis = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]


class DatabaseEvidence(models.Model):
    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, related_name="database_evidence")
    source_text = models.TextField()
    analysis = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
