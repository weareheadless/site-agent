"""Fetch exact private GitHub release dependencies, then seed npm's integrity cache."""
import base64
import hashlib
import json
from pathlib import Path
import re
import tempfile
import urllib.parse
import urllib.request

ASSET = re.compile(r'^https://github\.com/weareheadless/site-agent/releases/download/([^/]+)/([^/]+\.tgz)$')


class ReleaseRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != 'https' or parsed.hostname not in {'api.github.com', 'release-assets.githubusercontent.com'}:
            raise RuntimeError('Unexpected GitHub release redirect host')
        redirected = super().redirect_request(request, fp, code, message, headers, url)
        if parsed.hostname != 'api.github.com':
            redirected.remove_header('Authorization')
        return redirected


def github_fetch(path, token, binary=False):
    request = urllib.request.Request('https://api.github.com' + path, headers={
        'Authorization': 'Bearer ' + token,
        'Accept': 'application/octet-stream' if binary else 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
    })
    with urllib.request.build_opener(ReleaseRedirect()).open(request, timeout=60) as response:
        data = response.read(32 * 1024 * 1024 + 1)
    if len(data) > 32 * 1024 * 1024:
        raise RuntimeError('Release asset exceeds maximum size')
    return data if binary else json.loads(data)


def verify_integrity(data, integrity):
    expected = 'sha512-' + base64.b64encode(hashlib.sha512(data).digest()).decode()
    if integrity != expected:
        raise RuntimeError('GitHub release artifact does not match committed lockfile integrity')


def prepare_release_dependencies(checkout, token, npm, environment, run):
    if not token:
        raise RuntimeError('Central GitHub release credential is required')
    package = json.loads((checkout / 'package.json').read_text())
    lock = json.loads((checkout / 'package-lock.json').read_text())
    evidence = []
    with tempfile.TemporaryDirectory(prefix='helloada-release-assets-') as temporary:
        for name in ('@weareheadless/helloada-payload-admin', '@weareheadless/helloada-payload-core'):
            url = package['dependencies'][name]
            match = ASSET.fullmatch(url)
            entry = lock['packages']['node_modules/' + name]
            if not match or entry.get('resolved') != url or not entry.get('integrity'):
                raise RuntimeError('Shared package requires an exact GitHub release URL and locked integrity')
            tag, filename = match.groups()
            release = github_fetch('/repos/weareheadless/site-agent/releases/tags/' + urllib.parse.quote(tag, safe=''), token)
            if release.get('tag_name') != tag or release.get('draft'):
                raise RuntimeError('Expected published immutable GitHub release')
            assets = [asset for asset in release['assets'] if asset['name'] == filename]
            if len(assets) != 1:
                raise RuntimeError('Expected exactly one locked GitHub release asset')
            asset = assets[0]
            data = github_fetch('/repos/weareheadless/site-agent/releases/assets/' + str(asset['id']), token, binary=True)
            verify_integrity(data, entry['integrity'])
            digest = 'sha256:' + hashlib.sha256(data).hexdigest()
            if asset.get('digest') != digest:
                raise RuntimeError('GitHub asset digest mismatch')
            target = Path(temporary) / filename
            target.write_bytes(data)
            target.chmod(0o600)
            run([npm, 'cache', 'add', str(target), '--ignore-scripts'], checkout, environment)
            evidence.append({'package': name, 'release': tag, 'assetId': asset['id'], 'integrity': entry['integrity'], 'digest': digest})
    return evidence
