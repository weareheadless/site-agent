from site_agent.application.design_jobs import DesignJobExecutor
from site_agent.core.design_contracts import BuildTarget, PageBuildRequest


def _request():
    return PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "design-job",
        "mode": "initial_homepage",
        "base_sha": "a" * 40,
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "acceptance_criteria": ["Keep the homepage accessible."],
    })


def _target():
    return BuildTarget.from_dict({
        "mode": "production_candidate",
        "base_sha": "a" * 40,
        "candidate_ref": "refs/ada-design/design-job",
        "push_mode": "none",
        "publishable": True,
    })


def test_design_worker_rehydrates_typed_request_and_target():
    request, target = _request(), _target()
    run = {
        "run_id": "design-job",
        "status": "planning",
        "planning_json": {
            "build_request": request.to_dict(),
            "build_target": target.to_dict(),
        },
    }

    class Memory:
        def __init__(self):
            self.events = []

        def add_design_run_event(self, run_id, stage, message, detail=None):
            self.events.append((run_id, stage, message, detail))

        def get_design_run(self, run_id):
            return run

    class Service:
        def __init__(self, memory):
            self.memory = memory
            self.calls = []

        def get_run(self, run_id):
            return run

        def execute_build(self, run_id, actual_request, actual_target, progress=None):
            self.calls.append(("build", run_id, actual_request, actual_target))
            assert actual_request == request
            assert actual_target == target

        def clone_path_for_run(self, run_id):
            self.calls.append(("clone", run_id))
            return "/tmp/design-job-clone"

        def validate_run(self, run_id, clone, browser=None):
            self.calls.append(("validate", run_id, clone, browser))

    memory = Memory()
    service = Service(memory)
    executor = DesignJobExecutor({"memory": memory}, service)

    executor._run("design-job")

    assert [call[0] for call in service.calls] == ["build", "clone", "validate"]
    assert [event[1] for event in memory.events] == ["claimed"]


def test_design_worker_links_a_passing_customer_candidate_to_review():
    run = {
        "run_id": "design-customer",
        "mode": "production_candidate",
        "status": "ready_for_review",
        "draft_id": None,
    }

    class Memory:
        def add_design_run_event(self, *args):
            raise AssertionError(f"unexpected review link event: {args}")

    class Service:
        def __init__(self):
            self.calls = []

        def get_run(self, run_id):
            assert run_id == run["run_id"]
            return run

        def create_review_draft(self, run_id):
            self.calls.append(run_id)
            run["draft_id"] = 42
            return run

    service = Service()
    executor = DesignJobExecutor({"memory": Memory()}, service)

    executor._link_review_draft_if_ready(run["run_id"])

    assert service.calls == ["design-customer"]
    assert run["draft_id"] == 42


def test_design_worker_uses_a_browser_factory_for_each_run():
    request, target = _request(), _target()
    run = {
        "run_id": "design-job",
        "status": "planning",
        "planning_json": {"build_request": request.to_dict(), "build_target": target.to_dict()},
    }

    class Memory:
        def __init__(self):
            self.events = []

        def add_design_run_event(self, run_id, stage, message, detail=None):
            self.events.append((run_id, stage, message, detail))

        def get_design_run(self, run_id):
            return run

    class Service:
        def __init__(self, memory):
            self.memory = memory
            self.calls = []

        def get_run(self, run_id):
            return run

        def execute_build(self, *args, **kwargs):
            self.calls.append("build")

        def clone_path_for_run(self, run_id):
            return "/tmp/design-job-clone"

        def validate_run(self, run_id, clone, browser=None):
            self.calls.append(("validate", browser))

    browser = object()
    memory = Memory()
    service = Service(memory)
    factory_calls = []
    executor = DesignJobExecutor(
        {"memory": memory, "browser_quality_factory": lambda run_id, value: factory_calls.append(run_id) or browser},
        service,
    )

    executor._run("design-job")

    assert factory_calls == ["design-job"]
    assert service.calls[-1] == ("validate", browser)


def test_design_worker_restarts_a_retained_candidate_without_rebuilding():
    run = {
        "run_id": "design-job",
        "status": "candidate_ready",
        "candidate_sha": "c" * 40,
        "quality_report_json": {},
        "events": [],
    }

    class Memory:
        def __init__(self):
            self.events = []

        def add_design_run_event(self, run_id, stage, message, detail=None):
            self.events.append((run_id, stage, message, detail))

        def get_design_run(self, run_id):
            return run

        def transition_design_run(self, run_id, status, error=None):
            run["status"] = status
            return run

    class Service:
        def __init__(self, memory):
            self.memory = memory
            self.calls = []

        def get_run(self, run_id):
            return run

        def execute_build(self, *args, **kwargs):
            self.calls.append("build")
            raise AssertionError("retained candidates must not be rebuilt")

        def clone_path_for_run(self, run_id):
            self.calls.append("clone")
            return "/tmp/design-job-clone"

        def validate_run(self, run_id, clone, browser=None):
            self.calls.append(("validate", browser))
            run["status"] = "ready_for_review"

    memory = Memory()
    service = Service(memory)
    browser = object()
    executor = DesignJobExecutor(
        {"memory": memory, "browser_quality_factory": lambda run_id, value: browser},
        service,
    )

    executor._run(run["run_id"])

    assert service.calls == ["clone", ("validate", browser)]
    assert run["status"] == "ready_for_review"


