from site_agent.application.workspace import _owner_preview_job


def test_owner_preview_failure_keeps_diagnostic_identity_without_exposing_traceback():
    diagnostic = '/SOCIAL/private/preview/node_modules/schema.ts:281\nTraceback: Section 1 needs a name.'
    job = {'id': 'preview-failed-1', 'status': 'failed', 'error': diagnostic, 'commit': 'a' * 40}
    projected = _owner_preview_job(job)
    assert projected['status'] == 'failed'
    assert projected['commit'] == job['commit']
    assert projected['diagnostic_id'] == job['id']
    assert projected['error'] and len(projected['error']) < 200
    assert '/SOCIAL' not in projected['error'] and 'Traceback' not in projected['error']
    assert job['error'] == diagnostic


def test_ready_preview_is_not_changed_by_owner_projection():
    job = {'id': 'preview-ready-1', 'status': 'ready', 'preview_url': '/ada/preview/'}
    assert _owner_preview_job(job) == job
