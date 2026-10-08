from django.urls import path
from . import views

app_name = "incidents"
urlpatterns = [
    path('<int:incident_id>/rca/jobs/<uuid:job_id>/', views.rca_job, name='rca_job'),
    path('<int:incident_id>/rca/jobs/<uuid:job_id>/status/', views.rca_job_status, name='rca_job_status'),
    path("<int:incident_id>/rca/new/", views.rca_create, name="rca_create"),
    path("<int:incident_id>/rca/<int:report_id>/", views.rca_detail, name="rca_detail"),
    path("<int:incident_id>/correlation/", views.incident_correlation, name="correlation"),
    path("<int:incident_id>/deployments/<int:deployment_id>/review/", views.deployment_review, name="deployment_review"),
    path("<int:incident_id>/deployments/<int:deployment_id>/diff/", views.deployment_fetch_diff, name="deployment_fetch_diff"),
    path("<int:incident_id>/deployments/new/", views.deployment_create, name="deployment_create"),
    path("<int:incident_id>/deployments/<int:deployment_id>/", views.deployment_detail, name="deployment_detail"),
    path("<int:incident_id>/traces/new/", views.trace_create, name="trace_create"),
    path("<int:incident_id>/traces/<int:evidence_id>/", views.trace_detail, name="trace_detail"),
    path("<int:incident_id>/database/new/", views.database_create, name="database_create"),
    path("<int:incident_id>/database/<int:evidence_id>/", views.database_detail, name="database_detail"),
    path("<int:incident_id>/logs/new/", views.logs_create, name="logs_create"),
    path("<int:incident_id>/logs/<int:evidence_id>/", views.log_detail, name="log_detail"),
    path("", views.incident_list, name="list"),
    path("new/", views.incident_create, name="create"),
    path("<int:incident_id>/", views.incident_detail, name="detail"),
]
