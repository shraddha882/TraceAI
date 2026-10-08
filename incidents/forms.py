from django import forms
from django.utils import timezone

from .models import Incident
from .log_analysis import MAX_LOG_BYTES, MAX_LOG_LINES


class UTCDateTimeField(forms.DateTimeField):
    def to_python(self, value):
        # The form explicitly accepts UTC, independent of active user timezone.
        with timezone.override("UTC"):
            return super().to_python(value)


class IncidentForm(forms.ModelForm):
    occurred_at = UTCDateTimeField(
        label="Occurrence time (UTC)",
        help_text="Enter when the incident occurred in UTC. IST is UTC +05:30.",
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"],
    )

    class Meta:
        model = Incident
        fields = ["title", "affected_service", "description", "occurred_at"]
        widgets = {"description": forms.Textarea(attrs={"rows": 6})}
        help_texts = {
            "title": "A short summary, for example: Checkout returning HTTP 500.",
            "affected_service": "For example: checkout-api or payments-worker.",
            "description": "Describe observed symptoms and impact. Evidence collection comes next.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "w-full mt-2 rounded-lg bg-slate-950 border border-slate-700 p-3 text-white"

    def clean_occurred_at(self):
        value = self.cleaned_data["occurred_at"]
        if value > timezone.now():
            raise forms.ValidationError("Occurrence time cannot be in the future. Check the UTC time.")
        return value


class LogEvidenceForm(forms.Form):
    logs = forms.CharField(required=False, strip=False, widget=forms.Textarea(attrs={"rows": 10}), label="Paste logs")
    log_file = forms.FileField(required=False, label="Or upload a log file", widget=forms.FileInput(attrs={"accept": ".log,.txt,.jsonl,.ndjson"}))

    def clean(self):
        cleaned = super().clean()
        upload = cleaned.get("log_file")
        source = cleaned.get("logs", "")
        name = "Pasted logs"
        if upload:
            if not upload.name.lower().endswith((".log", ".txt", ".jsonl", ".ndjson")):
                raise forms.ValidationError("Upload a .log, .txt, .jsonl or .ndjson file.")
            if upload.size > MAX_LOG_BYTES:
                raise forms.ValidationError("Maximum log size is 1 MB.")
            try:
                source = upload.read(MAX_LOG_BYTES + 1).decode("utf-8-sig")
            except UnicodeDecodeError as error:
                raise forms.ValidationError("Upload a valid UTF-8 log file.") from error
            name = upload.name
        if not source.strip():
            raise forms.ValidationError("Paste logs or upload a nonempty log file.")
        if len(source.encode("utf-8")) > MAX_LOG_BYTES:
            raise forms.ValidationError("Maximum log size is 1 MB.")
        if len(source.splitlines()) > MAX_LOG_LINES:
            raise forms.ValidationError("Maximum log length is 10,000 lines.")
        cleaned["source_text"] = source
        cleaned["source_name"] = name
        return cleaned

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "block w-full mt-2 bg-slate-950 border border-slate-700 rounded-lg p-3"
