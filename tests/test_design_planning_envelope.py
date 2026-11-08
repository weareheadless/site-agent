def test_planning_envelope_allows_a_real_business_brief_without_truncation(tmp_path):
    """A full run envelope is not a shared 400 KB contract; truncating it would
    lose the design itself."""
    from site_agent.core.design_contracts import MAX_CONTRACT_BYTES, MAX_PLANNING_BYTES
    from site_agent.core.memory import Memory

    assert MAX_PLANNING_BYTES > MAX_CONTRACT_BYTES
    memory = Memory(tmp_path / "memory.db")
    memory.create_design_run(
        run_id="run-planning",
        mode="local_experiment",
        status="planning",
        intake_json={"business": {"name": "A"}},
        intake_hash="a" * 64,
        base_sha="b" * 40,
        publishable=False,
    )
    big = {"copy_deck": "x" * (MAX_CONTRACT_BYTES + 50_000)}
    memory.update_design_run("run-planning", planning_json=big)
    assert memory.get_design_run("run-planning")["planning_json"]["copy_deck"] == big["copy_deck"]
    memory.close()
