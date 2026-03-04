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
    def test_collects_marker_ack(self):
        cl_comment = MagicMock()
        cl_comment.id = 100

        ok = _make_comment(
            101,
            "OK",
            "alice",
            datetime(2026, 2, 15, 14, 30, tzinfo=timezone.utc),
        )
        ok.in_reply_to_id = 100
        pr = MagicMock()
        pr.get_review_comments.return_value = [ok]

        existing = {"api-review": cl_comment}
        details = _collect_acknowledgement_details(
            pr, existing, ["api-review"]
        )
        assert len(details["api-review"]) == 1
        assert details["api-review"][0]["reviewer"] == "alice"
        assert "2026-02-15" in details["api-review"][0]["acknowledged_at"]

    def test_no_acks(self):
        cl_comment = MagicMock()
        cl_comment.id = 100

        pr = MagicMock()
        pr.get_review_comments.return_value = []

        existing = {"api-review": cl_comment}
        details = _collect_acknowledgement_details(
            pr, existing, ["api-review"]
        )
        assert details["api-review"] == []

    def test_bare_ok_is_collected(self):
        """Bare OK is collected for evidence."""
        cl_comment = MagicMock()
        cl_comment.id = 100

        ok = _make_comment(
            101,
            "OK",
            "bob",
            datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc),
        )
        ok.in_reply_to_id = 100
        pr = MagicMock()
        pr.get_review_comments.return_value = [ok]

        existing = {"api-review": cl_comment}
        details = _collect_acknowledgement_details(
            pr, existing, ["api-review"]
        )
        assert len(details["api-review"]) == 1
        assert details["api-review"][0]["reviewer"] == "bob"

    def test_reply_to_different_comment_ignored(self):
        """A reply to a different comment is not collected."""
        cl_comment = MagicMock()
        cl_comment.id = 100

        ok = _make_comment(
            101,
            "OK",
            "alice",
            datetime(2026, 2, 15, 14, 30, tzinfo=timezone.utc),
        )
        ok.in_reply_to_id = 999  # different comment
        pr = MagicMock()
        pr.get_review_comments.return_value = [ok]

        existing = {"api-review": cl_comment}
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
        pr.get_review_comments.return_value = []
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

        cl_comment = MagicMock()
        cl_comment.id = 100

        ok_reply = _make_comment(
            101,
            "OK",
            "alice",
            datetime(2026, 2, 15, 14, 30, tzinfo=timezone.utc),
        )
        ok_reply.in_reply_to_id = 100
        pr.get_review_comments.return_value = [ok_reply]
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
            return_value={"api-review": cl_comment},
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


# ---------------------------------------------------------------------------
# _verify_all_acknowledged
# ---------------------------------------------------------------------------


class TestVerifyAllAcknowledged:
    def test_all_acknowledged(self):
        ack_details = {
            "api-review": [
                {"reviewer": "alice", "acknowledged_at": "2026-01-01T00:00:00"},
                {"reviewer": "bob", "acknowledged_at": "2026-01-01T00:01:00"},
            ],
        }
        missing = _verify_all_acknowledged(
            ack_details, ["alice", "bob"], ["api-review"]
        )
        assert missing == {}

    def test_missing_one_reviewer(self):
        ack_details = {
            "api-review": [
                {"reviewer": "alice", "acknowledged_at": "2026-01-01T00:00:00"},
            ],
        }
        missing = _verify_all_acknowledged(
            ack_details, ["alice", "bob"], ["api-review"]
        )
        assert missing == {"api-review": ["bob"]}

    def test_no_acks_at_all(self):
        ack_details = {"api-review": []}
        missing = _verify_all_acknowledged(
            ack_details, ["alice"], ["api-review"]
        )
        assert missing == {"api-review": ["alice"]}

    def test_empty_approvers_means_nothing_missing(self):
        ack_details = {"api-review": []}
        missing = _verify_all_acknowledged(
            ack_details, [], ["api-review"]
        )
        assert missing == {}


# ---------------------------------------------------------------------------
# main(strict=True)
# ---------------------------------------------------------------------------


