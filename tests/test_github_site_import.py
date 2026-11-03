import pytest
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
import yaml

from site_agent.application.github_site_import import (
    GitHubSiteImportError,
    normalize_repository,
    inspect_static_site,
)


@pytest.mark.parametrize('value', ['weareheadless/astrid-rincon-website', 'https://github.com/weareheadless/astrid-rincon-website.git'])
def test_repository_is_one_managed_github_identity(value):
    assert normalize_repository(value) == 'weareheadless/astrid-rincon-website'
    assert normalize_repository('weareheadless/Astrid-Rincon-Website') == 'weareheadless/astrid-rincon-website'


@pytest.mark.parametrize('value', ['https://github.com.evil/a/b', 'https://user@github.com/weareheadless/x',
                                  'https://github.com/weareheadless/x?token=x', 'other/x', '../x',
                                  'https://github.com/weareheadless/x/tree/main'])
def test_invalid_repository_rejected(value):
    with pytest.raises(GitHubSiteImportError):
        normalize_repository(value)


def test_static_inventory_preserves_pages_and_requires_assets(tmp_path):
    public = tmp_path / 'public'
    public.mkdir()
    (public / 'index.html').write_text('<html lang="es"><head><title>Astrid</title></head><body><img src="/assets/logo.webp"></body></html>')
    with pytest.raises(GitHubSiteImportError, match='missing'):
        inspect_static_site(tmp_path)
    (public / 'assets').mkdir()
    (public / 'assets/logo.webp').write_bytes(b'image')
    result = inspect_static_site(tmp_path)
    assert result['kind'] == 'static'
    assert result['routes'] == {'/': '/index.html'}
    assert result['defaultLocale'] == 'es'
    assert result['locales'] == ['es']
    assert result['files']['/assets/logo.webp']


def test_reserved_routes_and_symlinks_are_not_importable(tmp_path):
    public = tmp_path / 'public'
    public.mkdir()
    (public / 'index.html').write_text('<html lang="en"><head></head></html>')
    (public / 'admin').mkdir()
    (public / 'admin/index.html').write_text('not an admin')
    with pytest.raises(GitHubSiteImportError, match='reserved'):
        inspect_static_site(tmp_path)
    (public / 'admin/index.html').unlink()
    (public / 'admin').rmdir()
    (public / 'escape').symlink_to('/etc/passwd')
    with pytest.raises(GitHubSiteImportError, match='symlink'):
        inspect_static_site(tmp_path)


def test_import_scaffolds_platform_but_preserves_exact_public_source_and_history(tmp_path, monkeypatch):
    from site_agent.application.bootstrap import WebsiteBootstrapService

    upstream = tmp_path / 'upstream'
    upstream.mkdir()
    def git(root, *args):
        return subprocess.check_output(['git', '-C', str(root), *args], text=True).rstrip()
    git(upstream, 'init', '-q', '-b', 'main')
    git(upstream, 'config', 'user.email', 'test@localhost')
    git(upstream, 'config', 'user.name', 'Test')
    (upstream / 'public').mkdir()
    original = '<html lang="es"><head><title>Astrid</title></head><body>Owner-designed</body></html>'
    (upstream / 'public/index.html').write_text(original)
    (upstream / 'package.json').write_text('{"scripts":{"deploy":"wrangler deploy"}}')
    (upstream / 'wrangler.jsonc').write_text('{"account_id":"old-account","routes":[{"pattern":"astridrincon.com"}]}')
    git(upstream, 'add', '.')
    git(upstream, 'commit', '-qm', 'Owner-designed website')
    source_sha = git(upstream, 'rev-parse', 'HEAD')
    tenant = tmp_path / 'tenant'
    tenant.mkdir()
    config = tenant / 'config.yaml'
    config.write_text(yaml.safe_dump({'provisioning_source': {'kind': 'github_static', 'repository': 'weareheadless/astrid-rincon-website'}}))
    service = WebsiteBootstrapService({'workspace_api': {'provisioned_root': str(tmp_path / 'registered')}}, {},
                                     registration=SimpleNamespace(root=tmp_path / 'registered'), registry=SimpleNamespace())
    remote = 'git@github.com:weareheadless/astrid-rincon-website.git'
    pushes = []
    def transport(root, *args, **kwargs):
        if args[0] == 'clone':
            result = git(root, *[str(upstream) if arg == remote else arg for arg in args])
            git(Path(args[-1]), 'remote', 'set-url', 'origin', remote)
            return result
        if args[0] == 'push':
            pushes.append(args)
            return ''
        return git(root, *args)
    monkeypatch.setattr(service, '_git', transport)
    try:
        receipt = service._repository('astrid-site', 'Astrid', config)
        site = Path(receipt['site_dir'])
        assert (site / 'public/index.html').read_text() == original
        assert receipt['source_sha'] == source_sha
        assert git(site, 'rev-parse', 'HEAD^') == source_sha
        assert 'old-account' not in (site / 'wrangler.jsonc').read_text()
        assert (site / 'template-manifest.json').is_file()
        assert 'defaultLocale: "es"' in (site / 'src/helloada.config.ts').read_text()
        assert json.loads((site / 'template-manifest.json').read_text())['defaultLocale'] == 'es'
        assert pushes == [('push', '-u', 'origin', 'main')]
        assert service._repository('astrid-site', 'Astrid', config)['full_name'] == receipt['full_name']
        assert len(pushes) == 1
    finally:
        service.close()
