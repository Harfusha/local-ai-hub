"""Legacy SDK: sends flat fields."""
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

def checkpoint(base_url, **fields):
    request = Request(base_url + '/checkpoint', data=json.dumps(fields).encode(), headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urlopen(request, timeout=3) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        return exc.code, json.load(exc)
