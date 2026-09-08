from site_agent.main import _loopback_host, main


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


def test_intake_lab_accepts_only_loopback_hosts():
    assert _loopback_host("127.0.0.1")
    assert _loopback_host("::1")
    assert _loopback_host("localhost")
    assert not _loopback_host("0.0.0.0")
    assert not _loopback_host("example.test")


def test_intake_lab_cli_defaults_are_loopback_and_port_3012(tmp_path, monkeypatch):
    import importlib

    module = importlib.import_module("site_agent.main")
    captured = {}

    def fake_handler(args):
        captured.update({"host": args.host, "port": args.port, "intake": args.intake})
        return 17

    monkeypatch.setattr(module, "_cmd_intake_lab", fake_handler)

    assert main([
        "intake-lab",
        "--workspace", str(tmp_path / "workspace"),
    ]) == 17
    assert captured == {"host": "127.0.0.1", "port": 3012, "intake": None}


def test_intake_lab_cli_rejects_non_loopback_before_loading_files(tmp_path, capsys):
    assert main([
        "intake-lab",
        "--intake", str(tmp_path / "missing.json"),
        "--workspace", str(tmp_path / "workspace"),
        "--host", "0.0.0.0",
    ]) == 1
    assert "loopback" in capsys.readouterr().err
