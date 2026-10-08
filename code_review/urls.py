from django.urls import path
from . import views

app_name = "code_review"

urlpatterns = [
    path('jobs/<uuid:job_id>/', views.job_detail, name='job_detail'),
    path('jobs/<uuid:job_id>/status/', views.job_status, name='job_status'),
    path("history/pr/<int:review_id>/", views.pr_review_detail, name="pr_detail"),
    path("github/", views.github_pr, name="github"),
    path("", views.review_code, name="review"),

    path(
        "history/",
        views.review_history,
        name="history"
    ),

    path(
        "history/<int:review_id>/",
        views.review_detail,
        name="detail"
    ),
]
