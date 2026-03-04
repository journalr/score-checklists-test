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

"""Create an empty evidence commit recording checklist acknowledgements.

This script creates an additional empty commit (same tree as HEAD) on
the given branch.  The commit message records:
- Each relevant checklist and its content
- Which reviewers acknowledged each checklist
- Timestamps of acknowledgements

This provides an auditable trail of the review-checklist process.

When invoked with ``--strict``, the script first verifies that every
approving reviewer has acknowledged every relevant checklist.  If not,
it exits with a non-zero status **without** creating the evidence commit.
This allows the merge queue to atomically verify and record evidence in
a single step — if verification fails the merge is blocked.
"""

from __future__ import annotations

import argparse
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
)


def _collect_acknowledgement_details(
    pr: Any, existing_comments: dict[str, Any], relevant_ids: list[str]
) -> dict[str, list[dict[str, str]]]:
    """Collect detailed acknowledgement information.

    Returns a mapping of checklist_id → list of dicts with keys:
        - reviewer: username
        - acknowledged_at: ISO timestamp

    Checklist findings are posted as file-level PR review comments; OK
    replies are threaded review comment replies whose body equals the
    OK keyword.  The conversation thread associates the reply with the
    checklist.
    """
    details: dict[str, list[dict[str, str]]] = {
        cid: [] for cid in relevant_ids
    }

    # Build a mapping of checklist comment id → checklist id.
    cl_comment_ids: dict[int, str] = {}
    for cid, comment in existing_comments.items():
        if cid in relevant_ids:
            cl_comment_ids[comment.id] = cid

    for comment in pr.get_review_comments():
        reply_to = getattr(comment, "in_reply_to_id", None)
        if reply_to is None or reply_to not in cl_comment_ids:
            continue

        cid = cl_comment_ids[reply_to]  # type: ignore[index]
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
    """Return a dict of checklist_id → list of approvers who have NOT acknowledged.

    An empty dict means all approvers acknowledged all checklists.
    """
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


def _build_evidence_message(
    pr: Any,
    relevant: list[dict],
    ack_details: dict[str, list[dict[str, str]]],
) -> str:
    """Build the evidence commit message."""
    lines = [
        f"chore: review-checklist evidence for PR #{pr.number}",
        "",
        f"PR: {pr.title}",
        f"PR URL: {pr.html_url}",
        f"Merged at: {datetime.now(timezone.utc).isoformat()}",
        "",
        "=" * 60,
        "REVIEW CHECKLIST EVIDENCE",
        "=" * 60,
        "",
    ]

    for cl in relevant:
        cid = cl["id"]
        lines.append(f"## {cl['name']} ({cid})")
        lines.append(f"Paths: {', '.join(cl['paths'])}")
        lines.append("")
        lines.append("Checklist:")
        for checklist_line in cl["checklist"].strip().splitlines():
            lines.append(f"  {checklist_line}")
        lines.append("")

        acks = ack_details.get(cid, [])
        if acks:
            lines.append("Acknowledged by:")
            for ack in acks:
                lines.append(
                    f"  - {ack['reviewer']} at {ack['acknowledged_at']}"
                )
        else:
            lines.append("Acknowledged by: (none)")
        lines.append("")
        lines.append("-" * 40)
        lines.append("")

    return "\n".join(lines)


def main(strict: bool = False, branch: str | None = None) -> None:
    gh = get_github_client()
    repo, pr = get_repo_and_pr(gh)

    checklists = load_checklists()
    changed_files = get_changed_files(pr)
    relevant = match_checklists(checklists, changed_files)

    if not relevant:
        print("No relevant checklists — skipping evidence commit.")
        return

    existing = find_existing_checklist_comments(pr)
    relevant_ids = [cl["id"] for cl in relevant if cl["id"] in existing]

    if not relevant_ids:
        print("No checklist review findings found — skipping evidence commit.")
        if strict:
            sys.exit(1)
        return

    ack_details = _collect_acknowledgement_details(pr, existing, relevant_ids)

    # When strict, verify all approvers acknowledged before creating evidence.
    if strict:
        approvers = get_approving_reviewers(pr)
        if not approvers:
            print("ERROR: No approving reviewers — cannot create evidence.")
            sys.exit(1)

        missing = _verify_all_acknowledged(ack_details, approvers, relevant_ids)
        if missing:
            for cid, users in missing.items():
                print(f"ERROR: {cid}: awaiting {', '.join(users)}")
            print(
                "Acknowledgement verification failed "
                "— aborting evidence commit."
            )
            sys.exit(1)

        print("All acknowledgements verified ✅")

    message = _build_evidence_message(pr, relevant, ack_details)

    # Determine which branch to commit on.
    target_ref = branch if branch else f"heads/{pr.base.ref}"
    ref = repo.get_git_ref(target_ref)
    head_sha = ref.object.sha
    head_commit = repo.get_git_commit(head_sha)

    # Create an empty commit: same tree, parent = current HEAD.
    new_commit = repo.create_git_commit(
        message=message,
        tree=head_commit.tree,
        parents=[head_commit],
    )

    # Update the branch ref to point to the new commit.
    ref.edit(sha=new_commit.sha)

    print(f"Created evidence commit {new_commit.sha} on {target_ref}")
    print(f"Commit message:\n{message}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Create evidence commit recording checklist acknowledgements."
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="Verify all acknowledgements before creating the evidence commit. "
             "Exit non-zero if incomplete.",
    )
    parser.add_argument(
        "--branch",
        default=None,
        help="Git ref to commit on (e.g. 'heads/main' or "
             "'heads/gh-readonly-queue/main/pr-42-abc123'). "
             "Defaults to heads/{pr.base.ref}.",
    )
    args = parser.parse_args()
    main(strict=args.strict, branch=args.branch)

