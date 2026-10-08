from django.contrib.auth.views import redirect_to_login
from django.http import JsonResponse, HttpResponseForbidden
from django.utils.deprecation import MiddlewareMixin


class WorkspaceAccessMiddleware(MiddlewareMixin):
    """Require an active account for application pages and background status."""
    def process_view(self, request, view_func, view_args, view_kwargs):
        match = request.resolver_match
        if match.url_name in {'login', 'logout', 'signup'} or match.app_name == 'admin':
            return None
        is_status = match.url_name in {'job_status', 'rca_job_status'}
        if not request.user.is_authenticated:
            if is_status:
                return JsonResponse({'error': 'Login required.'}, status=401)
            return redirect_to_login(request.get_full_path())
        if not request.user.is_active:
            if is_status:
                return JsonResponse({'error': 'Workspace access denied.'}, status=403)
            return HttpResponseForbidden('This account is inactive.')
