from core.ownership import owned_by
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from .forms import IncidentForm, LogEvidenceForm
from .models import Incident, LogEvidence
from .log_analysis import analyze_logs
from .db_forms import DatabaseEvidenceForm
from .models import DatabaseEvidence
from .models import TraceEvidence
from .trace_analysis import TraceEvidenceForm
from .deployment_forms import DeploymentForm
from .models import Deployment
from .deployment_diff import save_deployment_diff, review_deployment_diff
from code_review.github import GitHubError
from .correlation import correlate_incident
from .models import RCAReport, RCAJob
from django.db import transaction
from django.http import JsonResponse
from django.urls import reverse


@require_http_methods(["POST"])
def rca_create(request, incident_id):
    with transaction.atomic():
        incident = get_object_or_404(owned_by(Incident.objects.select_for_update(), request.user), pk=incident_id)
        job = incident.rca_jobs.filter(status__in=['pending', 'running']).first()
        if job is None:
            job = RCAJob.objects.create(incident=incident, use_ai=request.POST.get('use_ai') == 'on')
    return redirect('incidents:rca_job', incident_id=incident.pk, job_id=job.pk)


@require_http_methods(['GET'])
def rca_job(request, incident_id, job_id):
    job = get_object_or_404(owned_by(RCAJob.objects.select_related('incident'), request.user, 'incident__owner'), pk=job_id, incident_id=incident_id)
    return render(request, 'incidents/rca_job.html', {'job': job, 'incident': job.incident})


@require_http_methods(['GET'])
def rca_job_status(request, incident_id, job_id):
    job = get_object_or_404(owned_by(RCAJob.objects.all(), request.user, 'incident__owner'), pk=job_id, incident_id=incident_id)
    response = JsonResponse({'status': job.status, 'error': job.error,
        'report_url': reverse('incidents:rca_detail', args=[incident_id, job.report_id]) if job.report_id else None})
    response['Cache-Control'] = 'no-store'
    return response


@require_http_methods(["GET"])
def rca_detail(request, incident_id, report_id):
    report = get_object_or_404(owned_by(RCAReport.objects.select_related("incident"), request.user, 'incident__owner'), incident_id=incident_id, pk=report_id)
    return render(request, "incidents/rca.html", {"report": report, "incident": report.incident})


@require_http_methods(["GET"])
def incident_correlation(request, incident_id):
    incident = get_object_or_404(owned_by(Incident.objects.all(), request.user), pk=incident_id)
    return render(request, "incidents/correlation.html", {"incident": incident, "correlation": correlate_incident(incident)})


@require_http_methods(["POST"])
def deployment_review(request, incident_id, deployment_id):
    deployment = get_object_or_404(owned_by(Deployment.objects.select_related("incident"), request.user, 'incident__owner'), pk=deployment_id, incident_id=incident_id)
    try:
        review_deployment_diff(deployment)
    except GitHubError as error:
        return render(request, "incidents/deployment_detail.html", {
            "deployment": deployment, "incident": deployment.incident, "diff_error": str(error),
        })
    return redirect("incidents:deployment_detail", incident_id=incident_id, deployment_id=deployment_id)


@require_http_methods(["POST"])
def deployment_fetch_diff(request, incident_id, deployment_id):
    deployment = get_object_or_404(owned_by(Deployment.objects.select_related("incident"), request.user, 'incident__owner'), pk=deployment_id, incident_id=incident_id)
    try:
        save_deployment_diff(deployment)
    except GitHubError as error:
        return render(request, "incidents/deployment_detail.html", {
            "deployment": deployment, "incident": deployment.incident,
            "diff_error": f"Unable to load commit comparison: {error}",
        })
    return redirect("incidents:deployment_detail", incident_id=incident_id, deployment_id=deployment_id)


@require_http_methods(["GET", "POST"])
def deployment_create(request, incident_id):
    incident = get_object_or_404(owned_by(Incident.objects.all(), request.user), pk=incident_id)
    form = DeploymentForm(request.POST if request.method == "POST" else None, initial={"service": incident.affected_service})
    if request.method == "POST" and form.is_valid():
        deployment = form.save(commit=False)
        deployment.incident = incident
        deployment.save()
        return redirect("incidents:deployment_detail", incident_id=incident.pk, deployment_id=deployment.pk)
    return render(request, "incidents/deployment_form.html", {"form": form, "incident": incident})


