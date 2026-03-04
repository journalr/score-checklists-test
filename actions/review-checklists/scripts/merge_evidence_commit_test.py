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
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from merge_evidence_commit import (
    _build_evidence_message,
    _collect_acknowledgement_details,
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
    def test_collects_marker_ack(self):
        cl_review = MagicMock()
        cl_review.id = 100
        cl_review.body = "<!-- review-checklist:api-review -->"

        ok = _make_comment(
            101,
            "OK\n<!-- checklist-ok:api-review -->",
            "alice",
            datetime(2026, 2, 15, 14, 30, tzinfo=timezone.utc),
        )
        pr = MagicMock()
        pr.get_issue_comments.return_value = [ok]

        existing = {"api-review": cl_review}
        details = _collect_acknowledgement_details(
            pr, existing, ["api-review"]
        )
        assert len(details["api-review"]) == 1
        assert details["api-review"][0]["reviewer"] == "alice"
        assert "2026-02-15" in details["api-review"][0]["acknowledged_at"]

    def test_no_acks(self):
        cl_review = MagicMock()
        cl_review.id = 100
        cl_review.body = "<!-- review-checklist:api-review -->"

        pr = MagicMock()
        pr.get_issue_comments.return_value = []

        existing = {"api-review": cl_review}
        details = _collect_acknowledgement_details(
            pr, existing, ["api-review"]
        )
        assert details["api-review"] == []

    def test_bare_ok_without_marker_not_collected(self):
        """Bare OK without marker is not collected for evidence (must be tagged first)."""
        cl_review = MagicMock()
        cl_review.id = 100
        cl_review.body = "<!-- review-checklist:api-review -->"

        ok = _make_comment(
            101,
            "OK",
            "bob",
            datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc),
        )
        pr = MagicMock()
        pr.get_issue_comments.return_value = [ok]

        existing = {"api-review": cl_review}
        details = _collect_acknowledgement_details(
            pr, existing, ["api-review"]
        )
        assert details["api-review"] == []


# ---------------------------------------------------------------------------
# _build_evidence_message
# ---------------------------------------------------------------------------


class TestBuildEvidenceMessage:
    def test_contains_pr_info(self):
        pr = MagicMock()
        pr.number = 42
        pr.title = "Add new feature"
        pr.html_url = "https://github.com/org/repo/pull/42"

        msg = _build_evidence_message(pr, SAMPLE_CHECKLISTS, {"api-review": []})

        assert "PR #42" in msg
        assert "Add new feature" in msg
        assert "https://github.com/org/repo/pull/42" in msg

    def test_contains_checklist_details(self):
        pr = MagicMock()
        pr.number = 1
        pr.title = "t"
        pr.html_url = "u"

        msg = _build_evidence_message(pr, SAMPLE_CHECKLISTS, {"api-review": []})

        assert "API Review" in msg
        assert "api-review" in msg
        assert "Reviewed" in msg

    def test_contains_acknowledgement_info(self):
        pr = MagicMock()
        pr.number = 1
        pr.title = "t"
        pr.html_url = "u"

        ack_details = {
            "api-review": [
                {
                    "reviewer": "alice",
                    "acknowledged_at": "2026-02-15T14:30:00+00:00",
                }
            ]
        }
        msg = _build_evidence_message(pr, SAMPLE_CHECKLISTS, ack_details)

        assert "alice" in msg
        assert "2026-02-15" in msg

    def test_shows_none_when_no_acks(self):
        pr = MagicMock()
        pr.number = 1
        pr.title = "t"
        pr.html_url = "u"

        msg = _build_evidence_message(pr, SAMPLE_CHECKLISTS, {"api-review": []})
        assert "(none)" in msg


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


class TestMergeEvidenceMain:
    @patch("merge_evidence_commit.load_checklists", return_value=SAMPLE_CHECKLISTS)
    @patch("merge_evidence_commit.get_repo_and_pr")
    @patch("merge_evidence_commit.get_github_client")
    def test_no_relevant_checklists_skips(
        self, mock_gh, mock_repo_pr, mock_load, capsys
    ):
        repo = MagicMock()
        pr = MagicMock()
        pr.get_files.return_value = [_make_file("unrelated.txt")]
        mock_repo_pr.return_value = (repo, pr)

        main()

        out = capsys.readouterr().out
        assert "skipping evidence" in out.lower()

    @patch("merge_evidence_commit.load_checklists", return_value=SAMPLE_CHECKLISTS)
    @patch("merge_evidence_commit.get_repo_and_pr")
    @patch("merge_evidence_commit.get_github_client")
    def test_no_existing_comments_skips(
        self, mock_gh, mock_repo_pr, mock_load, capsys
    ):
        repo = MagicMock()
        pr = MagicMock()
        pr.get_files.return_value = [_make_file("src/api/foo.py")]
        pr.get_issue_comments.return_value = []
        mock_repo_pr.return_value = (repo, pr)

        with patch(
            "merge_evidence_commit.find_existing_checklist_comments",
            return_value={},
        ):
            main()

        out = capsys.readouterr().out
        assert "skipping evidence" in out.lower()

    @patch("merge_evidence_commit.load_checklists", return_value=SAMPLE_CHECKLISTS)
    @patch("merge_evidence_commit.get_repo_and_pr")
    @patch("merge_evidence_commit.get_github_client")
    def test_creates_evidence_commit(
        self, mock_gh, mock_repo_pr, mock_load
    ):
        repo = MagicMock()
        pr = MagicMock()
        pr.number = 42
        pr.title = "My PR"
        pr.html_url = "https://github.com/org/repo/pull/42"
        pr.base.ref = "main"
        pr.get_files.return_value = [_make_file("src/api/foo.py")]

        cl_review = MagicMock()
        cl_review.id = 100
        cl_review.body = "<!-- review-checklist:api-review -->"

        ok_comment = _make_comment(
            101,
            "OK\n<!-- checklist-ok:api-review -->",
            "alice",
            datetime(2026, 2, 15, 14, 30, tzinfo=timezone.utc),
        )
        pr.get_issue_comments.return_value = [ok_comment]
        mock_repo_pr.return_value = (repo, pr)

        # Set up git ref / commit mocks.
        ref = MagicMock()
        ref.object.sha = "headsha"
        repo.get_git_ref.return_value = ref

        head_commit = MagicMock()
        head_commit.tree = MagicMock()
        repo.get_git_commit.return_value = head_commit

        new_commit = MagicMock()
        new_commit.sha = "newcommitsha"
        repo.create_git_commit.return_value = new_commit

        with patch(
            "merge_evidence_commit.find_existing_checklist_comments",
            return_value={"api-review": cl_review},
        ):
            main()

        # Verify commit was created.
        repo.create_git_commit.assert_called_once()
        call_kwargs = repo.create_git_commit.call_args[1]
        assert "PR #42" in call_kwargs["message"]
        assert "alice" in call_kwargs["message"]
        assert call_kwargs["tree"] == head_commit.tree
        assert call_kwargs["parents"] == [head_commit]

        # Verify ref was updated.
        ref.edit.assert_called_once_with(sha="newcommitsha")

        # Verify the right branch was looked up.
        repo.get_git_ref.assert_called_once_with("heads/main")

