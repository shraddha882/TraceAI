"""Static-analysis fixture with fake values. Expect five CRITICAL findings."""
import os

DB_PASSWORD = "fake-demo-value"
api_key: str = "fake-demo-value"
config = {"client_secret": "fake-demo-value"}


class Demo:
    def configure(self):
        self.access_token = "fake-demo-value"
        authenticate(password="fake-demo-value")


# These should not trigger the secret rule.
runtime_password = os.getenv("DB_PASSWORD")
password_hint = "Use your password manager"
password = ""
