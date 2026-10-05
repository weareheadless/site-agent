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
    assert "const collections = ['pages', 'posts', 'postCategories', 'products', 'productCategories', 'contactForms', 'contacts', 'conversations', 'messages', 'messageOperations'] as const" in verifier
    assert "const versionedCollections = ['pages', 'posts', 'postCategories', 'products', 'contactForms'] as const" in verifier
    assert 'for (const collection of versionedCollections)' in verifier


def test_all_server_side_payload_gateway_resources_have_exact_route_handlers():
    content = (TEMPLATE / 'src/app/api/workspace/content/route.ts').read_text(encoding='utf-8')
    global_route = (TEMPLATE / 'src/app/api/workspace/global/route.ts').read_text(encoding='utf-8')
    media = (TEMPLATE / 'src/app/api/workspace/media/route.ts').read_text(encoding='utf-8')
    for source in (content, global_route, media):
        assert "serviceAuthorized(request)" in source
        assert "Cache-Control" in source
        assert "hashJson" in source
    assert 'expectedHash is required for a draft update' in content
    assert 'expectedHash is required for a draft update' in global_route
    assert 'exact expectedHash are required' in media
    assert "operation === 'publish'" in content
    assert "operation || '').trim().toLowerCase() !== 'update'" in global_route
    assert "operation || '').trim().toLowerCase() !== 'update'" in media


def test_production_payload_cli_has_no_local_migration_escape_hatch():
    config = (TEMPLATE / 'payload.config.ts').read_text(encoding='utf-8')
    package = json.loads((TEMPLATE / 'package.json').read_text(encoding='utf-8'))
    assert 'ALLOW_LOCAL_PAYLOAD_MIGRATION' not in config
    assert 'payloadCliEntrypoint && !isCLI' in config
    assert 'isCLI && isProduction && isDatabaseMigrationCommand && !hasCloudflareToken' in config
    assert "['migrate', 'migrate:status', 'migrate:create', 'migrate:down']" in config
    assert 'PAYLOAD_CLI=1' in package['scripts']['prebuild']
    assert 'PAYLOAD_CLI=1' in package['scripts']['payload']


def test_preview_inventory_cannot_execute_a_customer_repository_script():
    source = (ROOT / 'src' / 'site_agent' / 'application' / 'source_deployment.py').read_text(encoding='utf-8')
    method = source.split('def _inventory_command(', 1)[1].split('\n    def ', 1)[0]
    assert 'with_name("source_inventory.py")' in method
    assert 'inventory_script' not in method
    assert 'npx' not in method
    assert 'fallback' not in method.lower()


def test_payload_template_has_one_managed_growth_write_and_renderer_boundary():
    source = BRIDGE.read_text(encoding='utf-8')
    contract = (TEMPLATE / 'src' / 'lib' / 'growth-contract.ts').read_text(encoding='utf-8')
    renderer = (TEMPLATE / 'src' / 'components' / 'PublicDocument.tsx').read_text(encoding='utf-8')
    config = (TEMPLATE / 'payload.config.ts').read_text(encoding='utf-8')
    shared_schema = (ROOT / 'packages' / 'helloada-payload-core' / 'src' / 'schema' / 'index.ts').read_text(encoding='utf-8')
    assert "path === '/growth/apply'" in source
    assert "path === '/growth/publish'" in source
    assert "claimOperation(operationKey, documentKey, packageHash)" in source
    assert 'verifyExactPreview(request' in source
    assert 'renderToStaticMarkup' not in source
    assert 'helloada_growth_candidates' in contract
    assert 'helloada_growth_operations' in contract
    assert "state = 'writing'" in contract
    assert 'assertNativeWriteAllowed' in contract
    assert 'ensureGrowthTables' not in contract
    assert 'CREATE TABLE' not in contract
    migration = (TEMPLATE / 'src/migrations/20261004_221500_growth_operations.ts').read_text(encoding='utf-8')
    assert 'CREATE TABLE' in migration
    assert 'CREATE UNIQUE INDEX' in migration
    assert 'function PublicDocument' in renderer
    assert "from '@weareheadless/helloada-payload-core/schema'" in config
    assert 'createHelloAdaSchema(assertNativeWriteAllowed)' in config
    for slug in ('pages', 'posts', 'products'):
        assert f"sectionCollectionHooks('{slug}', guard)" in shared_schema
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
