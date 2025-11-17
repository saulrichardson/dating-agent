"""Tests for server API endpoints."""
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


def test_set_context(client):
    """Test setting context via POST."""
    response = client.post(
        '/context/user1/match1',
        json={'context': {'message': 'test'}},
        content_type='application/json'
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['status'] == 'saved'
    assert data['user_id'] == 'user1'
    assert data['match_id'] == 'match1'


def test_get_context(client):
    """Test getting context."""
    client.post(
        '/context/user1/match1',
        json={'context': {'message': 'test'}},
        content_type='application/json'
    )
    
    response = client.get('/context/user1/match1')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['user_id'] == 'user1'
    assert data['match_id'] == 'match1'
    assert data['context'] == {'message': 'test'}


def test_get_nonexistent_context(client):
    """Test getting context that doesn't exist."""
    response = client.get('/context/user1/match999')
    assert response.status_code == 404
    data = json.loads(response.data)
    assert 'error' in data


def test_set_context_missing_data(client):
    """Test setting context with missing data."""
    response = client.post(
        '/context/user1/match1',
        json={},
        content_type='application/json'
    )
    assert response.status_code == 400
    data = json.loads(response.data)
    assert 'error' in data


def test_delete_context(client):
    """Test deleting context."""
    client.post(
        '/context/user1/match1',
        json={'context': {'message': 'test'}},
        content_type='application/json'
    )
    
    response = client.delete('/context/user1/match1')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['status'] == 'deleted'
    
    get_response = client.get('/context/user1/match1')
    assert get_response.status_code == 404


def test_get_all_user_contexts(client):
    """Test getting all contexts for a user."""
    client.post(
        '/context/user1/match1',
        json={'context': {'message': 'test1'}},
        content_type='application/json'
    )
    client.post(
        '/context/user1/match2',
        json={'context': {'message': 'test2'}},
        content_type='application/json'
    )
    
    response = client.get('/context/user1')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['user_id'] == 'user1'
    assert len(data['contexts']) == 2

