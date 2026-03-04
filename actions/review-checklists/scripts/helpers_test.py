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

"""Tests for helpers.py."""

from __future__ import annotations

import os
import textwrap
from unittest.mock import MagicMock, patch

import pytest
import yaml

from helpers import (
    CHECKLIST_MARKER,
    OK_KEYWORD,
    OK_MARKER,
    check_merge_queue_protection,
    find_existing_checklist_comments,
    find_ok_replies,
    get_approving_reviewers,
    get_changed_files,
    get_github_client,
    get_repo_and_pr,
    load_checklists,
    make_checklist_comment_body,
    match_checklists,
    set_check_run,
    set_commit_status,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_CHECKLISTS = [
    {
        "id": "api-review",
        "name": "API Review",
        "paths": ["src/api/*.py", "src/api/*.h"],
        "checklist": "- [ ] APIs documented\n- [ ] Tests added",
    },
    {
        "id": "docs-review",
        "name": "Documentation Review",
        "paths": ["docs/**"],
        "checklist": "- [ ] Spelling checked",
    },
    {
        "id": "build-review",
        "name": "Build Review",
        "paths": ["**/BUILD", "**/*.bzl"],
        "checklist": "- [ ] Targets correct",
    },
]


@pytest.fixture()
def sample_config(tmp_path):
    """Write a sample checklists.yml and return its path."""
    cfg = tmp_path / "checklists.yml"
    cfg.write_text(yaml.dump({"checklists": SAMPLE_CHECKLISTS}))
    return str(cfg)


def _make_comment(comment_id, body, user_login="bot", created_at=None):
    """Build a lightweight mock issue-comment."""
    from datetime import datetime, timezone

    c = MagicMock()
    c.id = comment_id
    c.body = body
    c.user.login = user_login
    c.created_at = created_at or datetime(2026, 1, 1, tzinfo=timezone.utc)
    return c


def _make_review(user_login, state, review_id=1, body=None):
    r = MagicMock()
    r.user.login = user_login
    r.state = state
    r.id = review_id
    r.body = body or ""
    return r


# ---------------------------------------------------------------------------
# get_github_client / get_repo_and_pr
# ---------------------------------------------------------------------------


class TestGetGithubClient:
    def test_reads_token_from_env(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test123")
        with patch("helpers.Github") as mock_cls:
            get_github_client()
            mock_cls.assert_called_once_with("ghp_test123")

    def test_missing_token_raises(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with pytest.raises(KeyError):
            get_github_client()


class TestGetRepoAndPr:
    def test_returns_repo_and_pr(self, monkeypatch):
        monkeypatch.setenv("GITHUB_REPOSITORY", "org/repo")
        monkeypatch.setenv("PR_NUMBER", "42")
        gh = MagicMock()
        repo, pr = get_repo_and_pr(gh)
        gh.get_repo.assert_called_once_with("org/repo")
        gh.get_repo.return_value.get_pull.assert_called_once_with(42)


# ---------------------------------------------------------------------------
# load_checklists
# ---------------------------------------------------------------------------


class TestLoadChecklists:
    def test_load_from_explicit_path(self, sample_config):
        result = load_checklists(config_path=sample_config)
        assert len(result) == 3
        assert result[0]["id"] == "api-review"

    def test_load_via_env_override(self, sample_config, monkeypatch):
        monkeypatch.setenv("CHECKLISTS_CONFIG", sample_config)
        result = load_checklists()
        assert len(result) == 3

    def test_file_not_found_raises(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CHECKLISTS_CONFIG", "")
        monkeypatch.delenv("RUNFILES_DIR", raising=False)
        monkeypatch.delenv("RUNFILES_MANIFEST_FILE", raising=False)
        # Patch _find_checklists_config to raise directly so we don't depend
        # on file-system layout during tests.
        with patch(
            "helpers._find_checklists_config",
            side_effect=FileNotFoundError("Cannot locate checklists.yml"),
        ):
            with pytest.raises(FileNotFoundError):
                load_checklists()


# ---------------------------------------------------------------------------
# get_changed_files
# ---------------------------------------------------------------------------


class TestGetChangedFiles:
    def test_returns_filenames(self):
        file1 = MagicMock()
        file1.filename = "src/api/foo.py"
        file2 = MagicMock()
        file2.filename = "docs/readme.md"
        pr = MagicMock()
        pr.get_files.return_value = [file1, file2]
        assert get_changed_files(pr) == ["src/api/foo.py", "docs/readme.md"]


# ---------------------------------------------------------------------------
# match_checklists
# ---------------------------------------------------------------------------


class TestMatchChecklists:
    def test_single_match(self):
        files = ["src/api/handler.py"]
        result = match_checklists(SAMPLE_CHECKLISTS, files)
        assert len(result) == 1
        assert result[0]["id"] == "api-review"
        assert result[0]["matched_files"] == ["src/api/handler.py"]

    def test_multiple_matches(self):
        files = ["src/api/handler.py", "docs/guide.md"]
        result = match_checklists(SAMPLE_CHECKLISTS, files)
        ids = {r["id"] for r in result}
        assert ids == {"api-review", "docs-review"}

    def test_no_match(self):
        files = ["unrelated/file.txt"]
        result = match_checklists(SAMPLE_CHECKLISTS, files)
        assert result == []

    def test_glob_double_star(self):
        files = ["docs/nested/deep/file.md"]
        result = match_checklists(SAMPLE_CHECKLISTS, files)
        assert len(result) == 1
        assert result[0]["id"] == "docs-review"

    def test_build_glob(self):
        files = ["some/path/BUILD"]
        result = match_checklists(SAMPLE_CHECKLISTS, files)
        assert len(result) == 1
        assert result[0]["id"] == "build-review"

    def test_multiple_files_same_checklist(self):
        files = ["src/api/a.py", "src/api/b.h"]
        result = match_checklists(SAMPLE_CHECKLISTS, files)
        assert len(result) == 1
        assert set(result[0]["matched_files"]) == {
            "src/api/a.py",
            "src/api/b.h",
        }

    def test_does_not_mutate_input(self):
        files = ["src/api/handler.py"]
        original_len = len(SAMPLE_CHECKLISTS[0])
        match_checklists(SAMPLE_CHECKLISTS, files)
        # The original dict should not have gained a 'matched_files' key.
        assert len(SAMPLE_CHECKLISTS[0]) == original_len


# ---------------------------------------------------------------------------
# make_checklist_comment_body
# ---------------------------------------------------------------------------


class TestMakeChecklistCommentBody:
    def test_contains_marker(self):
        cl = SAMPLE_CHECKLISTS[0]
        body = make_checklist_comment_body(cl)
        expected_marker = CHECKLIST_MARKER.format(checklist_id="api-review")
        assert expected_marker in body

    def test_contains_name(self):
        cl = SAMPLE_CHECKLISTS[0]
        body = make_checklist_comment_body(cl)
        assert cl["name"] in body

    def test_contains_checklist_content(self):
        cl = SAMPLE_CHECKLISTS[0]
        body = make_checklist_comment_body(cl)
        assert "APIs documented" in body

    def test_contains_ok_instruction(self):
        cl = SAMPLE_CHECKLISTS[0]
        body = make_checklist_comment_body(cl)
        assert OK_KEYWORD in body

    def test_contains_paths(self):
        cl = SAMPLE_CHECKLISTS[0]
        body = make_checklist_comment_body(cl)
        for p in cl["paths"]:
            assert p in body


# ---------------------------------------------------------------------------
# find_existing_checklist_comments
# ---------------------------------------------------------------------------


class TestFindExistingChecklistComments:
    def test_finds_checklist_review_comments(self):
        c1 = _make_comment(
            1, "<!-- review-checklist:api-review --> body here"
        )
        c1.in_reply_to_id = None
        c2 = _make_comment(2, "just a normal comment")
        c2.in_reply_to_id = None
        c3 = _make_comment(
            3, "<!-- review-checklist:docs-review --> docs body"
        )
        c3.in_reply_to_id = None
        pr = MagicMock()
        pr.get_review_comments.return_value = [c1, c2, c3]

        result = find_existing_checklist_comments(pr)
        assert set(result.keys()) == {"api-review", "docs-review"}
        assert result["api-review"].id == 1
        assert result["docs-review"].id == 3

    def test_ignores_reply_comments(self):
        """A reply to a checklist comment should not be treated as a checklist."""
        c1 = _make_comment(
            1, "<!-- review-checklist:api-review --> body"
        )
        c1.in_reply_to_id = None
        c2 = _make_comment(
            2, "<!-- review-checklist:api-review --> reply copy"
        )
        c2.in_reply_to_id = 1  # this is a reply
        pr = MagicMock()
        pr.get_review_comments.return_value = [c1, c2]

        result = find_existing_checklist_comments(pr)
        assert len(result) == 1
        assert result["api-review"].id == 1

    def test_returns_empty_when_none(self):
        pr = MagicMock()
        c1 = _make_comment(1, "nothing here")
        c1.in_reply_to_id = None
        pr.get_review_comments.return_value = [c1]
        assert find_existing_checklist_comments(pr) == {}


# ---------------------------------------------------------------------------
# find_ok_replies
# ---------------------------------------------------------------------------


class TestFindOkReplies:
    def test_finds_marker_based_ok(self):
        marker = OK_MARKER.format(checklist_id="api-review")
        c1 = _make_comment(10, "checklist body", "bot")
        c1.in_reply_to_id = None
        c2 = _make_comment(11, f"OK\n{marker}", "reviewer1")
        c2.in_reply_to_id = 10
        pr = MagicMock()
        pr.get_review_comments.return_value = [c1, c2]

        result = find_ok_replies(pr, 10, "api-review")
        assert len(result) == 1
        assert result[0].id == 11

    def test_finds_bare_ok(self):
        c1 = _make_comment(10, "checklist body", "bot")
        c1.in_reply_to_id = None
        c2 = _make_comment(11, "OK", "reviewer1")
        c2.in_reply_to_id = 10
        pr = MagicMock()
        pr.get_review_comments.return_value = [c1, c2]

        result = find_ok_replies(pr, 10, "api-review")
        assert len(result) == 1

    def test_ignores_reply_to_different_comment(self):
        c1 = _make_comment(11, "OK", "reviewer1")
        c1.in_reply_to_id = 99  # different checklist
        pr = MagicMock()
        pr.get_review_comments.return_value = [c1]

        result = find_ok_replies(pr, 10, "api-review")
        assert len(result) == 0

    def test_ignores_unrelated_reply(self):
        c1 = _make_comment(11, "looks good but not OK keyword", "reviewer1")
        c1.in_reply_to_id = 10
        pr = MagicMock()
        pr.get_review_comments.return_value = [c1]

        result = find_ok_replies(pr, 10, "api-review")
        assert len(result) == 0


# ---------------------------------------------------------------------------
# get_approving_reviewers
# ---------------------------------------------------------------------------


class TestGetApprovingReviewers:
    def test_single_approver(self):
        pr = MagicMock()
        pr.get_reviews.return_value = [_make_review("alice", "APPROVED")]
        assert get_approving_reviewers(pr) == ["alice"]

    def test_dismissed_not_counted(self):
        pr = MagicMock()
        pr.get_reviews.return_value = [
            _make_review("alice", "APPROVED"),
            _make_review("alice", "DISMISSED"),
        ]
        assert get_approving_reviewers(pr) == []

    def test_changes_requested_overrides(self):
        pr = MagicMock()
        pr.get_reviews.return_value = [
            _make_review("alice", "APPROVED"),
            _make_review("alice", "CHANGES_REQUESTED"),
        ]
        assert get_approving_reviewers(pr) == []

    def test_re_approval_after_changes_requested(self):
        pr = MagicMock()
        pr.get_reviews.return_value = [
            _make_review("alice", "APPROVED"),
            _make_review("alice", "CHANGES_REQUESTED"),
            _make_review("alice", "APPROVED"),
        ]
        assert get_approving_reviewers(pr) == ["alice"]

    def test_multiple_approvers_sorted(self):
        pr = MagicMock()
        pr.get_reviews.return_value = [
            _make_review("charlie", "APPROVED"),
            _make_review("alice", "APPROVED"),
        ]
        assert get_approving_reviewers(pr) == ["alice", "charlie"]

    def test_no_reviews(self):
        pr = MagicMock()
        pr.get_reviews.return_value = []
        assert get_approving_reviewers(pr) == []


# ---------------------------------------------------------------------------
# set_commit_status
# ---------------------------------------------------------------------------


class TestSetCommitStatus:
    def test_creates_status(self):
        repo = MagicMock()
        set_commit_status(repo, "abc123", "success", "All good")
        commit = repo.get_commit.return_value
        commit.create_status.assert_called_once_with(
            state="success",
            description="All good",
            context="review-checklists",
        )

    def test_truncates_long_description(self):
        repo = MagicMock()
        long_desc = "x" * 200
        set_commit_status(repo, "abc123", "pending", long_desc)
        commit = repo.get_commit.return_value
        call_kwargs = commit.create_status.call_args[1]
        assert len(call_kwargs["description"]) == 140

    def test_custom_context(self):
        repo = MagicMock()
        set_commit_status(
            repo, "abc123", "success", "ok", context="my-context"
        )
        commit = repo.get_commit.return_value
        call_kwargs = commit.create_status.call_args[1]
        assert call_kwargs["context"] == "my-context"


# ---------------------------------------------------------------------------
# check_merge_queue_protection
# ---------------------------------------------------------------------------


class TestCheckMergeQueueProtection:
    def test_passes_with_merge_queue_group_size_1(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
        repo = MagicMock()
        repo.full_name = "org/repo"

        rules = [
            {
                "type": "merge_queue",
                "parameters": {"max_entries_to_merge": 1},
            }
        ]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = rules

        with patch("helpers.requests.get", return_value=mock_resp):
            # Should not raise.
            check_merge_queue_protection(repo, "main")

    def test_fails_when_no_merge_queue_rule(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
        repo = MagicMock()
        repo.full_name = "org/repo"

        rules = [{"type": "pull_request", "parameters": {}}]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = rules

        with patch("helpers.requests.get", return_value=mock_resp):
            with pytest.raises(SystemExit) as exc_info:
                check_merge_queue_protection(repo, "main")
            assert exc_info.value.code == 1

    def test_fails_when_group_size_greater_than_1(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
        repo = MagicMock()
        repo.full_name = "org/repo"

        rules = [
            {
                "type": "merge_queue",
                "parameters": {"max_entries_to_merge": 5},
            }
        ]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = rules

        with patch("helpers.requests.get", return_value=mock_resp):
            with pytest.raises(SystemExit) as exc_info:
                check_merge_queue_protection(repo, "main")
            assert exc_info.value.code == 1

    def test_fails_on_api_error(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
        repo = MagicMock()
        repo.full_name = "org/repo"

        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "Not Found"

        with patch("helpers.requests.get", return_value=mock_resp):
            with pytest.raises(SystemExit) as exc_info:
                check_merge_queue_protection(repo, "main")
            assert exc_info.value.code == 1

    def test_passes_with_no_parameters(self, monkeypatch):
        """A merge_queue rule with no parameters should pass (default group size)."""
        monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
        repo = MagicMock()
        repo.full_name = "org/repo"

        rules = [{"type": "merge_queue", "parameters": {}}]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = rules

        with patch("helpers.requests.get", return_value=mock_resp):
            # Should not raise — when max_group_size is None we treat it as 1.
            check_merge_queue_protection(repo, "main")

    def test_passes_with_alternative_key_name(self, monkeypatch):
        """Supports the alternative 'group_size_limit' parameter key."""
        monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
        repo = MagicMock()
        repo.full_name = "org/repo"

        rules = [
            {
                "type": "merge_queue",
                "parameters": {"group_size_limit": 1},
            }
        ]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = rules

        with patch("helpers.requests.get", return_value=mock_resp):
            check_merge_queue_protection(repo, "main")

    def test_calls_correct_api_url(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
        repo = MagicMock()
        repo.full_name = "myorg/myrepo"

        rules = [
            {
                "type": "merge_queue",
                "parameters": {"max_entries_to_merge": 1},
            }
        ]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = rules

        with patch("helpers.requests.get", return_value=mock_resp) as mock_get:
            check_merge_queue_protection(repo, "develop")

        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert "myorg/myrepo" in call_args[0][0]
        assert "develop" in call_args[0][0]


# ---------------------------------------------------------------------------
# set_check_run
# ---------------------------------------------------------------------------


class TestSetCheckRun:
    def test_success_sends_completed_conclusion(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
        repo = MagicMock()
        repo.full_name = "org/repo"

        mock_resp = MagicMock()
        mock_resp.status_code = 201

        with patch("helpers.requests.post", return_value=mock_resp) as mock_post:
            set_check_run(repo, "abc123", "success", "All good")

        mock_post.assert_called_once()
        payload = mock_post.call_args[1]["json"]
        assert payload["status"] == "completed"
        assert payload["conclusion"] == "success"
        assert payload["head_sha"] == "abc123"
        assert payload["name"] == "review-checklists"
        assert payload["output"]["title"] == "All good"

    def test_failure_sends_completed_conclusion(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
        repo = MagicMock()
        repo.full_name = "org/repo"

        mock_resp = MagicMock()
        mock_resp.status_code = 201

        with patch("helpers.requests.post", return_value=mock_resp) as mock_post:
            set_check_run(repo, "abc123", "failure", "Missing acks")

        payload = mock_post.call_args[1]["json"]
        assert payload["status"] == "completed"
        assert payload["conclusion"] == "failure"

    def test_pending_sends_in_progress_without_conclusion(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
        repo = MagicMock()
        repo.full_name = "org/repo"

        mock_resp = MagicMock()
        mock_resp.status_code = 201

        with patch("helpers.requests.post", return_value=mock_resp) as mock_post:
            set_check_run(repo, "abc123", "pending", "Awaiting review")

        payload = mock_post.call_args[1]["json"]
        assert payload["status"] == "in_progress"
        assert "conclusion" not in payload

    def test_custom_name(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
        repo = MagicMock()
        repo.full_name = "org/repo"

        mock_resp = MagicMock()
        mock_resp.status_code = 201

        with patch("helpers.requests.post", return_value=mock_resp) as mock_post:
            set_check_run(
                repo, "abc123", "success", "ok", name="my-check"
            )

        payload = mock_post.call_args[1]["json"]
        assert payload["name"] == "my-check"

    def test_truncates_long_title(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
        repo = MagicMock()
        repo.full_name = "org/repo"

        mock_resp = MagicMock()
        mock_resp.status_code = 201

        long_summary = "x" * 200

        with patch("helpers.requests.post", return_value=mock_resp) as mock_post:
            set_check_run(repo, "abc123", "success", long_summary)

        payload = mock_post.call_args[1]["json"]
        assert len(payload["output"]["title"]) == 140
        # Full summary is preserved.
        assert payload["output"]["summary"] == long_summary

    def test_calls_correct_api_url(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
        repo = MagicMock()
        repo.full_name = "myorg/myrepo"

        mock_resp = MagicMock()
        mock_resp.status_code = 201

        with patch("helpers.requests.post", return_value=mock_resp) as mock_post:
            set_check_run(repo, "abc123", "success", "ok")

        url = mock_post.call_args[0][0]
        assert "myorg/myrepo" in url
        assert "/check-runs" in url
