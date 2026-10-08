from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from core.forms import WorkspaceAuthenticationForm
from core.views import signup


urlpatterns = [
    path('accounts/signup/', signup, name='signup'),
    path('accounts/login/', auth_views.LoginView.as_view(template_name='core/login.html', authentication_form=WorkspaceAuthenticationForm), name='login'),
    path('accounts/logout/', auth_views.LogoutView.as_view(), name='logout'),
    path("incidents/", include("incidents.urls")),
    path("admin/", admin.site.urls),

    path("", include("core.urls")),

    path(
        "code-review/",
        include("code_review.urls")
    ),
]
