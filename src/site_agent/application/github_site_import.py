"""The supported existing-repository convention: committed static public/ files.

This is not a framework detector or content importer. Payload still owns its
collections; these pages remain the operator's source-controlled presentation.
"""

from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit


class GitHubSiteImportError(ValueError):
    pass


# Cloudflare caps a text binding at 5.1 kB, so the per-page route inventory
# ships as an asset next to the pages it describes.
STATIC_MANIFEST_ASSET = '/_helloada/static-manifest.json'


def normalize_repository(value: str) -> str:
    value = str(value or '').strip()
    if value.startswith('https://github.com/'):
        parsed = urlsplit(value)
        if parsed.netloc != 'github.com' or parsed.query or parsed.fragment:
            raise GitHubSiteImportError('Use a managed GitHub repository, without credentials, query or branch.')
        value = parsed.path.removeprefix('/')
    if value.endswith('.git'):
        value = value[:-4]
    if not re.fullmatch(r'weareheadless/[A-Za-z0-9][A-Za-z0-9_-]*(?:\.[A-Za-z0-9_-]+)*', value) or len(value.split('/')[-1]) > 100:
        raise GitHubSiteImportError('Use a weareheadless GitHub repository on main.')
    return value.lower()


class _References(HTMLParser):
    def __init__(self):
        super().__init__()
        self.references: list[str] = []
        self.locale = ''

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'html':
            self.locale = str(attrs.get('lang') or '').split('-')[0].lower()
        for key in ('src', 'poster'):
            if attrs.get(key):
                self.references.append(attrs[key])
        if tag == 'link' and attrs.get('rel') in {'stylesheet', 'icon', 'preload'} and attrs.get('href'):
            self.references.append(attrs['href'])
        if attrs.get('srcset'):
            self.references.extend(item.strip().split()[0] for item in attrs['srcset'].split(',') if item.strip())


def inspect_static_site(root: Path) -> dict:
    public = root / 'public'
    if not (public / 'index.html').is_file() or public.is_symlink():
        raise GitHubSiteImportError('The supported repository needs a committed public/index.html.')
    files: dict[str, str] = {}
    routes: dict[str, str] = {}
    locales: set[str] = set()
    default_locale = ''
    for path in sorted(public.rglob('*')):
        if path.is_symlink():
            raise GitHubSiteImportError('Static website files must not contain a symlink.')
        if not path.is_file():
            continue
        relative = '/' + path.relative_to(public).as_posix()
        # The canonical build writes its own provenance marker. It is not
        # customer presentation and must not invalidate the frozen inventory.
        if relative == '/helloada-release.json':
            continue
        if relative.split('/')[1] in {'admin', 'api', '_next', 'mail', 'blog', '_helloada'}:
            raise GitHubSiteImportError(f'Static website uses a reserved platform path: {relative}')
        if path.stat().st_size > 25 * 1024 * 1024:
            raise GitHubSiteImportError(f'Static asset exceeds the supported limit: {relative}')
        files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        references: list[str] = []
        if path.suffix == '.html':
            parser = _References()
            html = path.read_text(encoding='utf-8')
            if relative != '/404.html' and not re.search(r'</head\s*>', html, re.IGNORECASE):
                raise GitHubSiteImportError(f'An explicit HTML head boundary is required: {relative}')
            parser.feed(html)
            if not re.fullmatch('[a-z]{2,3}', parser.locale):
                raise GitHubSiteImportError(f'An explicit HTML language is required: {relative}')
            locales.add(parser.locale)
            if relative == '/index.html':
                default_locale = parser.locale
            if path.name == 'index.html':
                routes[relative.removesuffix('index.html')] = relative
            references = parser.references
        elif path.suffix == '.css':
            references = re.findall(r'url\(\s*[\'"]?([^\s\)\'";]+)', path.read_text(encoding='utf-8'))
        for reference in references:
            parsed = urlsplit(reference)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            resolved = unquote(urlsplit(urljoin('https://static.invalid' + relative, reference)).path)
            target = (public / resolved.lstrip('/')).resolve()
            if not target.is_relative_to(public.resolve()) or not target.is_file():
                raise GitHubSiteImportError(f'Static website asset is missing: {reference} in {relative}')
    return {'kind': 'static', 'defaultLocale': default_locale,
            'locales': [default_locale, *sorted(locales - {default_locale})],
            'routes': routes, 'files': files}


def static_manifest_path(root: Path) -> Path:
    """The committed inventory travels with the Worker assets, not a text binding."""
    return root / '.open-next' / 'assets' / STATIC_MANIFEST_ASSET.lstrip('/')


def write_static_manifest(root: Path, declaration: dict) -> Path:
    """Materialize the reviewed inventory into the built asset tree."""
    path = static_manifest_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(declaration, separators=(',', ':')) + '\n', encoding='utf-8')
    return path


def validate_static_declaration(root: Path, worker: dict) -> dict:
    """Bind source files, routing and actual Worker variables before any release."""
    declared = json.loads((root / 'helloada-frontend.json').read_text())
    actual = inspect_static_site(root)
    if any(declared.get(key) != value for key, value in actual.items()):
        raise GitHubSiteImportError('Static presentation manifest differs from the committed website files.')
    if not re.fullmatch('[0-9a-f]{40}', str(declared.get('sourceSha') or '')):
        raise GitHubSiteImportError('Static presentation has no imported source identity.')
    variables = worker.get('vars') or {}
    if variables.get('HELLOADA_PRESENTATION_PROFILE') != 'static':
        raise GitHubSiteImportError('Worker static presentation differs from the committed declaration.')
    if 'HELLOADA_STATIC_MANIFEST' in variables:
        raise GitHubSiteImportError('Static presentation inventory must ship with the Worker assets, not a text binding.')
    assets = worker.get('assets') or {}
    if assets.get('run_worker_first') is not True or assets.get('html_handling') != 'none':
        raise GitHubSiteImportError('Static HTML must pass through the tenant Worker for runtime SEO bindings.')
    return declared


def validate_static_artifact(root: Path, declaration: dict) -> None:
    """Prove OpenNext preserved every declared public file, not just source."""
    assets = root / '.open-next/assets'
    for relative, digest in declaration['files'].items():
        artifact = assets / relative.lstrip('/')
        if not artifact.is_file() or artifact.is_symlink() or hashlib.sha256(artifact.read_bytes()).hexdigest() != digest:
            raise GitHubSiteImportError(f'Compiled static asset is missing or differs from the reviewed source: {relative}')
    manifest = static_manifest_path(root)
    if not manifest.is_file() or manifest.is_symlink():
        raise GitHubSiteImportError('Compiled static asset tree has no reviewed route inventory.')
    try:
        shipped = json.loads(manifest.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise GitHubSiteImportError('Compiled static route inventory is not valid JSON.') from error
    if shipped != declaration:
        raise GitHubSiteImportError('Compiled static route inventory differs from the reviewed declaration.')
