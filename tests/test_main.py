from site_agent.main import _adoption_verifier_command, main


def test_adoption_verifier_command_preserves_explicit_release_contract(tmp_path):
    import sys
    from argparse import Namespace

    verifier = tmp_path / "deploy-payload-customer.py"
    args = Namespace(
        tenant="oceanicvibes",
        source_sha="a" * 40,
        release_id="20261008-oceanic-messages-schema-3",
        release_purpose="website",
    )

    assert _adoption_verifier_command(verifier, args) == [
        sys.executable,
        str(verifier),
        "--tenant",
        "oceanicvibes",
        "--ref",
        "a" * 40,
        "--release-id",
        "20261008-oceanic-messages-schema-3",
        "--release-purpose",
        "website",
        "--verify-only",
    ]


def test_missing_config_fails_regardless_of_option_position(tmp_path):
    missing = str(tmp_path / "missing.yaml")
    assert main(["--config", missing, "check"]) == 2
    assert main(["check", "--config", missing]) == 2


def test_provision_r2_reads_global_bootstrap_env_file(tmp_path, monkeypatch):
    from site_agent.hands.cloudflare_r2 import R2ProvisioningError

    config = tmp_path / "config.yaml"
    config.write_text("instance_name: test\n")
    bootstrap = tmp_path / "global.env"
    bootstrap.write_text("CLOUDFLARE_API_TOKEN=bootstrap\n")
    monkeypatch.setattr(
        "site_agent.hands.cloudflare_r2.CloudflareR2Provisioner.provision",
        lambda self, bucket, **kwargs: (_ for _ in ()).throw(R2ProvisioningError("stop after parse")),
    )
    assert main([
        "provision-r2", "--config", str(config), "--instance", "test",
        "--account-id", "a" * 32, "--bootstrap-env-file", str(bootstrap),
    ]) == 2
