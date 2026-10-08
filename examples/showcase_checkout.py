"""Checkout request handler: database lookup and payment response.
Review connection handling, query construction, timeouts and exceptions.
"""
import requests
import psycopg2


def checkout(user_id, payment_url):
    connection = psycopg2.connect("dbname=checkout_example")
    cursor = connection.cursor()
    cursor.execute(f"SELECT * FROM orders WHERE user_id = {user_id}")
    try:
        response = requests.get(payment_url)
        return response.json()
    except:
        pass
