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

"""Tests for check_acknowledgements.py."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from check_acknowledgements import _collect_ok_acknowledgements, main


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


def _make_review(user_login, state):
    r = MagicMock()
    r.user.login = user_login
    r.state = state
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
# _collect_ok_acknowledgements
# ---------------------------------------------------------------------------


class TestCollectOkAcknowledgements:
    def test_ok_reply_recognized(self):
        """A reply with OK is recognized."""
        cl_comment = MagicMock(id=100)
        ok_reply = _make_comment(
            101,
            "OK",
            "alice",
            datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        )
        ok_reply.in_reply_to_id = 100
        pr = MagicMock()
        pr.get_review_comments.return_value = [ok_reply]

        existing = {"api-review": cl_comment}
        acks = _collect_ok_acknowledgements(pr, existing, ["api-review"])
        assert "alice" in acks["api-review"]

    def test_bare_ok_reply_recognized(self):
        """A bare 'OK' reply is recognized."""
        cl_comment = MagicMock(id=100)
        ok_reply = _make_comment(
            101,
            "OK",
            "bob",
            datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        )
        ok_reply.in_reply_to_id = 100
        pr = MagicMock()
        pr.get_review_comments.return_value = [ok_reply]

        existing = {"api-review": cl_comment}
        acks = _collect_ok_acknowledgements(pr, existing, ["api-review"])
        assert "bob" in acks["api-review"]

    def test_reply_to_different_comment_ignored(self):
        """A reply to a different comment is not counted."""
        cl_comment = MagicMock(id=100)
        ok_reply = _make_comment(
            101,
            "OK",
            "bob",
            datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        )
        ok_reply.in_reply_to_id = 999  # different comment
        pr = MagicMock()
        pr.get_review_comments.return_value = [ok_reply]

        existing = {"api-review": cl_comment}
        acks = _collect_ok_acknowledgements(pr, existing, ["api-review"])
        assert acks["api-review"] == set()

    def test_multiple_reviewers(self):
        """Two reviewers both replying OK are collected."""
        cl_comment = MagicMock(id=100)
        ok1 = _make_comment(
            101,
            "OK",
            "alice",
            datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        )
        ok1.in_reply_to_id = 100
        ok2 = _make_comment(
            102,
            "OK",
            "bob",
            datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc),
        )
        ok2.in_reply_to_id = 100
        pr = MagicMock()
        pr.get_review_comments.return_value = [ok1, ok2]

        existing = {"api-review": cl_comment}
        acks = _collect_ok_acknowledgements(pr, existing, ["api-review"])
        assert acks["api-review"] == {"alice", "bob"}

    def test_unrelated_reply_ignored(self):
        """A reply that is not OK is not counted."""
        cl_comment = MagicMock(id=100)
        normal = _make_comment(
            101,
            "Looks good to me!",
            "alice",
            datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        )
        normal.in_reply_to_id = 100
        pr = MagicMock()
        pr.get_review_comments.return_value = [normal]

        existing = {"api-review": cl_comment}
        acks = _collect_ok_acknowledgements(pr, existing, ["api-review"])
        assert acks["api-review"] == set()


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


class TestCheckAcknowledgementsMain:
    @patch("check_acknowledgements.set_commit_status")
    @patch(
        "check_acknowledgements.load_checklists",
        return_value=SAMPLE_CHECKLISTS,
    )
    @patch("check_acknowledgements.get_repo_and_pr")
    @patch("check_acknowledgements.get_github_client")
    def test_no_relevant_checklists_sets_success(
        self, mock_gh, mock_repo_pr, mock_load, mock_status
    ):
        repo = MagicMock()
        pr = MagicMock()
        pr.head.sha = "abc"
        pr.get_files.return_value = [_make_file("unrelated.txt")]
        mock_repo_pr.return_value = (repo, pr)

        main()

        mock_status.assert_called_once_with(
            repo, "abc", "success", "No checklists applicable"
        )

    @patch("check_acknowledgements.set_commit_status")
    @patch(
        "check_acknowledgements.find_existing_checklist_comments",
        return_value={},
    )
    @patch(
        "check_acknowledgements.load_checklists",
        return_value=SAMPLE_CHECKLISTS,
    )
    @patch("check_acknowledgements.get_repo_and_pr")
    @patch("check_acknowledgements.get_github_client")
    def test_no_existing_comments_sets_pending(
        self, mock_gh, mock_repo_pr, mock_load, mock_existing, mock_status
    ):
        repo = MagicMock()
        pr = MagicMock()
        pr.head.sha = "abc"
        pr.get_files.return_value = [_make_file("src/api/foo.py")]
        mock_repo_pr.return_value = (repo, pr)

        main()

        mock_status.assert_called_once_with(
            repo, "abc", "pending", "Checklist comments not yet posted"
        )

    @patch("check_acknowledgements.set_commit_status")
    @patch("check_acknowledgements.get_approving_reviewers", return_value=[])
    @patch(
        "check_acknowledgements.load_checklists",
        return_value=SAMPLE_CHECKLISTS,
    )
    @patch("check_acknowledgements.get_repo_and_pr")
    @patch("check_acknowledgements.get_github_client")
    def test_no_approvers_sets_pending(
        self, mock_gh, mock_repo_pr, mock_load, mock_approvers, mock_status
    ):
        repo = MagicMock()
        pr = MagicMock()
        pr.head.sha = "abc"
        pr.get_files.return_value = [_make_file("src/api/foo.py")]

        cl_review = MagicMock()
        cl_review.id = 100
        cl_review.body = "<!-- review-checklist:api-review -->"
        pr.get_review_comments.return_value = []
        mock_repo_pr.return_value = (repo, pr)

        with patch(
            "check_acknowledgements.find_existing_checklist_comments",
            return_value={"api-review": cl_review},
        ):
            main()

        mock_status.assert_called_with(
            repo, "abc", "pending", "Awaiting at least one approving review"
        )

    @patch("check_acknowledgements.set_commit_status")
    @patch(
        "check_acknowledgements.get_approving_reviewers",
        return_value=["alice"],
    )
    @patch(
        "check_acknowledgements.load_checklists",
        return_value=SAMPLE_CHECKLISTS,
    )
    @patch("check_acknowledgements.get_repo_and_pr")
    @patch("check_acknowledgements.get_github_client")
    def test_all_acked_sets_success(
        self, mock_gh, mock_repo_pr, mock_load, mock_approvers, mock_status,
        tmp_path,
    ):
        repo = MagicMock()
        pr = MagicMock()
        pr.head.sha = "abc"
        pr.get_files.return_value = [_make_file("src/api/foo.py")]

        cl_review = MagicMock()
        cl_review.id = 100
        cl_review.body = "<!-- review-checklist:api-review -->"

        ok_reply = _make_comment(
            101,
            "OK",
            "alice",
            datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        )
        ok_reply.in_reply_to_id = 100
        pr.get_review_comments.return_value = [ok_reply]
        mock_repo_pr.return_value = (repo, pr)

        ack_path = str(tmp_path / "acks.json")

        with patch(
            "check_acknowledgements.find_existing_checklist_comments",
            return_value={"api-review": cl_review},
        ), patch.dict(os.environ, {"ACK_OUTPUT_PATH": ack_path}):
            main()

        # The last call should be success.
        mock_status.assert_called_with(
            repo,
            "abc",
            "success",
            "All checklists acknowledged by all approving reviewers",
        )
        # Check that ack data was written.
        with open(ack_path) as f:
            data = json.load(f)
        assert data["api-review"] == ["alice"]

    @patch("check_acknowledgements.set_commit_status")
    @patch(
        "check_acknowledgements.get_approving_reviewers",
        return_value=["alice", "bob"],
    )
    @patch(
        "check_acknowledgements.load_checklists",
        return_value=SAMPLE_CHECKLISTS,
    )
    @patch("check_acknowledgements.get_repo_and_pr")
    @patch("check_acknowledgements.get_github_client")
    def test_missing_ack_sets_pending(
        self, mock_gh, mock_repo_pr, mock_load, mock_approvers, mock_status,
        tmp_path,
    ):
        repo = MagicMock()
        pr = MagicMock()
        pr.head.sha = "abc"
        pr.get_files.return_value = [_make_file("src/api/foo.py")]

        cl_review = MagicMock()
        cl_review.id = 100
        cl_review.body = "<!-- review-checklist:api-review -->"

        # Only alice acked, bob did not.
        ok_reply = _make_comment(
            101,
            "OK",
            "alice",
            datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        )
        ok_reply.in_reply_to_id = 100
        pr.get_review_comments.return_value = [ok_reply]
        mock_repo_pr.return_value = (repo, pr)

        ack_path = str(tmp_path / "acks.json")

        with patch(
            "check_acknowledgements.find_existing_checklist_comments",
            return_value={"api-review": cl_review},
        ), patch.dict(os.environ, {"ACK_OUTPUT_PATH": ack_path}):
            main()

        mock_status.assert_called_with(
            repo, "abc", "pending", "api-review: awaiting bob"
        )


# ---------------------------------------------------------------------------
# main(strict=True)
# ---------------------------------------------------------------------------


class TestCheckAcknowledgementsStrict:
    @patch("check_acknowledgements.set_commit_status")
    @patch(
        "check_acknowledgements.get_approving_reviewers",
        return_value=["alice", "bob"],
    )
    @patch(
        "check_acknowledgements.load_checklists",
        return_value=SAMPLE_CHECKLISTS,
    )
    @patch("check_acknowledgements.get_repo_and_pr")
    @patch("check_acknowledgements.get_github_client")
    def test_strict_missing_ack_exits_nonzero(
        self, mock_gh, mock_repo_pr, mock_load, mock_approvers, mock_status,
        tmp_path,
    ):
        repo = MagicMock()
        pr = MagicMock()
        pr.head.sha = "abc"
        pr.get_files.return_value = [_make_file("src/api/foo.py")]

        cl_review = MagicMock()
        cl_review.id = 100
        cl_review.body = "<!-- review-checklist:api-review -->"

        # Only alice acked, bob did not.
        ok_reply = _make_comment(
            101,
            "OK",
            "alice",
            datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        )
        ok_reply.in_reply_to_id = 100
        pr.get_review_comments.return_value = [ok_reply]
        mock_repo_pr.return_value = (repo, pr)

        ack_path = str(tmp_path / "acks.json")

        with patch(
            "check_acknowledgements.find_existing_checklist_comments",
            return_value={"api-review": cl_review},
        ), patch.dict(os.environ, {"ACK_OUTPUT_PATH": ack_path}):
            with pytest.raises(SystemExit) as exc_info:
                main(strict=True)
            assert exc_info.value.code == 1

    @patch("check_acknowledgements.set_commit_status")
    @patch("check_acknowledgements.get_approving_reviewers", return_value=[])
    @patch(
        "check_acknowledgements.load_checklists",
        return_value=SAMPLE_CHECKLISTS,
    )
    @patch("check_acknowledgements.get_repo_and_pr")
    @patch("check_acknowledgements.get_github_client")
    def test_strict_no_approvers_exits_nonzero(
        self, mock_gh, mock_repo_pr, mock_load, mock_approvers, mock_status
    ):
        repo = MagicMock()
        pr = MagicMock()
        pr.head.sha = "abc"
        pr.get_files.return_value = [_make_file("src/api/foo.py")]

        cl_review = MagicMock()
        cl_review.id = 100
        cl_review.body = "<!-- review-checklist:api-review -->"
        pr.get_review_comments.return_value = []
        mock_repo_pr.return_value = (repo, pr)

        with patch(
            "check_acknowledgements.find_existing_checklist_comments",
            return_value={"api-review": cl_review},
        ):
            with pytest.raises(SystemExit) as exc_info:
                main(strict=True)
            assert exc_info.value.code == 1

    @patch("check_acknowledgements.set_commit_status")
    @patch(
        "check_acknowledgements.get_approving_reviewers",
        return_value=["alice"],
    )
    @patch(
        "check_acknowledgements.load_checklists",
        return_value=SAMPLE_CHECKLISTS,
    )
    @patch("check_acknowledgements.get_repo_and_pr")
    @patch("check_acknowledgements.get_github_client")
    def test_strict_all_acked_succeeds(
        self, mock_gh, mock_repo_pr, mock_load, mock_approvers, mock_status,
        tmp_path,
    ):
        repo = MagicMock()
        pr = MagicMock()
        pr.head.sha = "abc"
        pr.get_files.return_value = [_make_file("src/api/foo.py")]

        cl_review = MagicMock()
        cl_review.id = 100
        cl_review.body = "<!-- review-checklist:api-review -->"

        ok_reply = _make_comment(
            101,
            "OK",
            "alice",
            datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        )
        ok_reply.in_reply_to_id = 100
        pr.get_review_comments.return_value = [ok_reply]
        mock_repo_pr.return_value = (repo, pr)

        ack_path = str(tmp_path / "acks.json")

        with patch(
            "check_acknowledgements.find_existing_checklist_comments",
            return_value={"api-review": cl_review},
        ), patch.dict(os.environ, {"ACK_OUTPUT_PATH": ack_path}):
            # Should NOT raise SystemExit.
            main(strict=True)

        mock_status.assert_called_with(
            repo,
            "abc",
            "success",
            "All checklists acknowledged by all approving reviewers",
        )

    @patch("check_acknowledgements.set_commit_status")
    @patch(
        "check_acknowledgements.find_existing_checklist_comments",
        return_value={},
    )
    @patch(
        "check_acknowledgements.load_checklists",
        return_value=SAMPLE_CHECKLISTS,
    )
    @patch("check_acknowledgements.get_repo_and_pr")
    @patch("check_acknowledgements.get_github_client")
    def test_strict_no_existing_comments_exits_nonzero(
        self, mock_gh, mock_repo_pr, mock_load, mock_existing, mock_status
    ):
        repo = MagicMock()
        pr = MagicMock()
        pr.head.sha = "abc"
        pr.get_files.return_value = [_make_file("src/api/foo.py")]
        mock_repo_pr.return_value = (repo, pr)

        with pytest.raises(SystemExit) as exc_info:
            main(strict=True)
        assert exc_info.value.code == 1


