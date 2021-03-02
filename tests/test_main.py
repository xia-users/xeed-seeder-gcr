import json
import base64
import gzip
import pytest
from main import app

@pytest.fixture(scope="module")
def client():
    client = app.test_client()
    ctx = app.app_context()
    ctx.push()
    yield client
    ctx.pop()

def test_homepage(client):
    response = client.get('/')
    assert response.status_code == 200
    assert b'XEED' in response.data

def test_push(client):
    credentials = base64.b64encode(b"user:La_vie_est_belle").decode()
    headers = {"Authorization": "Basic {}".format(credentials)}
    response = client.get('/push', headers=headers)
    assert response.status_code == 200
    assert b'XEED' in response.data