from django import forms

from .github import GitHubError, parse_pr_url


class GitHubPRForm(forms.Form):
    pr_url = forms.CharField(
        label="Public GitHub PR URL", max_length=500,
        widget=forms.URLInput(attrs={
            "placeholder": "https://github.com/owner/repo/pull/123",
            "class": "w-full rounded-lg bg-slate-950 border border-slate-700 p-3 mt-2",
        }),
    )

    def clean_pr_url(self):
        value = self.cleaned_data["pr_url"]
        try:
            owner, repo, number = parse_pr_url(value)
        except GitHubError as error:
            raise forms.ValidationError(str(error)) from error
        return f"https://github.com/{owner}/{repo}/pull/{number}"
