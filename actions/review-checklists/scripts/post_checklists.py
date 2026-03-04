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
    find_existing_checklist_comments,
    get_changed_files,
    get_github_client,
    get_repo_and_pr,
    load_checklists,
    make_checklist_comment_body,
    match_checklists,
    set_commit_status,
)


def main() -> None:
    gh = get_github_client()
    repo, pr = get_repo_and_pr(gh)

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
            # Post as a file-level review comment (finding) on the first
            # matched file.  subject_type="file" creates a file-level
            # comment that is not tied to a specific diff line — it
            # appears as a conversation on the file and supports threaded
            # replies.
            anchor_file = cl["matched_files"][0]
            pr.create_review_comment(
                body=body,
                commit=pr.head.sha,
                path=anchor_file,
                subject_type="file",
                line=1,
            )
            print(f"Created checklist finding for '{cl['id']}'")

    # Set a pending status — actual pass/fail is determined by check_acknowledgements.
    set_commit_status(
        repo,
        pr.head.sha,
        "pending",
        f"{len(relevant)} checklist(s) require reviewer acknowledgement",
    )

    print(f"Posted/updated {len(relevant)} checklist finding(s).")


if __name__ == "__main__":
    main()

