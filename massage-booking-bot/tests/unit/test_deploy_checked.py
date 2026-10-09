"""No Render mutation is reachable unless the exact pushed commit passed Bot CI."""
import json
from unittest.mock import Mock
import pytest
from scripts import deploy_checked as deploy


@pytest.mark.parametrize('runs', [[],
    [{'headSha': 'abc', 'status': 'completed', 'conclusion': 'failure'}],
    [{'headSha': 'abc', 'status': 'in_progress', 'conclusion': ''}],
    [{'headSha': 'other', 'status': 'completed', 'conclusion': 'success'}],
])
def test_failed_pending_missing_or_wrong_revision_ci_blocks_deploy(monkeypatch, runs):
    monkeypatch.setattr(deploy, 'command', Mock(side_effect=[deploy.BRANCH, '', 'abc', 'abc refs/heads/x', json.dumps(runs)]))
    with pytest.raises(RuntimeError, match='Bot CI must succeed'):
        deploy.checked_revision()


def test_remote_head_must_match(monkeypatch):
    monkeypatch.setattr(deploy, 'command', Mock(side_effect=[deploy.BRANCH, '', 'abc', 'different refs/heads/x']))
    with pytest.raises(RuntimeError, match='pushed production'):
        deploy.checked_revision()


def test_success_returns_verified_revision(monkeypatch):
    runs = [{'headSha': 'abc', 'status': 'completed', 'conclusion': 'success', 'url': 'ci-url'}]
    monkeypatch.setattr(deploy, 'command', Mock(side_effect=[deploy.BRANCH, '', 'abc', 'abc refs/heads/x', json.dumps(runs)]))
    assert deploy.checked_revision() == ('abc', 'ci-url')
