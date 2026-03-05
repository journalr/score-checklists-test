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

"""Update PR description evidence in merge queue and verify acknowledgements.

This script runs during merge queue validation. It:

1. Collects current acknowledgements from threaded checklist comments
2. Updates the evidence block in the PR description
3. Verifies that all approving reviewers acknowledged all checklists
4. Sets commit status to success or failure accordingly
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from helpers import (
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


def _collect_acknowledgement_details(
    pr: Any, existing_comments: dict[str, Any], relevant_ids: list[str]
) -> dict[str, list[dict[str, str]]]:
    """Collect detailed acknowledgement information from review comments."""
    details: dict[str, list[dict[str, str]]] = {
        cid: [] for cid in relevant_ids
    }

    cl_comment_ids: dict[int, str] = {}
    for cid, comment in existing_comments.items():
        if cid in relevant_ids:
            cl_comment_ids[comment.id] = cid

    for comment in pr.get_review_comments():
        reply_to = getattr(comment, "in_reply_to_id", None)
        if reply_to is None or reply_to not in cl_comment_ids:
            continue

        cid = cl_comment_ids[reply_to]
        body = (comment.body or "").strip()
        user = comment.user.login

        if body.upper() == OK_KEYWORD:
            details[cid].append(
                {
                    "reviewer": user,
                    "acknowledged_at": comment.created_at.isoformat(),
                }
            )

    return details


def _verify_all_acknowledged(
    ack_details: dict[str, list[dict[str, str]]],
    approvers: list[str],
    relevant_ids: list[str],
) -> dict[str, list[str]]:
    """Return dict of checklist_id → list of approvers who have NOT acknowledged."""
    acked_users: dict[str, set[str]] = {
        cid: {a["reviewer"] for a in ack_details.get(cid, [])}
        for cid in relevant_ids
    }
    missing: dict[str, list[str]] = {}
    for cid in relevant_ids:
        not_acked = [u for u in approvers if u not in acked_users[cid]]
        if not_acked:
            missing[cid] = not_acked
    return missing


def main(strict: bool = False) -> None:
    gh = get_github_client()
    repo, pr = get_repo_and_pr(gh)

    status_sha = os.environ.get("HEAD_SHA") or pr.head.sha
    print(f"Commit status SHA: {status_sha}")

    checklists = load_checklists()
    changed_files = get_changed_files(pr)
    relevant = match_checklists(checklists, changed_files)

    if not relevant:
        print("No relevant checklists — no evidence verification needed.")
        set_commit_status(
            repo, status_sha, "success",
            "No checklists applicable",
        )
        return

    existing = find_existing_checklist_comments(pr)
    relevant_ids = [cl["id"] for cl in relevant if cl["id"] in existing]

    if not relevant_ids:
        print("No checklist review findings found.")
        if strict:
            set_commit_status(
                repo, status_sha, "failure",
                "Checklist findings not found",
            )
            sys.exit(1)
        return

    # Collect current acknowledgements
    ack_details = _collect_acknowledgement_details(pr, existing, relevant_ids)

    # When strict, verify all approvers acknowledged
    if strict:
        approvers = get_approving_reviewers(pr)
        if not approvers:
            print("ERROR: No approving reviewers.")
            set_commit_status(
                repo, status_sha, "failure",
                "No approving reviewers",
            )
            sys.exit(1)

        missing = _verify_all_acknowledged(ack_details, approvers, relevant_ids)
        if missing:
            parts = []
            for cid, users in missing.items():
                print(f"ERROR: {cid}: awaiting {', '.join(users)}")
                parts.append(f"{cid}: awaiting {', '.join(users)}")
            print("Not all approvers have acknowledged all checklists.")
            set_commit_status(
                repo, status_sha, "failure",
                "; ".join(parts),
            )
            sys.exit(1)

        print("All approvers acknowledged all checklists ✅")

    # Update PR description evidence block
    evidence_block = build_evidence_block(relevant, ack_details)
    update_pr_description_with_evidence(pr, evidence_block)

    set_commit_status(
        repo, status_sha, "success",
        "All checklists verified — evidence updated",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Verify evidence in PR description matches current state."
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="Also verify all approvers have acknowledged. Exit non-zero if incomplete.",
    )
    args = parser.parse_args()
    main(strict=args.strict)
