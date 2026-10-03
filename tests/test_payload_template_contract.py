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


def test_payload_template_has_one_managed_growth_write_and_renderer_boundary():
    source = BRIDGE.read_text(encoding='utf-8')
    contract = (TEMPLATE / 'src' / 'lib' / 'growth-contract.ts').read_text(encoding='utf-8')
    renderer = (TEMPLATE / 'src' / 'components' / 'PublicDocument.tsx').read_text(encoding='utf-8')
    config = (TEMPLATE / 'payload.config.ts').read_text(encoding='utf-8')
    shared_schema = (ROOT / 'packages' / 'helloada-payload-core' / 'src' / 'schema' / 'index.ts').read_text(encoding='utf-8')
    assert "path === '/growth/apply'" in source
    assert "path === '/growth/publish'" in source
    assert "claimOperation(operationKey, documentKey, packageHash)" in source
    assert 'renderToStaticMarkup' in source
    assert 'helloada_growth_candidates' in contract
    assert 'helloada_growth_operations' in contract
    assert "state = 'writing'" in contract
    assert 'assertNativeWriteAllowed' in contract
    assert 'function PublicDocument' in renderer
    assert "from '@weareheadless/helloada-payload-core/schema'" in config
    assert 'createHelloAdaSchema(assertNativeWriteAllowed)' in config
    for slug in ('pages', 'posts', 'products'):
        assert f"protectCollection('{slug}', guard)" in shared_schema
        assert not (TEMPLATE / 'src' / 'collections' / f'{slug.title()}.ts').exists()


def test_owner_edits_are_stable_draft_only_and_publish_the_exact_reviewed_revision():
    source = BRIDGE.read_text(encoding='utf-8')
    assert "from '@weareheadless/helloada-payload-core/bindings'" in source
    assert 'applyHelloAdaBindingEdits(currentDocument, checkedEdits)' in source
    assert 'expectedDraftHash' in source
    assert "claimOperation(operationKey, documentKey, packageHash)" in source
    assert 'prepareOperation(operationKey, intent)' in source
    assert 'reconcileOperation(operationKey, result)' in source
    assert "path === '/page-fields'" in source
    assert "path === '/page-images'" not in source
    assert "if (documents.length !== 1)" in source
    assert 'Payload saved a different draft than the exact content edit' in source
    assert 'The published document does not match the exact reviewed draft' in source
    assert 'helloAdaPlainText' not in source
