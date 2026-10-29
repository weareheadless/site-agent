import json

from site_agent.qa.cli import main
from site_agent.qa.driver import DriverError, FlowResult


def test_driver_setup_failure_emits_error_evidence_for_runner(monkeypatch, tmp_path):
    flow = tmp_path / 'flow.json'
    flow.write_text(json.dumps({'id': 'example', 'steps': [{'id': 'open', 'action': 'goto', 'url': '/'}]}))

    def fail(*args):
        raise DriverError('browser installation unavailable')

    monkeypatch.setattr('site_agent.qa.cli.PlaywrightDriver.run', fail)
    monkeypatch.setattr('site_agent.qa.cli.probe_target', lambda base_url: {})
    queue = tmp_path / 'test-results'
    code = main(['run', str(flow), '--base-url', 'http://localhost',
                 '--evidence-dir', str(tmp_path / 'evidence'),
                 '--artifacts-dir', str(tmp_path / 'artifacts'),
                 '--runner-results-dir', str(queue)])
    assert code != 0
    receipts = list(queue.glob('*.json'))
    assert len(receipts) == 1
    bundle = json.loads(receipts[0].read_text())
    assert bundle['status'] == 'error'
    assert bundle['failure_kind'] == 'execution'
    assert bundle['rubric']['passed'] is False
    assert bundle['timings']['total_s'] is not None


def test_empty_driver_result_cannot_pass(monkeypatch, tmp_path):
    flow = tmp_path / 'flow.json'
    flow.write_text(json.dumps({'id': 'example', 'steps': [{'id': 'open', 'action': 'goto', 'url': '/'}]}))
    monkeypatch.setattr('site_agent.qa.cli.PlaywrightDriver.run',
                        lambda self, flow: FlowResult(flow=flow, base_url='http://localhost'))
    monkeypatch.setattr('site_agent.qa.cli.probe_target', lambda base_url: {})
    code = main(['run', str(flow), '--base-url', 'http://localhost',
                 '--evidence-dir', str(tmp_path / 'evidence'),
                 '--artifacts-dir', str(tmp_path / 'artifacts')])
    assert code == 1
