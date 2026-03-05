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

"""Post or update review-checklist findings on a pull request.

For every relevant checklist (determined by path-matching against changed
files), a file-level PR review comment (finding) is created on the PR,
anchored to the first matched file.  If the finding already exists it is
updated in place so that the conversation thread (and any replies) is
preserved.  File-level review comments are used because they support
threaded conversations where reviewers can reply directly with OK.
"""

from __future__ import annotations


from helpers import (
    build_evidence_block,
    check_merge_queue_protection,
    find_existing_checklist_comments,
    get_changed_files,
    get_github_client,
    get_repo_and_pr,
    load_checklists,
    make_checklist_comment_body,
    match_checklists,
    set_commit_status,
    update_pr_description_with_evidence,
)


def _collect_acknowledgement_details(
    pr, existing_comments: dict, relevant_ids: list[str]
) -> dict[str, list[dict[str, str]]]:
    """Collect detailed acknowledgement information from review comments."""
    from datetime import datetime, timezone
    from helpers import OK_KEYWORD

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


def main() -> None:
    gh = get_github_client()
    repo, pr = get_repo_and_pr(gh)

    # Verify the target branch enforces a merge queue with proper settings.
    check_merge_queue_protection(repo, pr.base.ref)

    checklists = load_checklists()
    changed_files = get_changed_files(pr)
    relevant = match_checklists(checklists, changed_files)

    if not relevant:
        print("No checklists are relevant for this PR.")
        set_commit_status(
            repo,
            pr.head.sha,
            "success",
            "No checklists applicable",
        )
        return

    existing = find_existing_checklist_comments(pr)

    for cl in relevant:
        body = make_checklist_comment_body(cl)
        if cl["id"] in existing:
            comment = existing[cl["id"]]
            # Only update if the body actually changed (avoids notification spam).
            if (comment.body or "").strip() != body.strip():
                comment.edit(body=body)
                print(f"Updated checklist finding for '{cl['id']}'")
            else:
                print(
                    f"Checklist finding for '{cl['id']}' is already up to date"
                )
        else:
            # Post as a review with an inline comment (finding) on the first
            # matched file.  Using create_review with comments creates a
            # PullRequestComment that supports threaded replies where
            # reviewers can acknowledge with OK.
            anchor_file = cl["matched_files"][0]
            pr.create_review(
                body="",
                event="COMMENT",
                comments=[
                    {
                        "path": anchor_file,
                        "position": 1,
                        "body": body,
                    }
                ],
            )
            print(f"Created checklist finding for '{cl['id']}'")

    # Set a pending check — actual pass/fail is determined by check_acknowledgements.
    set_commit_status(
        repo,
        pr.head.sha,
        "pending",
        f"{len(relevant)} checklist(s) require reviewer acknowledgement",
    )

    print(f"Posted/updated {len(relevant)} checklist finding(s).")


if __name__ == "__main__":
    main()

