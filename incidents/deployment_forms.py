import re
from django import forms
from django.utils import timezone
from .forms import UTCDateTimeField
from .models import Deployment


class DeploymentForm(forms.ModelForm):
    deployed_at = UTCDateTimeField(label="Deployment time (UTC)",
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"])

    class Meta:
        model = Deployment
        fields = ["service", "environment", "deployed_at", "repository", "commit_sha", "previous_commit_sha", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 4})}
        help_texts = {
            "environment": "For example: production or staging.",
            "repository": "GitHub owner/repository, e.g. django/django. No URL required.",
            "commit_sha": "Full 40-character deployed commit SHA. Stored as supplied; not verified against GitHub yet.",
            "previous_commit_sha": "Optional full SHA of the previously deployed commit, for future diff comparison.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "block w-full mt-2 bg-slate-950 border border-slate-700 rounded-lg p-3"

    def clean_repository(self):
        value = self.cleaned_data["repository"]
        if not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+", value) or value.split("/")[1] in {".", ".."}:
            raise forms.ValidationError("Use GitHub owner/repository format.")
        return value

    def clean_deployed_at(self):
        value = self.cleaned_data["deployed_at"]
        if value > timezone.now():
            raise forms.ValidationError("Deployment time cannot be in the future. Check UTC time.")
        return value

    def clean_commit_sha(self):
        return self.cleaned_data["commit_sha"].lower()

    def clean_previous_commit_sha(self):
        return self.cleaned_data["previous_commit_sha"].lower()
