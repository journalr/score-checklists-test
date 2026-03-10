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
    # 1. Bazel runfiles via the bazel-runfiles library (Rlocation API).
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

    # 2. Fallback: relative to this source file (works outside Bazel).
    candidate = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "checklists.yml"
    )
    if os.path.isfile(candidate):
        return candidate

    raise FileNotFoundError("Cannot locate checklists.yml")


def load_checklists() -> list[dict]:
    """Load checklist definitions from the YAML configuration file."""
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
    """Build the Markdown body for a checklist PR review comment (finding)."""
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
        f"**To acknowledge this checklist, reply to this conversation "
        f"with exactly `{OK_KEYWORD}`.** Each approving reviewer must "
        f"acknowledge every applicable checklist before the PR can be merged.\n"
    )
    return body


def find_existing_checklist_comments(pr: PullRequest) -> dict[str, Any]:
    """Find existing bot-managed checklist review comments (findings) on the PR.

    Returns a dict mapping checklist-id → PullRequestComment object.

    Checklist findings are identified by the ``CHECKLIST_MARKER`` HTML comment
    in their body.  We search PR review comments (``get_review_comments()``)
    because checklists are posted as file-level review comments that support
    threaded conversations where reviewers can reply with OK.
    """
    result = {}
    for comment in pr.get_review_comments():
        body = comment.body or ""
        prefix = "<!-- review-checklist:"
        if prefix in body:
            start = body.index(prefix) + len(prefix)
            end = body.index(" -->", start)
            cid = body[start:end]
            # Only keep top-level checklist comments (not replies).
            if not getattr(comment, "in_reply_to_id", None):
                result[cid] = comment
    return result


def find_ok_replies(
    pr: PullRequest, checklist_comment_id: int, checklist_id: str
) -> list[Any]:
    """Find valid OK reply comments for a given checklist review comment.

    We look at PR review comment replies (threaded conversation) where
    ``in_reply_to_id`` matches the checklist comment id.  A reply counts
    as an OK if its body (stripped, case-insensitive) equals the OK keyword.
    The conversation thread itself associates the reply with the checklist.
    """
    ok_replies = []
    for comment in pr.get_review_comments():
        reply_to = getattr(comment, "in_reply_to_id", None)
        if reply_to != checklist_comment_id:
            continue
        body = (comment.body or "").strip()
        if body.upper() == OK_KEYWORD:
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
    desc = description[:140]
    print(
        f"Setting commit status: context='{context}', state='{state}', "
        f"sha='{sha}', description='{desc}'"
    )
    repo.get_commit(sha).create_status(
        state=state,
        description=desc,
        context=context,
    )
    print("Commit status set successfully.")


# Evidence block markers for PR description
EVIDENCE_BLOCK_START = "<!-- review-checklist-evidence:start -->"
EVIDENCE_BLOCK_END = "<!-- review-checklist-evidence:end -->"

# Standalone merge-queue notice block in PR description.
MERGE_QUEUE_NOTICE_START = "<!-- review-checklist-merge-queue-notice:start -->"
MERGE_QUEUE_NOTICE_END = "<!-- review-checklist-merge-queue-notice:end -->"

# Marker for a bot-managed PR comment carrying the same notice.
MERGE_QUEUE_COMMENT_MARKER = "<!-- review-checklist-merge-queue-comment -->"


def extract_evidence_block(description: str) -> str | None:
    """Extract the evidence block from PR description, or None if not present."""
    if EVIDENCE_BLOCK_START not in description:
        return None
    try:
        start = description.index(EVIDENCE_BLOCK_START)
        end = description.index(EVIDENCE_BLOCK_END)
        return description[start : end + len(EVIDENCE_BLOCK_END)]
    except ValueError:
        return None


def remove_evidence_block(description: str) -> str:
    """Remove the evidence block from PR description."""
    if EVIDENCE_BLOCK_START not in description:
        return description
    try:
        start = description.index(EVIDENCE_BLOCK_START)
        end = description.index(EVIDENCE_BLOCK_END) + len(EVIDENCE_BLOCK_END)
        # Remove the evidence block and any trailing whitespace
        result = description[:start] + description[end:]
        return result.rstrip() + "\n"
    except ValueError:
        return description


def build_evidence_block(
    relevant: list[dict],
    ack_details: dict[str, list[dict[str, str]]],
) -> str:
    """Build the evidence block for the PR description."""
    from datetime import datetime, timezone

    lines = [
        EVIDENCE_BLOCK_START,
        "<details>",
        "<summary>Checklist Report (do not modify)</summary>",
        "",
        "## Review Checklist Evidence",
        "",
        f"**Last updated:** {datetime.now(timezone.utc).isoformat()}",
        "",
    ]

    for cl in relevant:
        cid = cl["id"]
        lines.append(f"### {cl['name']} (`{cid}`)")
        lines.append("")

        acks = ack_details.get(cid, [])
        if acks:
            lines.append("**Acknowledged by:**")
            for ack in acks:
                lines.append(
                    f"- {ack['reviewer']} at {ack['acknowledged_at']}"
                )
        else:
            lines.append("**Acknowledged by:** No acknowledgements yet")
        lines.append("")

    lines += [
        "</details>",
        EVIDENCE_BLOCK_END
    ]
    return "\n".join(lines)


