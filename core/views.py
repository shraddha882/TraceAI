from django.shortcuts import render, redirect
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from .forms import SignUpForm
from .ownership import owned_by
from code_review.models import CodeReview
from incidents.models import Incident
from django.db.models import Sum

# Create your views here.

def dashboard(request):
    reviews = owned_by(CodeReview.objects.all(), request.user)
    counts = reviews.aggregate(critical=Sum('critical_count'), high=Sum('high_count'),
                               medium=Sum('medium_count'), low=Sum('low_count'))
    return render(request, "core/dashboard.html", {
        'incident_count': owned_by(Incident.objects.all(), request.user).count(),
        'review_count': reviews.count(),
        'risk_count': sum(value or 0 for value in counts.values()),
    })


@require_http_methods(["GET", "POST"])
def signup(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    form = SignUpForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Account created. Sign in with your username and password.')
        return redirect('login')
    return render(request, 'core/signup.html', {'form': form})
