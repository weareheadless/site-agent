import pytest

from site_agent.hands.payload_gateway import PayloadGatewayClient, PayloadGatewayError


def client(response):
    gateway = object.__new__(PayloadGatewayClient)
    object.__setattr__(gateway, 'gateway_prefix', '/api/workspace')
    object.__setattr__(gateway, '_request', lambda *args, **kwargs: response)
    return gateway


def test_publication_verifier_requires_exact_destination_and_renderer_proof():
    revision = 'sha256:' + 'a' * 64
    proof = {'status': 'passed', 'checks': [{'status': 200, 'documentId': '4', 'updatedAt': 'revision', 'verifiedAt': '2026-10-21T00:00:00Z'}]}
    response = {'collection': 'posts', 'documentId': '4', 'documentHash': revision, 'liveVerification': proof}
    assert client(response).verify_publication('posts', '4', revision, locale='en') == proof
    for replacement in ({'documentId': '5'}, {'documentHash': 'sha256:' + 'b' * 64}, {'liveVerification': {'status': 'passed', 'checks': []}}):
        with pytest.raises(PayloadGatewayError, match='verification'):
            client({**response, **replacement}).verify_publication('posts', '4', revision, locale='en')


def test_publication_verifier_never_calls_publish_or_accepts_missing_revision():
    gateway = client({})
    object.__setattr__(gateway, '_request', lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('must reject before request')))
    with pytest.raises(PayloadGatewayError, match='exact document'):
        gateway.verify_publication('posts', '4', '', locale='en')