def test_design_worker_restarts_validating_candidate_with_read_only_visual_review():
    run = {
        "run_id": "design-job",
        "status": "validating",
        "candidate_sha": "c" * 40,
        "quality_report_json": {"state": "passed"},
        "events": [{"stage": "visual_review_pending"}],
    }

    class Memory:
        def __init__(self):
            self.events = []

        def add_design_run_event(self, *args):
            self.events.append(args)

        def get_design_run(self, run_id):
            return run

    class Service:
        def __init__(self, memory):
            self.memory = memory
            self.calls = []

        def get_run(self, run_id):
            return run

        def clone_path_for_run(self, run_id):
            return "/tmp/design-job-clone"

        def validate_run(self, *args, **kwargs):
            self.calls.append("validate")

        def visual_review_run(self, run_id, **kwargs):
            self.calls.append(("visual_review", run_id))

    memory = Memory()
    service = Service(memory)
    executor = DesignJobExecutor({"memory": memory, "env": {"HOME": "/tmp/lab"}}, service)

    executor._run(run["run_id"])

    assert service.calls == [("visual_review", "design-job")]
    assert executor._queued == set()


def test_design_worker_visual_review_service_error_is_non_fatal():
    run = {
        "run_id": "design-job",
        "status": "validating",
        "candidate_sha": "d" * 40,
        "quality_report_json": {"state": "passed"},
        "events": [{"stage": "visual_review_pending"}],
    }

    class Memory:
        def __init__(self):
            self.events = []

        def add_design_run_event(self, *args):
            self.events.append(args)

        def get_design_run(self, run_id):
            return run

    class Service:
        def __init__(self, memory):
            self.memory = memory
            self.calls = []

        def get_run(self, run_id):
            return run

        def clone_path_for_run(self, run_id):
            return "/tmp/design-job-clone"

        def validate_run(self, *args, **kwargs):
            self.calls.append("validate")

        def visual_review_run(self, run_id, **kwargs):
            self.calls.append(("visual_review", run_id))
            raise RuntimeError("review provider unavailable")

    memory = Memory()
    service = Service(memory)
    executor = DesignJobExecutor({"memory": memory, "env": {"HOME": "/tmp/lab"}}, service)

    executor._run(run["run_id"])

    assert service.calls == [("visual_review", "design-job")]
    assert executor._queued == set()


def test_design_worker_marks_abandoned_build_interrupted_on_restart():
    run = {"run_id": "design-job", "status": "building", "events": []}

    class Memory:
        def __init__(self):
            self.events = []

        def add_design_run_event(self, *args):
            self.events.append(args)

        def get_design_run(self, run_id):
            return run

        def transition_design_run(self, run_id, status, error=None):
            run["status"] = status
            run["error"] = error
            return run

    class Service:
        def __init__(self, memory):
            self.memory = memory

        def list_runs(self, limit=500):
            return [run]

    memory = Memory()
    executor = DesignJobExecutor(
        {"memory": memory, "recover_retained_candidates": True},
        Service(memory),
    )

    executor._recover_queued()

    assert run["status"] == "interrupted"
    assert any(event[1] == "interrupted" for event in memory.events)


def test_design_worker_records_terminal_quality_activity():
    request, target = _request(), _target()
    run = {
        "run_id": "design-job",
        "status": "planning",
        "planning_json": {"build_request": request.to_dict(), "build_target": target.to_dict()},
    }

    class Memory:
        def add_design_run_event(self, *args):
            pass

        def get_design_run(self, run_id):
            return run

    class Service:
        def __init__(self, memory):
            self.memory = memory

        def get_run(self, run_id):
            return run

        def execute_build(self, *args, **kwargs):
            run["status"] = "ready_for_review"

    class Activity:
        def __init__(self):
            self.events = []

        def record(self, **kwargs):
            self.events.append(kwargs)

    memory = Memory()
    activity = Activity()
    executor = DesignJobExecutor({"memory": memory, "activity_service": activity}, Service(memory))

    executor._run(run["run_id"])

    assert [event["kind"] for event in activity.events] == [
        "design_run_started",
        "quality_checks_completed",
    ]
    assert activity.events[-1]["category"] == "quality"
    assert activity.events[-1]["state"] == "completed"


def test_design_worker_records_restart_interruption_activity():
    run = {"run_id": "design-job", "status": "building", "events": []}

    class Memory:
        def __init__(self):
            self.events = []

        def add_design_run_event(self, *args):
            self.events.append(args)

        def get_design_run(self, run_id):
            return run

        def transition_design_run(self, run_id, status, error=None):
            run["status"] = status
            return run

    class Service:
        def list_runs(self, limit=500):
            return [run]

    class Activity:
        def __init__(self):
            self.events = []

        def record(self, **kwargs):
            self.events.append(kwargs)

    memory = Memory()
    activity = Activity()
    executor = DesignJobExecutor(
        {"memory": memory, "activity_service": activity, "recover_retained_candidates": True},
        Service(),
    )

    executor._recover_queued()

    assert activity.events[-1]["kind"] == "design_run_interrupted"
    assert activity.events[-1]["state"] == "needs_attention"
