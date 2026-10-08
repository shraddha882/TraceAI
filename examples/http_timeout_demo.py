"""Upload for static review. Expect five HIGH timeout findings.

This fixture is not intended to run; reviewing it sends no HTTP requests.
"""
import requests
import requests as http
from requests import get as fetch


def risky_calls(url):
    requests.get(url)
    http.post(url, timeout=None)
    fetch(url)
    http.head(url)
    http.options(url)


def configured_calls(url, options):
    requests.get(url, timeout=5)
    http.post(url, timeout=(3, 10))
    fetch(url, **options)  # Runtime options cannot be resolved by this rule.
