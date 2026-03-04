# *******************************************************************************
# Copyright (c) 2024 Contributors to the Eclipse Foundation
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

"""Shared helpers for review-checklist scripts."""

from __future__ import annotations

import fnmatch
import os
from typing import Any

import yaml
from github import Github
from github.PullRequest import PullRequest


# Marker prefix used to identify bot-managed checklist reviews.
CHECKLIST_MARKER = "<!-- review-checklist:{checklist_id} -->"
OK_MARKER = "<!-- checklist-ok:{checklist_id} -->"

# The keyword a reviewer must post to acknowledge a checklist.
OK_KEYWORD = "OK"


def get_github_client() -> Github:
    """Return an authenticated PyGithub client."""
    token = os.environ["GITHUB_TOKEN"]
    return Github(token)


def get_repo_and_pr(gh: Github) -> tuple[Any, PullRequest]:
    """Return the repository and pull-request objects from environment."""
    repo_name = os.environ["GITHUB_REPOSITORY"]
    pr_number = int(os.environ["PR_NUMBER"])
    repo = gh.get_repo(repo_name)
    pr = repo.get_pull(pr_number)
    return repo, pr


def _find_checklists_config() -> str:
    """Locate checklists.yml using Bazel runfiles, env var, or path heuristics."""
    # 1. Explicit override via environment variable.
    env_path = os.environ.get("CHECKLISTS_CONFIG")
    if env_path and os.path.isfile(env_path):
        return env_path

    # 2. Bazel runfiles via the bazel-runfiles library (Rlocation API).
    try:
        from runfiles import Runfiles  # type: ignore[import-untyped]

        r = Runfiles.Create()
        if r:
            candidate = r.Rlocation(
                "_main/actions/review-checklists/checklists.yml"
            )
            if candidate and os.path.isfile(candidate):
                return candidate
    except (ImportError, Exception):
        pass

    # 3. Fallback: relative to this source file (works outside Bazel).
    candidate = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "checklists.yml"
    )
    if os.path.isfile(candidate):
        return candidate

    raise FileNotFoundError("Cannot locate checklists.yml")


def load_checklists(config_path: str | None = None) -> list[dict]:
    """Load checklist definitions from the YAML configuration file."""
    if config_path is None:
        config_path = _find_checklists_config()
    with open(config_path, "r") as f:
        data = yaml.safe_load(f)
    return data["checklists"]


def get_changed_files(pr: PullRequest) -> list[str]:
    """Return the list of files changed in the pull request."""
    return [f.filename for f in pr.get_files()]


def match_checklists(
    checklists: list[dict], changed_files: list[str]
) -> list[dict]:
    """Return checklists whose path patterns match at least one changed file.

    Each returned checklist dict is augmented with a ``matched_files`` key
    containing the list of changed files that triggered the match.
    """
    relevant = []
    for cl in checklists:
        matched = set()
        for pattern in cl["paths"]:
            for filepath in changed_files:
                if fnmatch.fnmatch(filepath, pattern):
                    matched.add(filepath)
        if matched:
            cl_copy = dict(cl)
            cl_copy["matched_files"] = sorted(matched)
            relevant.append(cl_copy)
    return relevant


def make_checklist_comment_body(checklist: dict) -> str:
    """Build the Markdown body for a checklist PR review finding."""
    marker = CHECKLIST_MARKER.format(checklist_id=checklist["id"])
    body = (
        f"{marker}\n"
        f"## 📋 {checklist['name']}\n\n"
        f"**Checklist ID:** `{checklist['id']}`\n\n"
        f"**Applicable to files matching:** "
        f"`{'`, `'.join(checklist['paths'])}`\n\n"
        f"### Checklist\n\n"
        f"{checklist['checklist'].strip()}\n\n"
        f"---\n"
        f"**To acknowledge this checklist, post a comment containing "
        f"exactly `{OK_KEYWORD}` with the marker "
        f"`{OK_MARKER.format(checklist_id=checklist['id'])}`.** "
        f"Each approving reviewer must "
        f"acknowledge every applicable checklist before the PR can be merged.\n"
    )
    return body


def find_existing_checklist_comments(pr: PullRequest) -> dict[str, Any]:
    """Find existing bot-managed checklist reviews on the PR.

    Returns a dict mapping checklist-id → review object.

    Checklist reviews are identified by the ``CHECKLIST_MARKER`` HTML comment
    in their body.  We search PR reviews (not issue comments) because
    checklists are posted as review findings so that users can reply in
    threaded conversations.
    """
    result = {}
    for review in pr.get_reviews():
        body = review.body or ""
        for prefix in ("<!-- review-checklist:",):
            if prefix in body:
                # Extract checklist id from the marker.
                start = body.index(prefix) + len(prefix)
                end = body.index(" -->", start)
                cid = body[start:end]
                result[cid] = review
    return result


def find_ok_replies(
    pr: PullRequest, checklist_review_id: int, checklist_id: str
) -> list[Any]:
    """Find valid OK reply comments for a given checklist review.

    We look at issue comments that contain the OK marker for this checklist
    or a raw OK keyword.  Since checklist findings are posted as PR reviews,
    OK replies are issue comments tagged with the checklist-ok marker.
    """
    ok_replies = []
    ok_marker = OK_MARKER.format(checklist_id=checklist_id)
    for comment in pr.get_issue_comments():
        body = (comment.body or "").strip()
        if ok_marker in body:
            ok_replies.append(comment)
        elif body.upper() == OK_KEYWORD:
            # Heuristic: a bare "OK" comment is matched by proximity.
            # The check_acknowledgements script will tag it with the marker.
            ok_replies.append(comment)
    return ok_replies


def get_approving_reviewers(pr: PullRequest) -> list[str]:
    """Return a list of usernames who have an active APPROVED review."""
    approvers = set()
    for review in pr.get_reviews():
        if review.state == "APPROVED":
            approvers.add(review.user.login)
        elif review.state in ("CHANGES_REQUESTED", "DISMISSED"):
            approvers.discard(review.user.login)
    return sorted(approvers)


def set_commit_status(
    repo: Any,
    sha: str,
    state: str,
    description: str,
    context: str = "review-checklists",
) -> None:
    """Set a commit status on the given SHA."""
    repo.get_commit(sha).create_status(
        state=state,
        description=description[:140],
        context=context,
    )

