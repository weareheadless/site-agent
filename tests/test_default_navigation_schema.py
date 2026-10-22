from pathlib import Path


def test_default_navigation_uses_the_canonical_schema_link_policy():
    source = (Path(__file__).parents[1] / "src/site_agent/templates/next-payload/src/components/site/TenantChrome.tsx").read_text()
    assert "import { validateHelloAdaLink } from '@weareheadless/helloada-payload-core/schema'" in source
    assert "const validation = validateHelloAdaLink(value)" in source
    assert "if (validation !== true) throw" in source
    assert "new URL(" not in source
