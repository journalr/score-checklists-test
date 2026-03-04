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

"""Invalidate OK acknowledgements.

This script handles two scenarios:

1. **New push (synchronize)**: When new commits are pushed to the PR, we
   determine which checklist paths are affected by the *new* changes.  For
   each affected checklist, all existing OK replies are deleted and the
   commit status is set back to pending.  Approvals are **not** dismissed
   here — branch rulesets handle dismissing stale reviews on new pushes.

2. **OK modified or deleted**: When a reviewer edits or deletes their OK
   comment, the commit status is set back to pending so the checklist
   must be re-acknowledged.  The reviewer's approval is **not** dismissed.

The script is invoked with a ``--trigger`` argument:

    python dismiss_and_invalidate.py --trigger synchronize
    python dismiss_and_invalidate.py --trigger comment_changed
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any

from helpers import (
    OK_KEYWORD,
    find_existing_checklist_comments,
    get_changed_files,
    get_github_client,
    get_repo_and_pr,
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


def _find_ok_comments_for_checklist(
    pr: Any, checklist_id: str, checklist_comment_id: int
) -> list[Any]:
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


def handle_synchronize(pr: Any) -> None:
    """Handle new commits pushed to the PR.

    For each checklist whose covered paths were touched by the new push,
    delete all OK replies and set the commit status back to pending.
    Approvals are not dismissed — branch rulesets handle that.
    """
    checklists = load_checklists()
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
        ok_comments = _find_ok_comments_for_checklist(pr, cid, review.id)

        for ok_comment in ok_comments:
            user = ok_comment.user.login
            any_invalidated = True
            try:
                ok_comment.delete()
                print(
                    f"Deleted OK comment {ok_comment.id} from {user} "
                    f"for checklist '{cid}'"
                )
            except Exception as e:
                print(
                    f"Warning: could not delete comment {ok_comment.id}: {e}"
                )

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


def handle_comment_changed(pr: Any) -> None:
    """Handle an OK comment being edited or deleted.

    When a reviewer modifies or removes their OK, set the commit status
    back to pending.  The reviewer's approval is preserved.
    """
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    if not event_path:
        print("No event payload available.")
        return

    with open(event_path) as f:
        event = json.load(f)

    comment_body = event.get("comment", {}).get("body", "")
    comment_user = event.get("comment", {}).get("user", {}).get("login", "")
    action = event.get("action", "")

    if not comment_user:
        print("Could not determine comment author.")
        return

    # Check if this was an OK-related comment.
    was_ok = False
    if action == "deleted":
        # For deleted comments the body is the content at time of deletion.
        was_ok = comment_body.strip().upper() == OK_KEYWORD
    elif action == "edited":
        old_body = (
            event.get("changes", {}).get("body", {}).get("from", "")
        )
        # If old body was OK but new body is not, this is a retraction.
        old_is_ok = old_body.strip().upper() == OK_KEYWORD
        new_is_ok = comment_body.strip().upper() == OK_KEYWORD
        was_ok = old_is_ok and not new_is_ok

    if was_ok:
        print(
            f"Checklist OK retracted by {comment_user} "
            f"(approval preserved)"
        )

        repo_name = os.environ["GITHUB_REPOSITORY"]
        gh = get_github_client()
        repo = gh.get_repo(repo_name)
        set_commit_status(
            repo,
            pr.head.sha,
            "pending",
            f"Checklist OK retracted by {comment_user}",
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Invalidate OK acknowledgements."
    )
    parser.add_argument(
        "--trigger",
        required=True,
        choices=["synchronize", "comment_changed"],
        help="The event trigger type.",
    )
    args = parser.parse_args()

    gh = get_github_client()
    _, pr = get_repo_and_pr(gh)

    if args.trigger == "synchronize":
        handle_synchronize(pr)
    elif args.trigger == "comment_changed":
        handle_comment_changed(pr)


if __name__ == "__main__":
    main()