def update_pr_description_with_evidence(
    pr: Any,
    evidence_block: str,
) -> None:
    """Update PR description to include/replace evidence block."""
    current_description = pr.body or ""

    # Remove existing evidence block
    new_description = remove_evidence_block(current_description)

    # Append new evidence block
    new_description = new_description + "\n" + evidence_block

    # Only update if description changed
    if new_description.strip() != current_description.strip():
        pr.edit(body=new_description)
        print("Updated PR description with evidence block")
    else:
        print("PR description evidence is already up to date")


def is_pr_in_merge_queue(pr: Any) -> bool:
    """Return whether the PR is currently in GitHub merge queue via GraphQL."""
    repo_name = getattr(getattr(getattr(pr, "base", None), "repo", None), "full_name", "")
    if not repo_name or "/" not in repo_name:
        repo_name = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" not in repo_name:
        print("Could not determine repository for merge-queue lookup")
        return False

    number = getattr(pr, "number", None)
    if not number:
        try:
            number = int(os.environ.get("PR_NUMBER", "0"))
        except ValueError:
            number = 0
    if not number:
        print("Could not determine PR number for merge-queue lookup")
        return False

    owner, name = repo_name.split("/", 1)
    query = """
      query($owner: String!, $name: String!, $number: Int!) {
        repository(owner: $owner, name: $name) {
          pullRequest(number: $number) {
            isInMergeQueue
          }
        }
      }
    """

    try:
        result = _run_graphql_query(
            query,
            {"owner": owner, "name": name, "number": int(number)},
        )
    except Exception as exc:
        print(f"GraphQL merge-queue lookup failed: {exc}")
        return False

    is_in_queue = (
        result.get("data", {})
        .get("repository", {})
        .get("pullRequest", {})
        .get("isInMergeQueue")
    )
    if isinstance(is_in_queue, bool):
        return is_in_queue

    print("GraphQL merge-queue lookup returned no boolean state")
    return False


def _build_merge_queue_notice_block() -> str:
    """Return the standalone merge-queue notice for PR description."""
    return "\n".join(
        [
            MERGE_QUEUE_NOTICE_START,
            "## Merge Queue Evidence Notice",
            "",
            "Changes made after this PR enters the merge queue may update",
            "the PR discussion and checklist state, but they do not affect",
            "the evidence recorded in git history via the merge commit flow.",
            MERGE_QUEUE_NOTICE_END,
        ]
    )


def _remove_merge_queue_notice_block(description: str) -> str:
    """Remove the standalone merge-queue notice block from PR description."""
    if MERGE_QUEUE_NOTICE_START not in description:
        return description
    try:
        start = description.index(MERGE_QUEUE_NOTICE_START)
        end = description.index(MERGE_QUEUE_NOTICE_END) + len(
            MERGE_QUEUE_NOTICE_END
        )
        result = description[:start] + description[end:]
        return result.rstrip() + "\n"
    except ValueError:
        return description


def ensure_merge_queue_notice_description(pr: Any) -> None:
    """Ensure a standalone merge-queue notice exists in the PR description."""
    current_description = pr.body or ""
    notice_block = _build_merge_queue_notice_block()
    description_without_notice = _remove_merge_queue_notice_block(
        current_description
    )
    base = description_without_notice.rstrip()
    if base:
        new_description = base + "\n\n" + notice_block
    else:
        new_description = notice_block

    if new_description.strip() != current_description.strip():
        pr.edit(body=new_description)
        print("Updated PR description with merge-queue evidence notice")


def ensure_merge_queue_notice_comment(pr: Any) -> None:
    """Ensure the PR has a single bot-managed merge-queue evidence notice."""
    body = "\n".join(
        [
            MERGE_QUEUE_COMMENT_MARKER,
            "Merge queue note: Changes made after this PR enters the merge queue",
            "may update PR checklist content, but they do not affect the evidence",
            "recorded in git history by the merge commit evidence flow.",
        ]
    )

    existing_comment = None
    for comment in pr.get_issue_comments():
        comment_body = comment.body or ""
        if MERGE_QUEUE_COMMENT_MARKER in comment_body:
            existing_comment = comment
            break

    if existing_comment is None:
        pr.create_issue_comment(body)
        print("Posted merge-queue evidence notice comment")
        return

    if (existing_comment.body or "").strip() != body.strip():
        existing_comment.edit(body)
        print("Updated merge-queue evidence notice comment")


def _run_graphql_query(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    """Execute a GitHub GraphQL query via PyGithub and return JSON data."""
    gh = get_github_client()
    result = gh.graphql_query(query=query, variables=variables)
    if not isinstance(result, dict):
        raise RuntimeError("Unexpected GraphQL response type")
    if "errors" in result:
        raise RuntimeError(f"GraphQL errors: {result['errors']}")
    return result
