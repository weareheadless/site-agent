import json
from pathlib import Path


def test_content_gateway_platform_dependencies_are_in_the_shared_overlay():
    root = Path(__file__).parents[1]
    copied = set(json.loads((root / 'deploy/shared-runtime-overlay.json').read_text())['copy'])
    dependencies = {
        'src/app/api/workspace/content/route.ts',
        'src/lib/payload-field-match.ts',
        'src/lib/payload-locale.ts',
        'mailflare-booking-service.ts',
    }
    assert dependencies <= copied
    template = root / 'src/site_agent/templates/next-payload'
    for path in dependencies:
        assert (template / path).is_file(), path
    route = (template / 'src/app/api/workspace/content/route.ts').read_text()
    assert "from '../../../../../mailflare-booking-service'" in route
