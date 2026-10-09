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


def verify_integrity(data, integrity, package_name):
    actual = 'sha512-' + base64.b64encode(hashlib.sha512(data).digest()).decode()
    if integrity != actual:
        raise RuntimeError(
            f'{package_name}: published artifact SHA-512 does not match package-lock.json '
            f'(expected {integrity}, received {actual})'
        )


def _verified_release_dependencies(checkout, token):
    if not token:
        raise RuntimeError('Central GitHub release credential is required')
    package = json.loads((checkout / 'package.json').read_text())
    lock = json.loads((checkout / 'package-lock.json').read_text())
    for name in ('@weareheadless/helloada-payload-admin', '@weareheadless/helloada-payload-core'):
        url = package['dependencies'][name]
        match = ASSET.fullmatch(url)
        entry = lock['packages']['node_modules/' + name]
        if not match or entry.get('resolved') != url or not entry.get('integrity'):
            raise RuntimeError(f'{name}: requires an exact GitHub release URL and locked integrity')
        tag, filename = match.groups()
        release = github_fetch('/repos/weareheadless/site-agent/releases/tags/' + urllib.parse.quote(tag, safe=''), token)
        if release.get('tag_name') != tag or release.get('draft'):
            raise RuntimeError(f'{name}: expected published immutable GitHub release {tag}')
        assets = [asset for asset in release['assets'] if asset['name'] == filename]
        if len(assets) != 1:
            raise RuntimeError(f'{name}: expected exactly one GitHub release asset {filename}')
        asset = assets[0]
        data = github_fetch('/repos/weareheadless/site-agent/releases/assets/' + str(asset['id']), token, binary=True)
        verify_integrity(data, entry['integrity'], name)
        digest = 'sha256:' + hashlib.sha256(data).hexdigest()
        if asset.get('digest') != digest:
            raise RuntimeError(f'{name}: GitHub asset digest does not match downloaded bytes')
        yield {'package': name, 'release': tag, 'filename': filename, 'assetId': asset['id'],
               'integrity': entry['integrity'], 'digest': digest, 'data': data}


def verify_release_dependencies(checkout, token):
    """Verify canonical lockfile entries against the exact published GitHub bytes."""
    keys = ('package', 'release', 'assetId', 'integrity', 'digest')
    return [{key: artifact[key] for key in keys}
            for artifact in _verified_release_dependencies(checkout, token)]


def prepare_release_dependencies(checkout, token, npm, environment, run):
    evidence = []
    with tempfile.TemporaryDirectory(prefix='helloada-release-assets-', dir=environment.get('TMPDIR')) as temporary:
        for artifact in _verified_release_dependencies(checkout, token):
            target = Path(temporary) / artifact['filename']
            target.write_bytes(artifact['data'])
            target.chmod(0o600)
            run([npm, 'cache', 'add', str(target), '--ignore-scripts'], checkout, environment)
            evidence.append({key: artifact[key] for key in
                             ('package', 'release', 'assetId', 'integrity', 'digest')})
    return evidence


if __name__ == '__main__':
    import os

    for item in verify_release_dependencies(Path.cwd() / 'src/site_agent/templates/next-payload', os.environ.get('GITHUB_TOKEN', '')):
        print(f"Verified {item['package']} {item['release']} ({item['digest']})")
