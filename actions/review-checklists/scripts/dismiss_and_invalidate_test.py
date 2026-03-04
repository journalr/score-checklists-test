# *******************************************************************************
# Copyright (c) 2026 Contributors to the Eclipse Foundation
#
# See the NOTICE file(s) distributed with this work for additional
# information regarding copyright ownership.
#
# This program and the accompanying materials are made available under the
# terms of the Apache License Version 2.0 which is available at
# https://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0
# *******************************************************************************

"""Tests for dismiss_and_invalidate.py."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from dismiss_and_invalidate import (
    _dismiss_approval,
    _find_ok_comments_for_checklist,
    handle_comment_changed,
    handle_synchronize,
)


def _make_comment(comment_id, body, user_login="reviewer", created_at=None):
    c = MagicMock()
    c.id = comment_id
    c.body = body
    c.user.login = user_login
    c.created_at = created_at or datetime(2026, 1, 1, tzinfo=timezone.utc)
    return c


def _make_file(filename):
    f = MagicMock()
    f.filename = filename
    return f


def _make_review(user_login, state, review_id=1):
    r = MagicMock()
    r.user.login = user_login
    r.state = state
    r.id = review_id
    return r


SAMPLE_CHECKLISTS = [
    {
        "id": "api-review",
        "name": "API Review",
        "paths": ["src/api/*.py"],
        "checklist": "- [ ] Reviewed",
    },
]


# ---------------------------------------------------------------------------
# _find_ok_comments_for_checklist
# ---------------------------------------------------------------------------


class TestFindOkCommentsForChecklist:
    def test_finds_marker_ok(self):
        ok = _make_comment(
            101,
            "OK\n<!-- checklist-ok:api-review -->",
            "alice",
            datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        )
        pr = MagicMock()
        pr.get_issue_comments.return_value = [ok]

        result = _find_ok_comments_for_checklist(pr, "api-review", 100)
        assert len(result) == 1
        assert result[0].id == 101

    def test_finds_bare_ok(self):
        ok = _make_comment(
            101,
            "OK",
            "alice",
            datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        )
        pr = MagicMock()
        pr.get_issue_comments.return_value = [ok]

        result = _find_ok_comments_for_checklist(pr, "api-review", 100)
        assert len(result) == 1

    def test_ignores_ok_for_different_checklist(self):
        ok = _make_comment(
            101,
            "OK\n<!-- checklist-ok:other-review -->",
            "alice",
            datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        )
        pr = MagicMock()
        pr.get_issue_comments.return_value = [ok]

        result = _find_ok_comments_for_checklist(pr, "api-review", 100)
        assert len(result) == 0

    def test_ignores_unrelated_comment(self):
        normal = _make_comment(
            101,
            "looks good",
            "alice",
            datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        )
        pr = MagicMock()
        pr.get_issue_comments.return_value = [normal]

        result = _find_ok_comments_for_checklist(pr, "api-review", 100)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# _dismiss_approval
# ---------------------------------------------------------------------------


class TestDismissApproval:
    def test_dismisses_approved_review(self):
        review = _make_review("alice", "APPROVED", review_id=42)
        pr = MagicMock()
        pr.get_reviews.return_value = [review]

        _dismiss_approval(pr, "alice")

        review.dismiss.assert_called_once()

    def test_no_approval_to_dismiss(self, capsys):
        pr = MagicMock()
        pr.get_reviews.return_value = []

        _dismiss_approval(pr, "alice")

        out = capsys.readouterr().out
        assert "No active approval found" in out

    def test_only_dismisses_latest_approval(self):
        old = _make_review("alice", "APPROVED", review_id=1)
        new = _make_review("alice", "APPROVED", review_id=2)
        pr = MagicMock()
        pr.get_reviews.return_value = [old, new]

        _dismiss_approval(pr, "alice")

        new.dismiss.assert_called_once()
        old.dismiss.assert_not_called()

    def test_skips_non_approved(self):
        r = _make_review("alice", "CHANGES_REQUESTED", review_id=1)
        pr = MagicMock()
        pr.get_reviews.return_value = [r]

        _dismiss_approval(pr, "alice")

        r.dismiss.assert_not_called()


# ---------------------------------------------------------------------------
# handle_synchronize
# ---------------------------------------------------------------------------


class TestHandleSynchronize:
    @patch("dismiss_and_invalidate.set_commit_status")
    @patch("dismiss_and_invalidate.get_github_client")
    @patch("dismiss_and_invalidate.load_checklists", return_value=SAMPLE_CHECKLISTS)
    def test_no_affected_checklists(self, mock_load, mock_gh, mock_status, monkeypatch):
        monkeypatch.delenv("BEFORE_SHA", raising=False)
        monkeypatch.delenv("AFTER_SHA", raising=False)

        pr = MagicMock()
        pr.get_files.return_value = [_make_file("unrelated.txt")]

        handle_synchronize(pr)

        mock_status.assert_not_called()

    @patch("dismiss_and_invalidate.set_commit_status")
    @patch("dismiss_and_invalidate.get_github_client")
    @patch("dismiss_and_invalidate.load_checklists", return_value=SAMPLE_CHECKLISTS)
    def test_deletes_ok_and_dismisses(self, mock_load, mock_gh, mock_status, monkeypatch):
        monkeypatch.delenv("BEFORE_SHA", raising=False)
        monkeypatch.delenv("AFTER_SHA", raising=False)
        monkeypatch.setenv("GITHUB_REPOSITORY", "org/repo")

        pr = MagicMock()
        pr.head.sha = "newsha"
        pr.get_files.return_value = [_make_file("src/api/handler.py")]

        cl_review = MagicMock()
        cl_review.id = 100
        cl_review.body = "<!-- review-checklist:api-review -->"

        ok_comment = _make_comment(
            101,
            "OK\n<!-- checklist-ok:api-review -->",
            "alice",
            datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        )
        pr.get_issue_comments.return_value = [ok_comment]

        review = _make_review("alice", "APPROVED", 42)
        pr.get_reviews.return_value = [review]

        with patch(
            "dismiss_and_invalidate.find_existing_checklist_comments",
            return_value={"api-review": cl_review},
        ):
            handle_synchronize(pr)

        ok_comment.delete.assert_called_once()
        review.dismiss.assert_called_once()


# ---------------------------------------------------------------------------
# handle_comment_changed
# ---------------------------------------------------------------------------


class TestHandleCommentChanged:
    def test_no_event_path(self, capsys):
        pr = MagicMock()
        with patch.dict(os.environ, {"GITHUB_EVENT_PATH": ""}):
            handle_comment_changed(pr)
        assert "No event payload" in capsys.readouterr().out

    @patch("dismiss_and_invalidate.set_commit_status")
    @patch("dismiss_and_invalidate.get_github_client")
    def test_deleted_ok_dismisses_approval(
        self, mock_gh, mock_status, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("GITHUB_REPOSITORY", "org/repo")

        event = {
            "action": "deleted",
            "comment": {
                "body": "OK",
                "user": {"login": "alice"},
            },
        }
        event_file = tmp_path / "event.json"
        event_file.write_text(json.dumps(event))

        pr = MagicMock()
        pr.head.sha = "sha123"
        review = _make_review("alice", "APPROVED", 10)
        pr.get_reviews.return_value = [review]

        with patch.dict(
            os.environ, {"GITHUB_EVENT_PATH": str(event_file)}
        ):
            handle_comment_changed(pr)

        review.dismiss.assert_called_once()

    @patch("dismiss_and_invalidate.set_commit_status")
    @patch("dismiss_and_invalidate.get_github_client")
    def test_edited_ok_retraction_dismisses(
        self, mock_gh, mock_status, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("GITHUB_REPOSITORY", "org/repo")

        event = {
            "action": "edited",
            "comment": {
                "body": "never mind",
                "user": {"login": "bob"},
            },
            "changes": {
                "body": {"from": "OK"},
            },
        }
        event_file = tmp_path / "event.json"
        event_file.write_text(json.dumps(event))

        pr = MagicMock()
        pr.head.sha = "sha456"
        review = _make_review("bob", "APPROVED", 20)
        pr.get_reviews.return_value = [review]

        with patch.dict(
            os.environ, {"GITHUB_EVENT_PATH": str(event_file)}
        ):
            handle_comment_changed(pr)

        review.dismiss.assert_called_once()

    @patch("dismiss_and_invalidate.set_commit_status")
    @patch("dismiss_and_invalidate.get_github_client")
    def test_edited_non_ok_does_not_dismiss(
        self, mock_gh, mock_status, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("GITHUB_REPOSITORY", "org/repo")

        event = {
            "action": "edited",
            "comment": {
                "body": "updated comment",
                "user": {"login": "bob"},
            },
            "changes": {
                "body": {"from": "original non-ok comment"},
            },
        }
        event_file = tmp_path / "event.json"
        event_file.write_text(json.dumps(event))

        pr = MagicMock()
        pr.head.sha = "sha789"
        pr.get_reviews.return_value = []

        with patch.dict(
            os.environ, {"GITHUB_EVENT_PATH": str(event_file)}
        ):
            handle_comment_changed(pr)

        mock_status.assert_not_called()

    def test_deleted_non_ok_does_not_dismiss(self, tmp_path):
        event = {
            "action": "deleted",
            "comment": {
                "body": "just a regular comment",
                "user": {"login": "bob"},
            },
        }
        event_file = tmp_path / "event.json"
        event_file.write_text(json.dumps(event))

        pr = MagicMock()
        pr.get_reviews.return_value = []

        with patch.dict(
            os.environ, {"GITHUB_EVENT_PATH": str(event_file)}
        ):
            handle_comment_changed(pr)

        # No dismiss should have been called (no reviews to dismiss anyway).
        # The key assertion is that no exception was raised.

