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

After a PR is merged, this script creates an additional empty commit
(same tree as HEAD) on the target branch.  The commit message records:
- Each relevant checklist and its content
- Which reviewers acknowledged each checklist
- Timestamps of acknowledgements

This provides an auditable trail of the review-checklist process.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from helpers import (
    OK_MARKER,
    find_existing_checklist_comments,
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
    replies are threaded review comment replies tagged with the
    checklist-ok marker.
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

        marker = OK_MARKER.format(checklist_id=cid)
        if marker in body:
            details[cid].append(
                {
                    "reviewer": user,
                    "acknowledged_at": comment.created_at.isoformat(),
                }
            )

    return details


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


def main() -> None:
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
        return

    ack_details = _collect_acknowledgement_details(pr, existing, relevant_ids)
    message = _build_evidence_message(pr, relevant, ack_details)

    # Get the merge commit (the HEAD of the target branch after merge).
    target_branch = pr.base.ref
    ref = repo.get_git_ref(f"heads/{target_branch}")
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

    print(f"Created evidence commit {new_commit.sha} on {target_branch}")
    print(f"Commit message:\n{message}")


if __name__ == "__main__":
    main()

