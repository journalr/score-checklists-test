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

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
import sys

from dismiss_and_invalidate import (
    _find_ok_comments_for_checklist,
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
        "include": ["src/api/*.py"],
        "checklist": "- [ ] Reviewed",
    },
]


# ---------------------------------------------------------------------------
# _find_ok_comments_for_checklist
# ---------------------------------------------------------------------------


class TestFindOkCommentsForChecklist:
    def test_finds_marker_ok_reply(self):
        ok = _make_comment(
            101,
            "OK",
            "alice",
            datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        )
        ok.in_reply_to_id = 100
        pr = MagicMock()
        pr.get_review_comments.return_value = [ok]

        result = _find_ok_comments_for_checklist(pr, 100)
        assert len(result) == 1
        assert result[0].id == 101

    def test_finds_bare_ok_reply(self):
        ok = _make_comment(
            101,
            "OK",
            "alice",
            datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        )
        ok.in_reply_to_id = 100
        pr = MagicMock()
        pr.get_review_comments.return_value = [ok]

        result = _find_ok_comments_for_checklist(pr, 100)
        assert len(result) == 1

    def test_ignores_reply_to_different_comment(self):
        ok = _make_comment(
            101,
            "OK",
            "alice",
            datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        )
        ok.in_reply_to_id = 999  # different checklist
        pr = MagicMock()
        pr.get_review_comments.return_value = [ok]

        result = _find_ok_comments_for_checklist(pr, 100)
        assert len(result) == 0

    def test_ignores_unrelated_reply(self):
        normal = _make_comment(
            101,
            "looks good",
            "alice",
            datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        )
        normal.in_reply_to_id = 100
        pr = MagicMock()
        pr.get_review_comments.return_value = [normal]

        result = _find_ok_comments_for_checklist(pr, 100)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# handle_synchronize
# ---------------------------------------------------------------------------


class TestHandleSynchronize:
    @patch("dismiss_and_invalidate.ensure_merge_queue_notice_description")
    @patch("dismiss_and_invalidate.ensure_merge_queue_notice_comment")
    @patch("dismiss_and_invalidate.is_pr_in_merge_queue", return_value=False)
    @patch("dismiss_and_invalidate.set_commit_status")
    @patch("dismiss_and_invalidate.get_github_client")
    @patch("dismiss_and_invalidate.load_checklists", return_value=SAMPLE_CHECKLISTS)
    def test_no_affected_checklists(
        self,
        mock_load,
        mock_gh,
        mock_status,
        mock_in_queue,
        mock_notice_comment,
        mock_notice_description,
        monkeypatch,
    ):
        monkeypatch.delenv("BEFORE_SHA", raising=False)
        monkeypatch.delenv("AFTER_SHA", raising=False)

        pr = MagicMock()
        pr.get_files.return_value = [_make_file("unrelated.txt")]

        handle_synchronize(pr, ".github/review_checklists.yml")

        mock_status.assert_not_called()
        mock_notice_comment.assert_not_called()
        mock_notice_description.assert_not_called()

    @patch("dismiss_and_invalidate.ensure_merge_queue_notice_description")
    @patch("dismiss_and_invalidate.ensure_merge_queue_notice_comment")
    @patch("dismiss_and_invalidate.is_pr_in_merge_queue", return_value=True)
    @patch("dismiss_and_invalidate.set_commit_status")
    @patch("dismiss_and_invalidate.get_github_client")
    @patch("dismiss_and_invalidate.load_checklists", return_value=SAMPLE_CHECKLISTS)
    def test_deletes_ok_without_dismissing(
        self,
        mock_load,
        mock_gh,
        mock_status,
        mock_in_queue,
        mock_notice_comment,
        mock_notice_description,
        monkeypatch,
    ):
        monkeypatch.delenv("BEFORE_SHA", raising=False)
        monkeypatch.delenv("AFTER_SHA", raising=False)
        monkeypatch.setenv("GITHUB_REPOSITORY", "org/repo")

        pr = MagicMock()
        pr.head.sha = "newsha"
        pr.get_files.return_value = [_make_file("src/api/handler.py")]

        cl_comment = MagicMock()
        cl_comment.id = 100
        cl_comment.body = "<!-- review-checklist:api-review -->"

        ok_reply = _make_comment(
            101,
            "OK",
            "alice",
            datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        )
        ok_reply.in_reply_to_id = 100
        pr.get_review_comments.return_value = [ok_reply]

        review = _make_review("alice", "APPROVED", 42)
        pr.get_reviews.return_value = [review]

        with patch(
            "dismiss_and_invalidate.find_existing_checklist_comments",
            return_value={"api-review": cl_comment},
        ):
            handle_synchronize(pr, ".github/review_checklists.yml")

        ok_reply.delete.assert_called_once()
        review.dismiss.assert_not_called()
        mock_status.assert_called_once()
        mock_notice_comment.assert_called_once_with(pr)
        mock_notice_description.assert_called_once_with(pr)


if __name__ == "__main__":
    sys.exit(pytest.main(sys.argv[1:]))
