#!/usr/bin/env python3
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

"""Verify that all relevant checklists have been acknowledged by every approving
reviewer, and set the commit status accordingly.

An acknowledgement is an issue comment that contains the ``OK`` keyword
along with the checklist-ok marker.  This script:

1. Enumerates relevant checklists for the PR.
2. For each checklist, finds the bot-posted review finding and its OK replies.
3. Builds a mapping: checklist-id → set of reviewers who said OK.
4. Compares against the set of approving reviewers.
5. Sets commit status to *success* only when every approving reviewer has
   acknowledged every relevant checklist.  Otherwise sets *pending* or
   *failure*.
"""

from __future__ import annotations

import json
import os
from typing import Any

from helpers import (
    OK_KEYWORD,
    OK_MARKER,
    find_existing_checklist_comments,
    get_approving_reviewers,
    get_changed_files,
    get_github_client,
    get_repo_and_pr,
    load_checklists,
    match_checklists,
    set_commit_status,
)


def _collect_ok_acknowledgements(
    pr: Any, existing_reviews: dict[str, Any], relevant_ids: list[str]
) -> dict[str, set[str]]:
    """Return a mapping of checklist_id → set of usernames who acknowledged.

    We inspect all issue comments on the PR.  A comment counts as an OK for
    a checklist if it contains the ``OK_MARKER`` for that checklist.

    Bare ``OK`` comments (without a marker) are associated with a checklist
    heuristically and then tagged with the marker for future determinism.

    Checklist findings are posted as PR reviews, so they do not appear in
    issue comments.  Only OK reply comments are issue comments.
    """
    acks: dict[str, set[str]] = {cid: set() for cid in relevant_ids}

    # Walk all issue comments looking for OK markers or bare OKs.
    all_comments = sorted(pr.get_issue_comments(), key=lambda c: c.created_at)

    for comment in all_comments:
        body = (comment.body or "").strip()
        user = comment.user.login

        # Check for explicit OK markers.
        found_marker = False
        for cid in relevant_ids:
            marker = OK_MARKER.format(checklist_id=cid)
            if marker in body:
                acks[cid].add(user)
                found_marker = True

        if found_marker:
            continue

        # Check for bare OK keyword.
        if body.upper() == OK_KEYWORD:
            # Associate with the first relevant checklist that the user
            # hasn't acknowledged yet.
            for cid in relevant_ids:
                if user not in acks[cid]:
                    acks[cid].add(user)
                    marker = OK_MARKER.format(checklist_id=cid)
                    try:
                        comment.edit(f"{body}\n{marker}")
                        print(
                            f"Tagged bare OK comment {comment.id} from {user} "
                            f"with marker for checklist '{cid}'"
                        )
                    except Exception as exc:
                        print(
                            f"Warning: could not tag comment {comment.id}: {exc}"
                        )
                    break

    return acks


def main() -> None:
    gh = get_github_client()
    repo, pr = get_repo_and_pr(gh)

    checklists = load_checklists()
    changed_files = get_changed_files(pr)
    relevant = match_checklists(checklists, changed_files)

    if not relevant:
        set_commit_status(
            repo, pr.head.sha, "success", "No checklists applicable"
        )
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
    ack_data = {
        cid: sorted(users) for cid, users in acks.items()
    }
    output_path = os.environ.get("ACK_OUTPUT_PATH", "/tmp/checklist_acks.json")
    with open(output_path, "w") as f:
        json.dump(ack_data, f, indent=2)
    print(f"Acknowledgement data written to {output_path}")


if __name__ == "__main__":
    main()

