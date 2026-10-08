"""Upload to TraceAI to compare risky SQL construction with parameter binding.

This file is an analysis fixture, not a script to execute.
Expected: four potential SQL injection findings; safe_lookup has none.
"""


def risky_queries(cursor, user_id):
    cursor.execute(f"""SELECT *
        FROM users
        WHERE id = {user_id}""")
    cursor.execute("SELECT * FROM users WHERE id = " + user_id)
    cursor.execute("SELECT * FROM users WHERE id = %s" % user_id)
    cursor.execute("SELECT * FROM users WHERE id = {}".format(user_id))


def safe_lookup(cursor, user_id):
    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
