#!/usr/bin/env python3
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

"""Verify that all relevant checklists have been acknowledged by every approving
reviewer, and set the commit status accordingly.

An acknowledgement is a reply in the threaded conversation of a checklist
review comment (finding) that contains the ``OK`` keyword.  This script:

1. Ensures the merge-queue notice (comment + PR description) is present if
   the PR is currently enqueued in the merge queue.
2. Enumerates relevant checklists for the PR.
3. For each checklist, finds the bot-posted review comment and its OK replies.
4. Builds a mapping: checklist-id → set of reviewers who said OK.
5. Compares against the set of approving reviewers.
6. Sets commit status to *success* only when every approving reviewer has
   acknowledged every relevant checklist.  Otherwise sets *pending* or
   *failure*.

This script is invoked on every checklist-relevant event (it is always the
last step run), so it doubles as the single, fully stateless source of
truth for acknowledgement status: it always re-scans the current live
comment state rather than relying on which specific event triggered it.

For ``merge_group`` events it does not merely assume the evidence is still
valid because a required status check passed at some earlier point: it
resolves the underlying pull request and re-runs the same acknowledgement
validation against its current live state, setting the commit status on
the merge-queue's merge-commit SHA. This closes the window between when
the PR's own check last went green and when it actually entered the queue
(and rejects entries where that PR can no longer be resolved at all).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from helpers import (
    _collect_acknowledgement_details,
    OK_KEYWORD,
    build_evidence_block,
    ensure_merge_queue_notice_comment,
    ensure_merge_queue_notice_description,
    find_existing_checklist_comments,
    get_approving_reviewers,
    get_changed_files,
    get_github_client,
    get_repo_and_pr,
    is_pr_in_merge_queue,
    load_checklists,
    match_checklists,
    set_commit_status,
    update_pr_description_with_evidence,
)


def _collect_ok_acknowledgements(
    pr: Any, existing_comments: dict[str, Any], relevant_ids: list[str]
) -> dict[str, set[str]]:
    """Return a mapping of checklist_id → set of usernames who acknowledged.

    We inspect PR review comment replies (threaded conversations).  A reply
    counts as an OK for a checklist if:
      - Its ``in_reply_to_id`` matches the checklist finding comment id, AND
      - Its body (stripped, case-insensitive) equals the ``OK`` keyword.

    The conversation thread itself associates the reply with the checklist.
    """
    acks: dict[str, set[str]] = {cid: set() for cid in relevant_ids}

    # Build a mapping of checklist comment id → checklist id.
    cl_comment_ids: dict[int, str] = {}
    for cid, comment in existing_comments.items():
        if cid in relevant_ids:
            cl_comment_ids[comment.id] = cid

    # Walk all review comments looking for replies to checklist findings.
    for comment in pr.get_review_comments():
        reply_to = getattr(comment, "in_reply_to_id", None)
        if reply_to is None or reply_to not in cl_comment_ids:
            continue

        cid = cl_comment_ids[reply_to]  # type: ignore[index]
        body = (comment.body or "").strip()
        user = comment.user.login

        if body.upper() == OK_KEYWORD:
            acks[cid].add(user)

    return acks


def _acknowledgement_status(
    approvers: list[str],
    relevant_ids: list[str],
    acks: dict[str, set[str]],
) -> tuple[str, str]:
    """Compute the (state, description) commit-status pair from ack data.

    Pure decision logic with no side effects, so it can be reused both for
    the live PR flow (which also refreshes evidence/comments) and for
    merge_group evidence validation (which must not write anything).
    """
    if not approvers:
        return "pending", "Awaiting at least one approving review"

    missing: dict[str, list[str]] = {}
    for cid in relevant_ids:
        not_acked = [u for u in approvers if u not in acks[cid]]
        if not_acked:
            missing[cid] = not_acked

    if missing:
        summary_parts = [
            f"{cid}: awaiting {', '.join(users)}" for cid, users in missing.items()
        ]
        return "pending", "; ".join(summary_parts)

    return "success", "All checklists acknowledged by all approving reviewers"


def _validate_checklist_evidence(pr: Any, checklists: list[dict]) -> tuple[str, str]:
    """Re-derive and validate checklist acknowledgement evidence for a PR.

    Reads the PR's current live state (changed files, checklist findings,
    threaded OK replies, approving reviews) and returns the same
    (state, description) pair that would be used to set the
    "review-checklists" commit status, without any side effects. Used to
    validate the evidence at merge_group time instead of assuming it is
    still valid because a required status check passed at some earlier
    point.
    """
    changed_files = get_changed_files(pr)
    relevant = match_checklists(checklists, changed_files)

    if not relevant:
        return "success", "No checklists applicable"

    existing = find_existing_checklist_comments(pr)
    relevant_ids = [cl["id"] for cl in relevant if cl["id"] in existing]

    if not relevant_ids:
        return "pending", "Checklist comments not yet posted"

    acks = _collect_ok_acknowledgements(pr, existing, relevant_ids)
    approvers = get_approving_reviewers(pr)
    return _acknowledgement_status(approvers, relevant_ids, acks)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify review-checklist acknowledgements on a PR."
    )
    parser.add_argument(
        "--config-path",
        default=".github/review_checklists.yml",
        help="Path to checklist configuration file (default: .github/review_checklists.yml)",
    )
    args = parser.parse_args()

    gh = get_github_client()
    event_name = os.environ.get("CHECKLISTS_EVENT_NAME", "")
    if event_name == "merge_group":
        head_sha = os.environ.get("HEAD_SHA")
        if not head_sha:
            print("HEAD_SHA is required for merge_group events.")
            sys.exit(1)
        repo_name = os.environ["GITHUB_REPOSITORY"]
        repo = gh.get_repo(repo_name)

        pr_number_raw = os.environ.get("PR_NUMBER", "")
        try:
            pr_number = int(pr_number_raw)
        except ValueError:
            pr_number = 0

        if not pr_number:
            description = (
                "Could not resolve pull request to validate checklist evidence"
            )
            print(description)
            set_commit_status(repo, head_sha, "failure", description)
            sys.exit(1)

        pr = repo.get_pull(pr_number)
        checklists = load_checklists(args.config_path)
        state, description = _validate_checklist_evidence(pr, checklists)
        set_commit_status(repo, head_sha, state, f"Merge queue: {description}")
        if state != "success":
            print(f"Merge-queue checklist evidence validation failed: {description}")
            sys.exit(1)
        print("Merge-queue checklist evidence validated ✅")
        return

    repo, pr = get_repo_and_pr(gh)

    if is_pr_in_merge_queue(pr):
        ensure_merge_queue_notice_comment(pr)
        ensure_merge_queue_notice_description(pr)

    checklists = load_checklists(args.config_path)
    changed_files = get_changed_files(pr)
    relevant = match_checklists(checklists, changed_files)

    if not relevant:
        set_commit_status(repo, pr.head.sha, "success", "No checklists applicable")
        return

    existing = find_existing_checklist_comments(pr)
    relevant_ids = [cl["id"] for cl in relevant if cl["id"] in existing]

    if not relevant_ids:
        # Checklists haven't been posted yet — keep pending.
        set_commit_status(
            repo,
            pr.head.sha,
            "pending",
            "Checklist comments not yet posted",
        )
        return

    acks = _collect_ok_acknowledgements(pr, existing, relevant_ids)

    # Refresh evidence block in PR description based on current acknowledgements.
    ack_details = _collect_acknowledgement_details(pr, existing, relevant_ids)
    evidence_block = build_evidence_block(relevant, ack_details)
    update_pr_description_with_evidence(pr, evidence_block)

    approvers = get_approving_reviewers(pr)
    state, description = _acknowledgement_status(approvers, relevant_ids, acks)
    set_commit_status(repo, pr.head.sha, state, description)
    print(f"Acknowledgement status: {state} — {description}")

    # Write acknowledgement data for downstream use (merge evidence).
    ack_data = {cid: sorted(users) for cid, users in acks.items()}
    runner_temp = os.environ.get("RUNNER_TEMP", "./")
    output_path = os.environ.get(
        "ACK_OUTPUT_PATH", runner_temp + "/checklist_acks.json"
    )
    with open(output_path, "w") as f:
        json.dump(ack_data, f, indent=2)
    print(f"Acknowledgement data written to {output_path}")


if __name__ == "__main__":
    main()
