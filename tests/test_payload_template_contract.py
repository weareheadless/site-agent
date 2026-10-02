import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / 'src' / 'site_agent' / 'templates' / 'next-payload'
BRIDGE = TEMPLATE / 'src' / 'app' / 'api' / 'helloada' / '[...path]' / 'route.ts'


def test_payload_template_fails_closed_on_workspace_query_errors():
    source = BRIDGE.read_text(encoding='utf-8')
    assert 'PayloadWorkspaceQueryError' in source
    assert 'payload_workspace_unavailable' in source
    assert 'routes,' in source
    assert "routes.length ? routes : [{ path: '/', kind: 'page'" not in source
    assert 'catch {\n      return []' not in source
    assert 'const mergeEditableDocuments' in source
    assert 'payload.find({ ...query, draft: false })' in source
    assert 'payload.find({ ...query, draft: true })' in source


def test_payload_template_has_remote_payload_contract_gate():
    package = json.loads((TEMPLATE / 'package.json').read_text(encoding='utf-8'))
    script = package['scripts']['verify:payload']
    assert 'PAYLOAD_CLI=1' in script
    assert 'verify-payload-contract.ts' in script
    verifier = (TEMPLATE / 'scripts' / 'verify-payload-contract.ts').read_text(encoding='utf-8')
    for expected in ['draft: false', 'draft: true', 'findVersions', 'findGlobal', "collection: 'media'"]:
        assert expected in verifier
