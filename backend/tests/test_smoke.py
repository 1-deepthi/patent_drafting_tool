from fastapi.testclient import TestClient
from app.main import app

def test_root():
    response = TestClient(app).get('/')
    assert response.status_code == 200
    assert response.json()['docs'] == '/docs'

def test_health_shape_without_requiring_live_firebase():
    response = TestClient(app).get('/health')
    assert response.status_code in (200, 503)
    assert 'firebase' in response.json()
