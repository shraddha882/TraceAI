"""Shared code-review entry points for web, future GitHub and incident callers.

Call analyze_code for a static result without database writes. Call
create_code_review to analyze and persist a successful report. Neither function
needs an HTTP request, an uploaded file object, or an LLM API key.
"""
from dataclasses import dataclass

from .analyzers.python_analyzer import analyze_python_code
from .models import CodeReview


@dataclass(frozen=True)
class ReviewOutcome:
    result: dict
    review: CodeReview | None


def analyze_code(source_code: str, language: str = "Python") -> dict:
    """Analyze decoded source text without executing it or saving a report.

    Successful results contain summary, findings and severity counts. Invalid
    input returns success=False; syntax failures also include syntax_error.
    Unexpected analyzer errors propagate so callers cannot mistake them for a
    clean report. File decoding and upload validation belong to input adapters.
    """
    if language != "Python":
        return {
            "success": False,
            "summary": f"{language} analysis is not available yet.",
            "findings": [],
        }
    if not source_code.strip():
        return {
            "success": False,
            "summary": "Please provide Python code to analyze.",
            "findings": [],
        }
    return analyze_python_code(source_code)


def create_code_review(source_code: str, language: str = "Python", *, owner=None) -> ReviewOutcome:
    """Analyze once and create one report on success, including clean reports.

    Failed validation or syntax analysis creates no record. Database failures
    propagate to the caller; a report is never claimed saved when writing fails.
    """
    result = analyze_code(source_code, language)
    if not result["success"]:
        return ReviewOutcome(result=result, review=None)
    counts = result["counts"]
    review = CodeReview.objects.create(
        owner=owner,
        language=language,
        source_code=source_code,
        summary=result["summary"],
        findings=result["findings"],
        critical_count=counts["CRITICAL"],
        high_count=counts["HIGH"],
        medium_count=counts["MEDIUM"],
        low_count=counts["LOW"],
    )
    return ReviewOutcome(result=result, review=review)
