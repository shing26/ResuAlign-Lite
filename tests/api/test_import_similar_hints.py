"""ADR-0065: import response carries near-duplicate hints, never blocking."""

from __future__ import annotations

from resualign.api.services import jobs as jobs_service


def _batch(rows):
    return {
        'user_id': 'tenant-import',
        'rows': rows,
        'created': 0,
        'skipped': 0,
        'errors': [],
        'done': False,
        'preanalyze': False,
        'analyzed': 0,
        'analyze_errors': [],
        'job_ids': [],
    }


def _prepare(monkeypatch, batch, import_id):
    jobs_service.context._import_batches[import_id] = batch
    monkeypatch.setattr(
        jobs_service.context,
        '_create_job_from_source',
        lambda user, row: {'job_id': 'job-' + str(row.get('title'))},
    )
    monkeypatch.setattr(
        jobs_service.context, '_prune_import_batches', lambda *args, **kwargs: None
    )


def test_import_attaches_similar_hints(monkeypatch):
    batch = _batch([{'title': 'A', 'jd_text': 'java backend'}])
    _prepare(monkeypatch, batch, 'imp-hints')
    monkeypatch.setattr(
        jobs_service,
        'similar_existing_for_texts',
        lambda *args, **kwargs: [
            [{'job_id': 'old-1', 'title': 'Old', 'company': 'C', 'score': 0.95}]
        ],
    )

    jobs_service._run_import('imp-hints')

    assert batch['done'] is True
    assert batch['created'] == 1
    assert batch['similar_existing'][0]['job_id'] == 'job-A'
    assert batch['similar_existing'][0]['similar'][0]['job_id'] == 'old-1'


def test_import_survives_hint_failure(monkeypatch):
    batch = _batch([{'title': 'B', 'jd_text': 'java backend'}])
    _prepare(monkeypatch, batch, 'imp-hints-fail')

    def boom(*args, **kwargs):
        raise RuntimeError('embedder down')

    monkeypatch.setattr(jobs_service, 'similar_existing_for_texts', boom)

    jobs_service._run_import('imp-hints-fail')

    assert batch['done'] is True
    assert batch['created'] == 1
    assert 'similar_existing' not in batch


def test_import_skips_hints_without_created_rows(monkeypatch):
    batch = _batch([{'title': 'C', 'jd_text': ''}])
    _prepare(monkeypatch, batch, 'imp-empty')
    calls = []
    monkeypatch.setattr(
        jobs_service,
        'similar_existing_for_texts',
        lambda *args, **kwargs: calls.append(args) or [],
    )

    jobs_service._run_import('imp-empty')

    assert batch['done'] is True
    assert batch['skipped'] == 1
    assert calls == []
