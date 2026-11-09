import urllib.request
from email.message import Message

from fastapi import FastAPI
from fastapi.testclient import TestClient

from site_agent.application.workspace import ChatService, Tenant, TenantRegistry
from site_agent.core.memory import Memory
from site_agent.web.workspace import register_workspace_routes


def _app(tmp_path):
    tenant = Tenant(
        'alpha',
        {'site': {'payload': {'url': 'https://alpha.example'}}},
        Memory(tmp_path / 'alpha.db'),
        None,
        {},
        'alpha-token',
    )
    app = FastAPI()
    register_workspace_routes(
        app,
        config={},
        env={},
        service=ChatService(registry=TenantRegistry({'alpha': tenant})),
        registry=TenantRegistry({'alpha': tenant}),
        control_prefix='/v1/control-plane/websites',
        control_token='control-secret',
    )
    return app


class _Upstream:
    status = 200

    def __init__(self):
        self.headers = Message()
        self.headers['content-type'] = 'application/pgp-keys'
        self.headers['content-disposition'] = 'attachment; filename="publickey.asc"'
        self.headers['content-length'] = '7'

    def read(self):
        return b'pgp-key'


def test_worker_gateway_keeps_attachment_headers(tmp_path, monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=0):
        captured['url'] = request.full_url
        captured['authorization'] = request.get_header('Authorization')
        captured['subject'] = request.get_header('X-helloada-owner-subject')
        return _Upstream()

    monkeypatch.setattr(urllib.request, 'urlopen', fake_urlopen)
    app = _app(tmp_path)
    with TestClient(app) as client:
        response = client.get(
            '/v1/control-plane/websites/alpha/worker/mail/messages/msg_1/attachments/att_1',
            headers={
                'Authorization': 'Bearer control-secret',
                'x-helloada-owner-subject': '8',
            },
        )
    assert response.status_code == 200
    assert response.content == b'pgp-key'
    assert response.headers['content-type'] == 'application/pgp-keys'
    assert response.headers['content-disposition'] == 'attachment; filename="publickey.asc"'
    assert response.headers['cache-control'] == 'no-store'
    assert captured['url'] == 'https://alpha.example/api/helloada/mail/messages/msg_1/attachments/att_1'
    assert captured['authorization'] == 'Bearer alpha-token'
    assert captured['subject'] == '8'


def test_worker_gateway_requires_the_control_plane_identity(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        assert client.get('/v1/control-plane/websites/alpha/worker/mail/mailboxes').status_code == 401
        assert client.get(
            '/v1/control-plane/websites/alpha/worker/mail/mailboxes',
            headers={'Authorization': 'Bearer control-secret'},
        ).status_code == 400
