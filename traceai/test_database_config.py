from pathlib import Path
from django.test import SimpleTestCase
from django.core.exceptions import ImproperlyConfigured
from .database_config import database_config


class DatabaseConfigTests(SimpleTestCase):
    def env(self):
        return dict(TRACEAI_DB_BACKEND="postgresql", POSTGRES_DB="traceai", POSTGRES_USER="traceai", POSTGRES_PASSWORD="test-only", POSTGRES_HOST="localhost")

    def test_default_preserves_sqlite(self):
        self.assertEqual(database_config({}, Path("."))["NAME"], Path("db.sqlite3"))

    def test_postgres_settings(self):
        result = database_config(self.env(), Path("."))
        self.assertEqual(result["ENGINE"], "django.db.backends.postgresql")
        self.assertEqual(result["PORT"], 5432)
        self.assertEqual(result["OPTIONS"]["connect_timeout"], 5)

    def test_invalid_configuration_never_silently_falls_back(self):
        for changes in ({"POSTGRES_PASSWORD": ""}, {"POSTGRES_PORT": "bad"}, {"POSTGRES_PORT": "70000"}, {"POSTGRES_SSLMODE": "bad"}, {"TRACEAI_DB_BACKEND": "unknown"}):
            with self.subTest(changes=changes), self.assertRaises(ImproperlyConfigured):
                database_config({**self.env(), **changes}, Path("."))
