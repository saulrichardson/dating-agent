"""Tests for persona service API endpoints."""
import json
import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from server import app


@pytest.fixture
def client():
    """Create a test client."""
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


def test_health_endpoint(client):
    """Test health check endpoint."""
    response = client.get('/health')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['status'] == 'ok'


def test_extract_missing_data(client):
    """Test extract endpoint with missing data."""
    response = client.post(
        '/extract',
        json={},
        content_type='application/json'
    )
    assert response.status_code == 400
    data = json.loads(response.data)
    assert 'error' in data


def test_generate_missing_persona(client):
    """Test generate endpoint with missing persona."""
    response = client.post(
        '/generate',
        json={'recent_messages': []},
        content_type='application/json'
    )
    assert response.status_code == 400
    data = json.loads(response.data)
    assert 'error' in data


def test_generate_missing_messages(client):
    """Test generate endpoint with missing messages."""
    response = client.post(
        '/generate',
        json={'persona': {}},
        content_type='application/json'
    )
    assert response.status_code == 400
    data = json.loads(response.data)
    assert 'error' in data

