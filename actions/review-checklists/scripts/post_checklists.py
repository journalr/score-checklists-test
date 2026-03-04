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
files), a PR review finding is created on the PR.  If the review already
exists it is updated in place so that the conversation thread (and any
replies) is preserved.  Reviews are used instead of issue comments so that
users can reply in threaded conversations.
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
            review = existing[cl["id"]]
            # Only update if the body actually changed (avoids notification spam).
            if (review.body or "").strip() != body.strip():
                review.edit(body=body)
                print(f"Updated checklist review for '{cl['id']}'")
            else:
                print(f"Checklist review for '{cl['id']}' is already up to date")
        else:
            pr.create_review(body=body, event="COMMENT")
            print(f"Created checklist review for '{cl['id']}'")

    # Set a pending status — actual pass/fail is determined by check_acknowledgements.
    set_commit_status(
        repo,
        pr.head.sha,
        "pending",
        f"{len(relevant)} checklist(s) require reviewer acknowledgement",
    )

    print(f"Posted/updated {len(relevant)} checklist review(s).")


if __name__ == "__main__":
    main()

