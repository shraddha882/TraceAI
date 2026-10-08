import requests
import subprocess

api_key = "secret-api-key"


def fetch_data(url, command):

    response = requests.get(url)

    subprocess.run(
        command,
        shell=True
    )

    try:
        return eval(command)

    except:
        pass