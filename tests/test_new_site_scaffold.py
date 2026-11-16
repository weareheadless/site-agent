import subprocess
from pathlib import Path

from site_agent.brain import new_site
from site_agent.hands import opencode_runner
from site_agent.hands.opencode_runner import install_agent_files
from site_agent.site_scaffold import initialize_payload_site


def _git_repo(root: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.email=a@b", "-c", "user.name=t", "commit", "-qm", "scaffold"],
        check=True,
    )
    return root


def _install(root: Path) -> str:
    install_agent_files(root, None, None)
    return (root / ".opencode/ada-instructions.md").read_text(encoding="utf-8")


def test_new_site_brief_is_offered_while_the_home_route_is_the_scaffold(tmp_path):
    root = _git_repo(initialize_payload_site(tmp_path / "site", "New One", "https://new.example"))

    assert new_site.homepage_is_scaffold(root)
    instructions = _install(root)
    # The brief is the one thing a new site adds: establish the brief with the
    # owner, then author the first page. It carries rules, not sample copy.
    assert opencode_runner.ADA_INSTRUCTIONS.splitlines()[0] in instructions
    assert "Establish the brief with the owner" in instructions
    assert "The owner reviews the result as a preview" in instructions


def test_new_site_brief_disappears_once_the_scaffold_is_replaced(tmp_path):
    root = _git_repo(initialize_payload_site(tmp_path / "site", "New One", "https://new.example"))
    (root / new_site.HOME_ROUTE).write_text(
        "export default function Page() { return <main><h1>Built</h1></main> }\n",
        encoding="utf-8",
    )

    assert not new_site.homepage_is_scaffold(root)
    instructions = _install(root)
    # Ada's standing instructions still apply; only the new-site brief is gone.
    assert opencode_runner.ADA_INSTRUCTIONS.splitlines()[0] in instructions
    assert "Establish the brief with the owner" not in instructions


def test_a_site_without_the_home_route_is_not_treated_as_new(tmp_path):
    root = _git_repo(initialize_payload_site(tmp_path / "site", "New One", "https://new.example"))
    (root / new_site.HOME_ROUTE).unlink()

    # An imported or restructured site is not a scaffold: absence is not the
    # new-site state, and guessing would resurrect a retired journey.
    assert not new_site.homepage_is_scaffold(root)
