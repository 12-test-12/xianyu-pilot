"""Desktop-only route that asks the Qt host to open the embedded QR login."""
from pathlib import Path
import re

from fastapi.testclient import TestClient
import pytest

from app.core.config import Settings
from app.desktop_app import create_desktop_app


@pytest.fixture
def console(tmp_path,monkeypatch):
    from app.core import paths
    monkeypatch.setattr(paths,'SOURCE_ROOT',tmp_path)
    web=tmp_path/'web'
    (web/'assets').mkdir(parents=True)
    original=Path(__file__).resolve().parents[2]/'web/index.html'
    (web/'index.html').write_bytes(original.read_bytes())
    (web/'assets/module.js').write_text('export {}',encoding='utf-8')
    (web/'xya/brand').mkdir(parents=True)
    (web/'xya/brand/icon.png').write_bytes(b'fixture image')
    config=Settings(runtime_mode='desktop')
    app=create_desktop_app(config,web_dir=web)
    with TestClient(app,base_url='http://127.0.0.1:15177') as client:
        html=client.get('/')
        marker=re.search(r'name="xianyu-desktop-bootstrap" content="([^"]+)"',html.text)[1]
        session=client.post('/api/desktop/session',json={},headers={'X-Desktop-Bootstrap':marker})
        client.headers['Authorization']='Bearer '+session.json()['data']['token']
        yield client,app


def test_login_window_requires_a_live_qt_host(console):
    client,app=console
    response=client.post('/api/desktop/login-window',json={})
    assert response.status_code==409
    assert '桌面登录窗口不可用' in response.json()['detail']


def test_login_window_forwards_normalized_account_id(console):
    client,app=console
    opened=[]
    app.state.desktop_login_opener=lambda account_id: opened.append(account_id)

    assert client.post('/api/desktop/login-window',json={}).json()=={'ok':True}
    assert client.post('/api/desktop/login-window',json={'accountId':7}).status_code==200
    assert client.post('/api/desktop/login-window',json={'account_id':5}).status_code==200
    # Invalid, non-positive and blank identifiers mean "add a new account".
    client.post('/api/desktop/login-window',json={'accountId':'abc'})
    client.post('/api/desktop/login-window',json={'accountId':0})
    client.post('/api/desktop/login-window',json={'accountId':''})
    # A malformed body must not spill an exception into the API.
    client.post('/api/desktop/login-window',content=b'not-json',headers={'Content-Type':'application/json'})

    assert opened==[None,7,5,None,None,None,None]


def test_login_window_opener_failure_is_reported(console):
    client,app=console
    def broken(_account_id):
        raise RuntimeError('profile locked')
    app.state.desktop_login_opener=broken
    with pytest.raises(RuntimeError):
        client.post('/api/desktop/login-window',json={'accountId':1})
