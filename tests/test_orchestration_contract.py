import pytest

from site_agent.brain.editor import _validate_website_change_plan
from site_agent.hands.repo_changes import source_path_allowed


def config():
    return {'design_engine': {'build_profile': 'next_react'}, 'site': {
        'writable_patterns': ['next.config.mjs', 'src/app/(frontend)/**', 'src/components/**', 'public/**']}}


def test_source_plan_and_validator_share_the_ownership_boundary():
    plan = {'content_effects': [], 'source_brief': 'Improve the section typography',
            'source_paths': ['src/components/site/presentation/Training.tsx'], 'response_only': False}
    accepted = _validate_website_change_plan(plan, None, config())
    assert accepted['source_paths'] == plan['source_paths']
    assert source_path_allowed(config(), accepted['source_paths'][0])
    for path in ['public/robots.txt', 'src/app/(frontend)/page.tsx', 'src/app/sitemap.ts', 'next.config.mjs']:
        assert not source_path_allowed(config(), path)
        with pytest.raises(ValueError, match='outside tenant ownership'):
            _validate_website_change_plan({**plan, 'source_paths': [path]}, None, config())


def test_source_plan_requires_an_explicit_scope_before_delegation():
    with pytest.raises(ValueError, match='declare source_paths'):
        _validate_website_change_plan({'content_effects': [], 'source_brief': 'Improve SEO',
                                      'response_only': False}, None, config())
