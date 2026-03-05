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

"""Verify that evidence in PR description matches current acknowledgements.

This script runs during merge queue validation. It:

1. Collects current acknowledgements from threaded checklist comments
2. Extracts the evidence block from the PR description
3. Verifies that the evidence block in the description matches the current
   acknowledgement state
4. If verification passes, sets commit status to success, allowing the merge
5. If verification fails, sets commit status to failure, blocking the merge

The evidence block in the PR description is the single source of truth
during merge queue evaluation.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from typing import Any

from helpers import (
    OK_KEYWORD,
    find_existing_checklist_comments,
    get_approving_reviewers,
    get_changed_files,
    get_github_client,
    get_repo_and_pr,
    load_checklists,
    match_checklists,
    set_commit_status,
)

# Marker to identify the evidence block in PR description
EVIDENCE_BLOCK_START = "<!-- review-checklist-evidence:start -->"
EVIDENCE_BLOCK_END = "<!-- review-checklist-evidence:end -->"


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


def _extract_evidence_block(description: str) -> str | None:
    """Extract the evidence block from PR description, or None if not present."""
    if EVIDENCE_BLOCK_START not in description:
        return None
    try:
        start = description.index(EVIDENCE_BLOCK_START)
        end = description.index(EVIDENCE_BLOCK_END)
        return description[start : end + len(EVIDENCE_BLOCK_END)]
    except ValueError:
        return None


def _extract_acks_from_evidence(evidence_block: str) -> dict[str, set[str]]:
    """Extract acknowledged reviewers from the evidence block text.

    Parses the evidence block to find lines like:
    "- reviewer_name at timestamp"

    Returns dict of checklist_id → set of reviewer names.
    """
    result: dict[str, set[str]] = {}
    current_cid = None

    for line in evidence_block.split("\n"):
        # Detect checklist section: "### Checklist Name (`cid`)"
        if line.startswith("### "):
            # Extract checklist ID from backticks
            if "`" in line:
                start = line.index("`") + 1
                end = line.index("`", start)
                current_cid = line[start:end]
                result[current_cid] = set()
            continue

        # Extract acknowledgement lines: "- reviewer_name at timestamp"
        if current_cid and line.startswith("- "):
            # Format: "- reviewer_name at timestamp"
            parts = line[2:].split(" at ")
            if len(parts) >= 1:
                reviewer = parts[0].strip()
                result[current_cid].add(reviewer)

    return result


def _evidence_matches_current(
    evidence_block: str,
    current_acks: dict[str, list[dict[str, str]]],
    relevant_ids: list[str],
) -> bool:
    """Check if evidence block matches current acknowledgement state."""
    stored_acks = _extract_acks_from_evidence(evidence_block)

    # Convert current_acks to the same format for comparison
    current_acks_sets: dict[str, set[str]] = {
        cid: {ack["reviewer"] for ack in current_acks.get(cid, [])}
        for cid in relevant_ids
    }

    # Evidence matches if every relevant checklist has the same acknowledged reviewers
    for cid in relevant_ids:
        stored = stored_acks.get(cid, set())
        current = current_acks_sets.get(cid, set())
        if stored != current:
            return False

    return True


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

    # Extract evidence block from PR description
    pr_description = pr.body or ""
    evidence_block = _extract_evidence_block(pr_description)

    if not evidence_block:
        print("No evidence block found in PR description.")
        if strict:
            set_commit_status(
                repo, status_sha, "failure",
                "Evidence block not found in PR description",
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

    # Verify evidence block matches current state
    if _evidence_matches_current(evidence_block, ack_details, relevant_ids):
        print("Evidence block matches current acknowledgements ✅")
        set_commit_status(
            repo, status_sha, "success",
            "All checklists verified — evidence valid",
        )
    else:
        print("ERROR: Evidence block does not match current acknowledgements.")
        print("The PR description has been modified or acknowledgements changed.")
        set_commit_status(
            repo, status_sha, "failure",
            "Evidence in PR description is stale",
        )
        sys.exit(1)


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
