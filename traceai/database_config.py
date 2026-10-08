from django.core.exceptions import ImproperlyConfigured


def database_config(env, base_dir):
    backend = env.get("TRACEAI_DB_BACKEND", "sqlite").lower()
    if backend == "sqlite":
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": base_dir / "db.sqlite3"}
    if backend != "postgresql":
        raise ImproperlyConfigured("TRACEAI_DB_BACKEND must be sqlite or postgresql.")
    required = ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_HOST")
    missing = [name for name in required if not env.get(name)]
    if missing:
        raise ImproperlyConfigured("Missing PostgreSQL settings: " + ", ".join(missing))
    try:
        port = int(env.get("POSTGRES_PORT", "5432"))
        if not 1 <= port <= 65535:
            raise ValueError()
    except ValueError as error:
        raise ImproperlyConfigured("POSTGRES_PORT must be a valid port number.") from error
    sslmode = env.get("POSTGRES_SSLMODE", "prefer")
    if sslmode not in {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}:
        raise ImproperlyConfigured("Invalid POSTGRES_SSLMODE.")
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env["POSTGRES_DB"], "USER": env["POSTGRES_USER"],
        "PASSWORD": env["POSTGRES_PASSWORD"], "HOST": env["POSTGRES_HOST"], "PORT": port,
        "CONN_MAX_AGE": 0,
        "OPTIONS": {"connect_timeout": 5, "sslmode": sslmode},
    }
