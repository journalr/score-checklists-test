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

1. Enumerates relevant checklists for the PR.
2. For each checklist, finds the bot-posted review comment and its OK replies.
3. Builds a mapping: checklist-id → set of reviewers who said OK.
4. Compares against the set of approving reviewers.
5. Sets commit status to *success* only when every approving reviewer has
   acknowledged every relevant checklist.  Otherwise sets *pending* or
   *failure*.
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
    find_existing_checklist_comments,
    get_approving_reviewers,
    get_changed_files,
    get_github_client,
    get_repo_and_pr,
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
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    if event_name == "merge_group":
        head_sha = os.environ.get("HEAD_SHA")
        if not head_sha:
            print("HEAD_SHA is required for merge_group events.")
            sys.exit(1)
        repo_name = os.environ["GITHUB_REPOSITORY"]
        repo = gh.get_repo(repo_name)
        set_commit_status(
            repo,
            head_sha,
            "success",
            "Merge queue: checklists assumed OK",
        )
        return

    repo, pr = get_repo_and_pr(gh)

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

    if not approvers:
        set_commit_status(
            repo,
            pr.head.sha,
            "pending",
            "Awaiting at least one approving review",
        )
        print("No approving reviewers yet.")
        return

    # Check: every approver must have acknowledged every relevant checklist.
    missing: dict[str, list[str]] = {}
    for cid in relevant_ids:
        not_acked = [u for u in approvers if u not in acks[cid]]
        if not_acked:
            missing[cid] = not_acked

    if missing:
        summary_parts = []
        for cid, users in missing.items():
            summary_parts.append(f"{cid}: awaiting {', '.join(users)}")
        summary = "; ".join(summary_parts)
        set_commit_status(
            repo,
            pr.head.sha,
            "pending",
            summary,
        )
        print(f"Missing acknowledgements: {summary}")
    else:
        set_commit_status(
            repo,
            pr.head.sha,
            "success",
            "All checklists acknowledged by all approving reviewers",
        )
        print("All checklists acknowledged ✅")

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
