"""The repository release workflow must explain why a run cannot deploy.

A refused run used to die with an empty "deploy credential intake refused"
message, because the response body was the only diagnostic and it went to a
file. Three separate failures — a repository with no release identity, a
platform refusal, and a missing OIDC token — all looked identical in the log,
so the lane appeared broken rather than unenrolled.
"""
import yaml
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (
    ROOT / 'src' / 'site_agent' / 'templates' / 'next-payload'
    / '.github' / 'workflows' / 'release-deploy.yml'
)


def _steps():
    document = yaml.safe_load(WORKFLOW.read_text(encoding='utf-8'))
    return document['jobs']['deploy']['steps']


def _step(name):
    for step in _steps():
        if step.get('name') == name:
            return step
    raise AssertionError(f'the release workflow has no step named {name!r}')


def test_a_repository_without_a_release_identity_fails_with_the_remedy():
    step = _step("Read this repository's release identity")
    script = step['run']
    assert '.github/helloada-release.json' in script
    assert 'sync-tenant-repository-check.py --apply' in script
    assert '::error::' in script


def test_the_run_publishes_the_tenant_once_instead_of_re_reading_the_file():
    assert 'HELLOADA_RELEASE_TENANT=' in _step("Read this repository's release identity")['run']
    for name in ('Fetch this run\'s deploy material', 'Deploy the exact commit',
                 'Report the release to the platform'):
        script = _step(name)['run']
        assert 'HELLOADA_RELEASE_TENANT' in script, name
        assert 'helloada-release.json"))["tenant"]' not in script, name


def test_a_refused_intake_reports_its_http_status_and_body():
    script = _step("Fetch this run's deploy material")['run']
    assert '-w \'%{http_code}\'' in script
    assert 'the platform refused this run\'s deploy material' in script
    assert 'cat "$RUNNER_TEMP/deploy.json" >&2' in script


def test_a_missing_oidc_token_is_named_instead_of_misreported():
    script = _step("Fetch this run's deploy material")['run']
    assert 'did not issue this run an OIDC token' in script
    assert 'id-token: write' in _workflow_text()


def _workflow_text():
    return WORKFLOW.read_text(encoding='utf-8')
