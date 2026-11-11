from fastapi.testclient import TestClient
from backend.app import create_app


def test_delivery_readiness_is_read_only_scoped_and_validates_ranges(tmp_path,monkeypatch):
    with TestClient(create_app(tmp_path)) as client:
        pid=client.post('/api/projects',json={'name':'synthetic delivery'}).json()['id']
        async def forbidden(*args,**kwargs):raise AssertionError('readiness must not call runtime')
        monkeypatch.setattr(client.app.state.pi_runtime,'request',forbidden)
        base=f'/api/projects/{pid}/delivery-readiness'
        response=client.get(base)
        assert response.status_code==200,response.text
        assert response.json()['status']=='empty_scope'
        assert response.json()['summary']['source_panels']==0
        assert response.json()['pixel_bytes_reverified'] is False
        assert client.get(base+'?episode=0').status_code==422
        assert client.get(base+'?batch=-1').status_code==422
        assert client.get('/api/projects/other/delivery-readiness').status_code==404
        assert client.get(f'/api/projects/{pid}/tasks').json()==[]
        assert client.get(f'/api/projects/{pid}/records').json()==[]
