"""Background RCA from evidence saved when execution begins."""
import logging
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from .models import RCAJob, RCAReport
from .rca import build_rca_report
from .ai import explain_rca

logger = logging.getLogger(__name__)


def run_next_rca_job():
    RCAJob.objects.filter(status='running', started_at__lt=timezone.now() - timedelta(minutes=15)).update(
        status='failed', finished_at=timezone.now(), error='Worker interrupted or time limit exceeded. Generate a new report to retry.')
    with transaction.atomic():
        job = RCAJob.objects.select_for_update(skip_locked=True).filter(status='pending').order_by('created_at', 'pk').first()
        if job is None:
            return False
        job.status = 'running'
        job.started_at = timezone.now()
        job.save(update_fields=['status', 'started_at'])
    try:
        snapshot = build_rca_report(job.incident)
        snapshot['ai_enhancement'] = explain_rca(snapshot, requested=job.use_ai)
        with transaction.atomic():
            current = RCAJob.objects.select_for_update().get(pk=job.pk)
            if current.status == 'running':
                current.report = RCAReport.objects.create(incident_id=current.incident_id, snapshot=snapshot)
                current.status = 'completed'
                current.finished_at = timezone.now()
                current.save(update_fields=['report', 'status', 'finished_at'])
    except Exception as error:
        logger.warning('RCA job %s failed (%s)', job.pk, type(error).__name__)
        RCAJob.objects.filter(pk=job.pk, status='running').update(status='failed', finished_at=timezone.now(),
            error='RCA generation failed. Return to the incident and generate a new report to retry.')
    return True