class TestMergeEvidenceStrict:
    @patch("merge_evidence_commit.set_commit_status")
    @patch("merge_evidence_commit.get_approving_reviewers", return_value=[])
    @patch("merge_evidence_commit.load_checklists", return_value=SAMPLE_CHECKLISTS)
    @patch("merge_evidence_commit.get_repo_and_pr")
    @patch("merge_evidence_commit.get_github_client")
    def test_strict_no_approvers_exits_nonzero(
        self, mock_gh, mock_repo_pr, mock_load, mock_approvers, mock_status
    ):
        repo = MagicMock()
        pr = MagicMock()
        pr.head.sha = "abc"
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

        # No commit should have been created.
        repo.create_git_commit.assert_not_called()
        # Commit status should be set to failure.
        mock_status.assert_called_once_with(
            repo, "abc", "failure", "No approving reviewers"
        )

    @patch("merge_evidence_commit.set_commit_status")
    @patch(
        "merge_evidence_commit.get_approving_reviewers",
        return_value=["alice", "bob"],
    )
    @patch("merge_evidence_commit.load_checklists", return_value=SAMPLE_CHECKLISTS)
    @patch("merge_evidence_commit.get_repo_and_pr")
    @patch("merge_evidence_commit.get_github_client")
    def test_strict_missing_ack_exits_nonzero(
        self, mock_gh, mock_repo_pr, mock_load, mock_approvers, mock_status
    ):
        repo = MagicMock()
        pr = MagicMock()
        pr.head.sha = "abc"
        pr.get_files.return_value = [_make_file("src/api/foo.py")]

        cl_comment = MagicMock()
        cl_comment.id = 100

        # Only alice acked.
        ok_reply = _make_comment(
            101,
            "OK",
            "alice",
            datetime(2026, 2, 15, 14, 30, tzinfo=timezone.utc),
        )
        ok_reply.in_reply_to_id = 100
        pr.get_review_comments.return_value = [ok_reply]
        mock_repo_pr.return_value = (repo, pr)

        with patch(
            "merge_evidence_commit.find_existing_checklist_comments",
            return_value={"api-review": cl_comment},
        ):
            with pytest.raises(SystemExit) as exc_info:
                main(strict=True)
            assert exc_info.value.code == 1

        repo.create_git_commit.assert_not_called()
        mock_status.assert_called_once_with(
            repo, "abc", "failure", "api-review: awaiting bob"
        )

    @patch("merge_evidence_commit.set_commit_status")
    @patch(
        "merge_evidence_commit.get_approving_reviewers",
        return_value=["alice"],
    )
    @patch("merge_evidence_commit.load_checklists", return_value=SAMPLE_CHECKLISTS)
    @patch("merge_evidence_commit.get_repo_and_pr")
    @patch("merge_evidence_commit.get_github_client")
    def test_strict_all_acked_creates_commit(
        self, mock_gh, mock_repo_pr, mock_load, mock_approvers, mock_status
    ):
        repo = MagicMock()
        pr = MagicMock()
        pr.number = 42
        pr.title = "My PR"
        pr.html_url = "https://github.com/org/repo/pull/42"
        pr.base.ref = "main"
        pr.head.sha = "abc"
        pr.get_files.return_value = [_make_file("src/api/foo.py")]

        cl_comment = MagicMock()
        cl_comment.id = 100

        ok_reply = _make_comment(
            101,
            "OK",
            "alice",
            datetime(2026, 2, 15, 14, 30, tzinfo=timezone.utc),
        )
        ok_reply.in_reply_to_id = 100
        pr.get_review_comments.return_value = [ok_reply]
        mock_repo_pr.return_value = (repo, pr)

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
            return_value={"api-review": cl_comment},
        ):
            # Should NOT raise SystemExit.
            main(strict=True)

        repo.create_git_commit.assert_called_once()
        # Commit status should NOT be set to failure.
        mock_status.assert_not_called()

    @patch("merge_evidence_commit.set_commit_status")
    @patch("merge_evidence_commit.load_checklists", return_value=SAMPLE_CHECKLISTS)
    @patch("merge_evidence_commit.get_repo_and_pr")
    @patch("merge_evidence_commit.get_github_client")
    def test_strict_no_existing_comments_exits_nonzero(
        self, mock_gh, mock_repo_pr, mock_load, mock_status
    ):
        repo = MagicMock()
        pr = MagicMock()
        pr.head.sha = "abc"
        pr.get_files.return_value = [_make_file("src/api/foo.py")]
        mock_repo_pr.return_value = (repo, pr)

        with patch(
            "merge_evidence_commit.find_existing_checklist_comments",
            return_value={},
        ):
            with pytest.raises(SystemExit) as exc_info:
                main(strict=True)
            assert exc_info.value.code == 1

        mock_status.assert_called_once_with(
            repo, "abc", "failure", "Checklist findings not found"
        )

    @patch("merge_evidence_commit.set_commit_status")
    @patch("merge_evidence_commit.load_checklists", return_value=SAMPLE_CHECKLISTS)
    @patch("merge_evidence_commit.get_repo_and_pr")
    @patch("merge_evidence_commit.get_github_client")
    def test_evidence_commit_creation_failure_sets_status(
        self, mock_gh, mock_repo_pr, mock_load, mock_status
    ):
        repo = MagicMock()
        pr = MagicMock()
        pr.number = 42
        pr.title = "My PR"
        pr.html_url = "https://github.com/org/repo/pull/42"
        pr.base.ref = "main"
        pr.head.sha = "abc"
        pr.get_files.return_value = [_make_file("src/api/foo.py")]

        cl_comment = MagicMock()
        cl_comment.id = 100

        ok_reply = _make_comment(
            101,
            "OK",
            "alice",
            datetime(2026, 2, 15, 14, 30, tzinfo=timezone.utc),
        )
        ok_reply.in_reply_to_id = 100
        pr.get_review_comments.return_value = [ok_reply]
        mock_repo_pr.return_value = (repo, pr)

        # Simulate git API failure.
        repo.get_git_ref.side_effect = Exception("API error")

        with patch(
            "merge_evidence_commit.find_existing_checklist_comments",
            return_value={"api-review": cl_comment},
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

        repo.create_git_commit.assert_not_called()
        mock_status.assert_called_once_with(
            repo, "abc", "failure", "Evidence commit creation failed"
        )


# ---------------------------------------------------------------------------
# main(branch=...)
# ---------------------------------------------------------------------------


class TestMergeEvidenceBranch:
    @patch("merge_evidence_commit.load_checklists", return_value=SAMPLE_CHECKLISTS)
    @patch("merge_evidence_commit.get_repo_and_pr")
    @patch("merge_evidence_commit.get_github_client")
    def test_custom_branch_ref(self, mock_gh, mock_repo_pr, mock_load):
        repo = MagicMock()
        pr = MagicMock()
        pr.number = 42
        pr.title = "My PR"
        pr.html_url = "https://github.com/org/repo/pull/42"
        pr.base.ref = "main"
        pr.get_files.return_value = [_make_file("src/api/foo.py")]

        cl_comment = MagicMock()
        cl_comment.id = 100

        ok_reply = _make_comment(
            101,
            "OK",
            "alice",
            datetime(2026, 2, 15, 14, 30, tzinfo=timezone.utc),
        )
        ok_reply.in_reply_to_id = 100
        pr.get_review_comments.return_value = [ok_reply]
        mock_repo_pr.return_value = (repo, pr)

        ref = MagicMock()
        ref.object.sha = "headsha"
        repo.get_git_ref.return_value = ref

        head_commit = MagicMock()
        head_commit.tree = MagicMock()
        repo.get_git_commit.return_value = head_commit

        new_commit = MagicMock()
        new_commit.sha = "newcommitsha"
        repo.create_git_commit.return_value = new_commit

        custom_branch = "heads/gh-readonly-queue/main/pr-42-abc123"

        with patch(
            "merge_evidence_commit.find_existing_checklist_comments",
            return_value={"api-review": cl_comment},
        ):
            main(branch=custom_branch)

        # Should use the custom branch, not heads/main.
        repo.get_git_ref.assert_called_once_with(custom_branch)


