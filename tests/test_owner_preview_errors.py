from site_agent.application.workspace import _owner_preview_job


def test_owner_preview_failure_keeps_the_reason_without_paths_or_tracebacks():
    diagnostic = '/SOCIAL/private/preview/node_modules/schema.ts:281\nTraceback: Section 1 needs a name.'
    job = {'id': 'preview-failed-1', 'status': 'failed', 'error': diagnostic, 'commit': 'a' * 40}
    projected = _owner_preview_job(job)
    assert projected['status'] == 'failed'
    assert projected['commit'] == job['commit']
    assert projected['diagnostic_id'] == job['id']
    # The owner is told what to change, not just that something went wrong.
    assert 'could not be prepared' in projected['error']
    assert 'Section 1 needs a name.' in projected['error']
    assert '/SOCIAL' not in projected['error'] and 'Traceback' not in projected['error']
    assert len(projected['error']) < 320
    assert job['error'] == diagnostic


def test_owner_preview_failure_names_the_page_and_the_missing_file():
    diagnostic = (
        'compiled preview page / references http://127.0.0.1:44761/p/site/icon-1dmzes.svg, '
        'which returned 404; the candidate names a file it cannot serve'
    )
    projected = _owner_preview_job({'id': 'job-2', 'status': 'failed', 'error': diagnostic})
    assert 'page /' in projected['error']
    assert 'icon-1dmzes.svg' in projected['error']
    assert '404' in projected['error']
    assert '127.0.0.1' not in projected['error']


def test_ready_preview_is_not_changed_by_owner_projection():
    job = {'id': 'preview-ready-1', 'status': 'ready', 'preview_url': '/ada/preview/'}
    assert _owner_preview_job(job) == job
