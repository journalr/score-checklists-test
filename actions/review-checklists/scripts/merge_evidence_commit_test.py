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

"""Tests for merge_evidence_commit.py."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from merge_evidence_commit import (
    _collect_acknowledgement_details,
    _verify_all_acknowledged,
    main,
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


SAMPLE_CHECKLISTS = [
    {
        "id": "api-review",
        "name": "API Review",
        "paths": ["src/api/*.py"],
        "checklist": "- [ ] Reviewed",
    },
]


# ---------------------------------------------------------------------------
# _collect_acknowledgement_details
# ---------------------------------------------------------------------------


class TestCollectAcknowledgementDetails:
    def test_collects_ok_ack(self):
        cl_comment = MagicMock()
        cl_comment.id = 100

        ok = _make_comment(
            101, "OK", "alice",
            datetime(2026, 2, 15, 14, 30, tzinfo=timezone.utc),
        )
        ok.in_reply_to_id = 100
        pr = MagicMock()
        pr.get_review_comments.return_value = [ok]

        details = _collect_acknowledgement_details(
            pr, {"api-review": cl_comment}, ["api-review"],
        )
        assert len(details["api-review"]) == 1
        assert details["api-review"][0]["reviewer"] == "alice"
        assert "2026-02-15" in details["api-review"][0]["acknowledged_at"]

    def test_no_acks(self):
        cl_comment = MagicMock()
        cl_comment.id = 100
        pr = MagicMock()
        pr.get_review_comments.return_value = []

        details = _collect_acknowledgement_details(
            pr, {"api-review": cl_comment}, ["api-review"],
        )
        assert details["api-review"] == []


# ---------------------------------------------------------------------------
# _verify_all_acknowledged
# ---------------------------------------------------------------------------


class TestVerifyAllAcknowledged:
    def test_all_acknowledged(self):
        ack_details = {
            "api-review": [
                {"reviewer": "alice", "acknowledged_at": "t"},
                {"reviewer": "bob", "acknowledged_at": "t"},
            ],
        }
        assert _verify_all_acknowledged(ack_details, ["alice", "bob"], ["api-review"]) == {}

    def test_missing_one_reviewer(self):
        ack_details = {
            "api-review": [{"reviewer": "alice", "acknowledged_at": "t"}],
        }
        missing = _verify_all_acknowledged(ack_details, ["alice", "bob"], ["api-review"])
        assert missing == {"api-review": ["bob"]}


# ---------------------------------------------------------------------------
# main(strict=True)
# ---------------------------------------------------------------------------


class TestMainStrict:
    @patch("merge_evidence_commit.update_pr_description_with_evidence")
    @patch("merge_evidence_commit.set_commit_status")
    @patch("merge_evidence_commit.get_approving_reviewers", return_value=[])
    @patch("merge_evidence_commit.load_checklists", return_value=SAMPLE_CHECKLISTS)
    @patch("merge_evidence_commit.get_repo_and_pr")
    @patch("merge_evidence_commit.get_github_client")
    def test_no_approvers_exits_nonzero(
        self, mock_gh, mock_repo_pr, mock_load, mock_approvers, mock_status,
        mock_update, monkeypatch,
    ):
        monkeypatch.delenv("HEAD_SHA", raising=False)
        repo = MagicMock()
        pr = MagicMock()
        pr.head.sha = "abc"
        pr.body = "PR body"
        pr.get_files.return_value = [_make_file("src/api/foo.py")]
        cl_comment = MagicMock()
        cl_comment.id = 100
        pr.get_review_comments.return_value = []
        mock_repo_pr.return_value = (repo, pr)

        with patch(
            "merge_evidence_commit.find_existing_checklist_comments",
            return_value={"api-review": cl_comment},
        ):
            with pytest.raises(SystemExit) as exc_info:
                main(strict=True)
            assert exc_info.value.code == 1

        mock_update.assert_called_once()
        mock_status.assert_called_once_with(
            repo, "abc", "failure", "No approving reviewers",
        )

    @patch("merge_evidence_commit.update_pr_description_with_evidence")
    @patch("merge_evidence_commit.set_commit_status")
    @patch("merge_evidence_commit.get_approving_reviewers", return_value=["alice"])
    @patch("merge_evidence_commit.load_checklists", return_value=SAMPLE_CHECKLISTS)
    @patch("merge_evidence_commit.get_repo_and_pr")
    @patch("merge_evidence_commit.get_github_client")
    def test_all_acked_success(
        self, mock_gh, mock_repo_pr, mock_load, mock_approvers, mock_status,
        mock_update, monkeypatch,
    ):
        monkeypatch.delenv("HEAD_SHA", raising=False)
        repo = MagicMock()
        pr = MagicMock()
        pr.head.sha = "abc"
        pr.body = "PR body"
        pr.get_files.return_value = [_make_file("src/api/foo.py")]
        cl_comment = MagicMock()
        cl_comment.id = 100
        ok_reply = _make_comment(101, "OK", "alice")
        ok_reply.in_reply_to_id = 100
        pr.get_review_comments.return_value = [ok_reply]
        mock_repo_pr.return_value = (repo, pr)

        with patch(
            "merge_evidence_commit.find_existing_checklist_comments",
            return_value={"api-review": cl_comment},
        ):
            main(strict=True)

        mock_update.assert_called_once()
        mock_status.assert_called_once_with(
            repo, "abc", "success", "All checklists verified — evidence updated",
        )

    @patch("merge_evidence_commit.update_pr_description_with_evidence")
    @patch("merge_evidence_commit.set_commit_status")
    @patch("merge_evidence_commit.load_checklists", return_value=SAMPLE_CHECKLISTS)
    @patch("merge_evidence_commit.get_repo_and_pr")
    @patch("merge_evidence_commit.get_github_client")
    def test_no_findings_exits_nonzero(
        self, mock_gh, mock_repo_pr, mock_load, mock_status,
        mock_update, monkeypatch,
    ):
        monkeypatch.delenv("HEAD_SHA", raising=False)
        repo = MagicMock()
        pr = MagicMock()
        pr.head.sha = "abc"
        pr.body = "PR body"
        pr.get_files.return_value = [_make_file("src/api/foo.py")]
        mock_repo_pr.return_value = (repo, pr)

        with patch(
            "merge_evidence_commit.find_existing_checklist_comments",
            return_value={},
        ):
            with pytest.raises(SystemExit) as exc_info:
                main(strict=True)
            assert exc_info.value.code == 1

        mock_update.assert_not_called()
        mock_status.assert_called_once_with(
            repo, "abc", "failure", "Checklist findings not found",
        )


# ---------------------------------------------------------------------------
# main() — no relevant checklists
# ---------------------------------------------------------------------------


class TestMainNoChecklists:
    @patch("merge_evidence_commit.set_commit_status")
    @patch("merge_evidence_commit.load_checklists", return_value=SAMPLE_CHECKLISTS)
    @patch("merge_evidence_commit.get_repo_and_pr")
    @patch("merge_evidence_commit.get_github_client")
    def test_no_relevant_checklists_sets_success(
        self, mock_gh, mock_repo_pr, mock_load, mock_status,
        capsys, monkeypatch,
    ):
        monkeypatch.delenv("HEAD_SHA", raising=False)
        repo = MagicMock()
        pr = MagicMock()
        pr.head.sha = "abc"
        pr.get_files.return_value = [_make_file("unrelated.txt")]
        mock_repo_pr.return_value = (repo, pr)

        main()

        mock_status.assert_called_once_with(
            repo, "abc", "success", "No checklists applicable",
        )

