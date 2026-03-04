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
    find_existing_checklist_comments,
    find_ok_replies,
    get_approving_reviewers,
    get_changed_files,
    get_github_client,
    get_repo_and_pr,
    load_checklists,
    make_checklist_comment_body,
    match_checklists,
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
    def test_finds_checklist_reviews(self):
        r1 = _make_review(
            "bot", "COMMENTED", review_id=1,
            body="<!-- review-checklist:api-review --> body here",
        )
        r2 = _make_review(
            "alice", "APPROVED", review_id=2,
            body="just a normal review",
        )
        r3 = _make_review(
            "bot", "COMMENTED", review_id=3,
            body="<!-- review-checklist:docs-review --> docs body",
        )
        pr = MagicMock()
        pr.get_reviews.return_value = [r1, r2, r3]

        result = find_existing_checklist_comments(pr)
        assert set(result.keys()) == {"api-review", "docs-review"}
        assert result["api-review"].id == 1
        assert result["docs-review"].id == 3

    def test_returns_empty_when_none(self):
        pr = MagicMock()
        pr.get_reviews.return_value = [
            _make_review("alice", "APPROVED", review_id=1, body="nothing here")
        ]
        assert find_existing_checklist_comments(pr) == {}


# ---------------------------------------------------------------------------
# find_ok_replies
# ---------------------------------------------------------------------------


class TestFindOkReplies:
    def test_finds_marker_based_ok(self):
        marker = OK_MARKER.format(checklist_id="api-review")
        c1 = _make_comment(11, f"OK\n{marker}", "reviewer1")
        pr = MagicMock()
        pr.get_issue_comments.return_value = [c1]

        result = find_ok_replies(pr, 10, "api-review")
        assert len(result) == 1
        assert result[0].id == 11

    def test_finds_bare_ok(self):
        c1 = _make_comment(11, "OK", "reviewer1")
        pr = MagicMock()
        pr.get_issue_comments.return_value = [c1]

        result = find_ok_replies(pr, 10, "api-review")
        assert len(result) == 1

    def test_ignores_unrelated_comment(self):
        c1 = _make_comment(11, "looks good but not OK keyword", "reviewer1")
        pr = MagicMock()
        pr.get_issue_comments.return_value = [c1]

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

