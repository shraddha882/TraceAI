"""Upload this fixture to TraceAI; expect two HIGH possible connection leaks.

For static analysis only. No database or API key is needed to review it.
"""
import psycopg2


def leaking_connection():
    conn = psycopg2.connect("dbname=example")
    return conn.cursor()


def cleaned_connection():
    conn = psycopg2.connect("dbname=example")
    try:
        return conn.cursor().execute("SELECT 1")
    finally:
        conn.close()


def overwritten_connection():
    conn = psycopg2.connect("dbname=example")
    conn = psycopg2.connect("dbname=example")
    conn.close()