@require_http_methods(["GET"])
def deployment_detail(request, incident_id, deployment_id):
    deployment = get_object_or_404(owned_by(Deployment.objects.select_related("incident"), request.user, 'incident__owner'), pk=deployment_id, incident_id=incident_id)
    return render(request, "incidents/deployment_detail.html", {"deployment": deployment, "incident": deployment.incident})


@require_http_methods(["GET", "POST"])
def trace_create(request, incident_id):
    incident = get_object_or_404(owned_by(Incident.objects.all(), request.user), pk=incident_id)
    form = TraceEvidenceForm(request.POST if request.method == "POST" else None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        evidence = TraceEvidence.objects.create(incident=incident,
            source_text=form.cleaned_data["source_text"], analysis=form.cleaned_data["analysis"])
        return redirect("incidents:trace_detail", incident_id=incident.pk, evidence_id=evidence.pk)
    return render(request, "incidents/trace_form.html", {"incident": incident, "form": form})


@require_http_methods(["GET"])
def trace_detail(request, incident_id, evidence_id):
    evidence = get_object_or_404(owned_by(TraceEvidence.objects.select_related("incident"), request.user, 'incident__owner'), pk=evidence_id, incident_id=incident_id)
    return render(request, "incidents/trace_detail.html", {"evidence": evidence, "incident": evidence.incident})


@require_http_methods(["GET", "POST"])
def database_create(request, incident_id):
    incident = get_object_or_404(owned_by(Incident.objects.all(), request.user), pk=incident_id)
    form = DatabaseEvidenceForm(request.POST if request.method == "POST" else None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        evidence = DatabaseEvidence.objects.create(incident=incident,
            source_text=form.cleaned_data["source_text"], analysis=form.cleaned_data["analysis"])
        return redirect("incidents:database_detail", incident_id=incident.pk, evidence_id=evidence.pk)
    return render(request, "incidents/database_form.html", {"incident": incident, "form": form})


@require_http_methods(["GET"])
def database_detail(request, incident_id, evidence_id):
    evidence = get_object_or_404(owned_by(DatabaseEvidence.objects.select_related("incident"), request.user, 'incident__owner'), pk=evidence_id, incident_id=incident_id)
    return render(request, "incidents/database_detail.html", {"evidence": evidence, "incident": evidence.incident})


@require_http_methods(["GET"])
def incident_list(request):
    page = Paginator(owned_by(Incident.objects.all(), request.user), 20).get_page(request.GET.get("page"))
    return render(request, "incidents/list.html", {"page": page})


@require_http_methods(["GET", "POST"])
def incident_create(request):
    form = IncidentForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        incident = form.save(commit=False)
        incident.owner = request.user
        incident.save()
        return redirect("incidents:detail", incident_id=incident.pk)
    return render(request, "incidents/form.html", {"form": form})


@require_http_methods(["GET"])
def incident_detail(request, incident_id):
    incident = get_object_or_404(owned_by(Incident.objects.all(), request.user), pk=incident_id)
    return render(request, "incidents/detail.html", {"incident": incident})


@require_http_methods(["GET", "POST"])
def logs_create(request, incident_id):
    incident = get_object_or_404(owned_by(Incident.objects.all(), request.user), pk=incident_id)
    form = LogEvidenceForm(request.POST if request.method == "POST" else None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        source = form.cleaned_data["source_text"]
        evidence = LogEvidence.objects.create(
            incident=incident, source_name=form.cleaned_data["source_name"],
            source_text=source, analysis=analyze_logs(source),
        )
        return redirect("incidents:log_detail", incident_id=incident.pk, evidence_id=evidence.pk)
    return render(request, "incidents/log_form.html", {"incident": incident, "form": form})


@require_http_methods(["GET"])
def log_detail(request, incident_id, evidence_id):
    evidence = get_object_or_404(owned_by(LogEvidence.objects.select_related("incident"), request.user, 'incident__owner'), pk=evidence_id, incident_id=incident_id)
    return render(request, "incidents/log_detail.html", {"evidence": evidence, "incident": evidence.incident})
