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

"""Invalidate OK acknowledgements after new commits are pushed to a PR.

For the ``synchronize`` trigger, this script determines which checklists are
affected by newly pushed changes, deletes existing OK replies for those
checklists, and sets commit status back to pending.
"""

from __future__ import annotations

import argparse
import os
from typing import Any

from helpers import (
    OK_KEYWORD,
    ensure_merge_queue_notice_comment,
    ensure_merge_queue_notice_description,
    find_existing_checklist_comments,
    get_changed_files,
    get_github_client,
    get_repo_and_pr,
    is_pr_in_merge_queue,
    load_checklists,
    match_checklists,
    set_commit_status,
)


def _get_files_in_latest_push(pr: Any) -> list[str]:
    """Return files changed in the most recent push to the PR.

    For the ``synchronize`` event we ideally look at only the files changed
    in the new commits.  The GitHub event payload provides ``before`` and
    ``after`` SHAs which can be compared.  As a practical fallback we use
    the full PR changed-file list.
    """
    before_sha = os.environ.get("BEFORE_SHA", "")
    after_sha = os.environ.get("AFTER_SHA", "")

    if before_sha and after_sha:
        repo_name = os.environ["GITHUB_REPOSITORY"]
        gh = get_github_client()
        repo = gh.get_repo(repo_name)
        comparison = repo.compare(before_sha, after_sha)
        return [f.filename for f in comparison.files]

    # Fallback: treat all PR files as potentially changed.
    return get_changed_files(pr)


def _find_ok_comments_for_checklist(pr: Any, checklist_comment_id: int) -> list[Any]:
    """Find all OK reply comments for a given checklist.

    Checklist findings are posted as file-level PR review comments; OK
    replies are threaded review comment replies whose ``in_reply_to_id``
    matches the checklist comment id and whose body equals the OK keyword.
    """
    ok_comments = []

    for comment in pr.get_review_comments():
        reply_to = getattr(comment, "in_reply_to_id", None)
        if reply_to != checklist_comment_id:
            continue
        body = (comment.body or "").strip()

        if body.upper() == OK_KEYWORD:
            ok_comments.append(comment)

    return ok_comments


def handle_synchronize(pr: Any, config_path: str) -> None:
    """Handle new commits pushed to the PR.

    For each checklist whose covered paths were touched by the new push,
    delete all OK replies and set the commit status back to pending.
    Approvals are not dismissed — branch rulesets handle that.
    """
    checklists = load_checklists(config_path)
    new_files = _get_files_in_latest_push(pr)
    affected = match_checklists(checklists, new_files)

    if not affected:
        print("No checklist-relevant files changed in latest push.")
        return

    existing = find_existing_checklist_comments(pr)

    any_invalidated = False

    for cl in affected:
        cid = cl["id"]
        if cid not in existing:
            continue

        review = existing[cid]
        ok_comments = _find_ok_comments_for_checklist(pr, review.id)

        for ok_comment in ok_comments:
            user = ok_comment.user.login
            any_invalidated = True
            try:
                ok_comment.delete()
                print(
                    f"Deleted OK comment {ok_comment.id} from {user} "
                    f"for checklist '{review.id}'"
                )
            except Exception as e:
                print(f"Warning: could not delete comment {ok_comment.id}: {e}")

    if any_invalidated:
        repo_name = os.environ["GITHUB_REPOSITORY"]
        gh = get_github_client()
        repo = gh.get_repo(repo_name)
        set_commit_status(
            repo,
            pr.head.sha,
            "pending",
            "Checklist acknowledgements invalidated due to new changes",
        )

    if is_pr_in_merge_queue(pr):
        ensure_merge_queue_notice_comment(pr)
        ensure_merge_queue_notice_description(pr)


def main() -> None:
    parser = argparse.ArgumentParser(description="Invalidate OK acknowledgements.")
    parser.add_argument(
        "--trigger",
        required=True,
        choices=["synchronize"],
        help="The event trigger type.",
    )
    parser.add_argument(
        "--config-path",
        default=".github/review_checklists.yml",
        help="Path to checklist configuration file (default: .github/review_checklists.yml)",
    )
    args = parser.parse_args()

    gh = get_github_client()
    _, pr = get_repo_and_pr(gh)

    handle_synchronize(pr, args.config_path)


if __name__ == "__main__":
    main()
