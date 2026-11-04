import json
import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
TEMPLATE = ROOT / 'src/site_agent/templates/next-payload'
OVERLAY = ROOT / 'deploy/shared-runtime-overlay.json'

# Modules that stay in the tenant repository on purpose: the preview renderer is
# tenant presentation composition, not shared runtime. Anything else an overlaid
# file imports has to be copied with it.
TENANT_OWNED = {
    'src/lib/helloada-preview-renderer.tsx',
}


def _copied() -> set[str]:
    return set(json.loads(OVERLAY.read_text())['copy'])


def _local_lib_imports(source: str) -> list[str]:
    """Return the `@/lib/...` specifiers a source file imports."""
    return re.findall(r"""from\s+['"](@/lib/[^'"]+)['"]""", source)


def _resolve(specifier: str) -> str | None:
    relative = specifier.removeprefix('@/')
    for candidate in (f'src/{relative}.ts', f'src/{relative}.tsx',
                      f'src/{relative}/index.ts', f'src/{relative}/index.tsx'):
        if (TEMPLATE / candidate).is_file():
            return candidate
    return None


def test_every_overlaid_file_imports_only_overlaid_local_libraries():
    """A shared-runtime file that imports a non-overlaid module breaks tenant builds.

    The release runner copies exactly the declared overlay into a disposable
    tenant workspace. A new helper that exists only in the scaffold would be
    missing there, so an otherwise valid release would fail at build time.
    """
    copied = _copied()
    missing: dict[str, set[str]] = {}
    for relative in sorted(copied):
        if not relative.startswith('src/') or not relative.endswith(('.ts', '.tsx')):
            continue
        source = TEMPLATE / relative
        if not source.is_file():
            continue
        for specifier in _local_lib_imports(source.read_text(encoding='utf-8')):
            target = _resolve(specifier)
            if target and target not in copied and target not in TENANT_OWNED:
                missing.setdefault(relative, set()).add(target)
    assert missing == {}, f'shared runtime imports non-overlaid modules: {missing}'


def test_tenant_owned_exceptions_are_not_also_overlaid():
    assert not (TENANT_OWNED & _copied()), 'a tenant-owned module must not be overwritten by the overlay'
    for relative in TENANT_OWNED:
        assert (TEMPLATE / relative).is_file(), relative


def test_the_revision_contract_and_media_gateway_are_shared_runtime():
    copied = _copied()
    for relative in ('src/lib/payload-revision.ts', 'src/app/api/workspace/media/route.ts'):
        assert relative in copied
        assert (TEMPLATE / relative).is_file(), relative
