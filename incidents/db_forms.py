from django import forms
from .db_analysis import MAX_BYTES, analyze_db_snapshot


class DatabaseEvidenceForm(forms.Form):
    analyzer = staticmethod(analyze_db_snapshot)
    snapshot = forms.CharField(required=False, strip=False, widget=forms.Textarea(attrs={"rows": 16}))
    snapshot_file = forms.FileField(required=False, widget=forms.FileInput(attrs={"accept": ".json"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "block w-full mt-2 bg-slate-950 border border-slate-700 rounded-lg p-3"

    def clean(self):
        cleaned = super().clean()
        source = cleaned.get("snapshot", "")
        upload = cleaned.get("snapshot_file")
        if upload:
            if not upload.name.lower().endswith(".json") or upload.size > MAX_BYTES:
                raise forms.ValidationError("Upload a .json file up to 1 MB.")
            try:
                source = upload.read(MAX_BYTES + 1).decode("utf-8-sig")
            except UnicodeDecodeError as error:
                raise forms.ValidationError("Upload valid UTF-8 JSON.") from error
        try:
            cleaned["analysis"] = self.analyzer(source)
        except (ValueError, OverflowError) as error:
            raise forms.ValidationError(str(error)) from error
        cleaned["source_text"] = source
        return cleaned
