from site_agent.main import main


def test_missing_config_fails_regardless_of_option_position(tmp_path):
    missing = str(tmp_path / "missing.yaml")
    assert main(["--config", missing, "check"]) == 2
    assert main(["check", "--config", missing]) == 2
