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

"""Dismiss approvals and invalidate OK acknowledgements.

This script handles two scenarios:

1. **New push (synchronize)**: When new commits are pushed to the PR, we
   determine which checklist paths are affected by the *new* changes.  For
   each affected checklist, all existing OK replies are deleted and any
   approvals from those reviewers are dismissed.

2. **OK modified or deleted**: When a reviewer edits or deletes their OK
   comment, the corresponding reviewer's approval is dismissed.

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
    OK_MARKER,
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
    matches the checklist comment id.
    """
    ok_comments = []
    marker = OK_MARKER.format(checklist_id=checklist_id)

    for comment in pr.get_review_comments():
        reply_to = getattr(comment, "in_reply_to_id", None)
        if reply_to != checklist_comment_id:
            continue
        body = (comment.body or "").strip()

        # Explicit marker match.
        if marker in body:
            ok_comments.append(comment)
            continue

        # Bare OK keyword.
        if body.upper() == OK_KEYWORD:
            ok_comments.append(comment)

    return ok_comments


def _dismiss_approval(pr: Any, username: str) -> None:
    """Dismiss the latest approval from the given user on the PR."""
    for review in reversed(list(pr.get_reviews())):
        if review.user.login == username and review.state == "APPROVED":
            review.dismiss(
                "Approval dismissed: review-checklist acknowledgement "
                "was invalidated due to new changes or modified OK."
            )
            print(f"Dismissed approval from {username} (review {review.id})")
            return
    print(f"No active approval found for {username} to dismiss")


def handle_synchronize(pr: Any) -> None:
    """Handle new commits pushed to the PR.

    For each checklist whose covered paths were touched by the new push,
    delete all OK replies and dismiss approvals from those reviewers.
    """
    checklists = load_checklists()
    new_files = _get_files_in_latest_push(pr)
    affected = match_checklists(checklists, new_files)

    if not affected:
        print("No checklist-relevant files changed in latest push.")
        return

    existing = find_existing_checklist_comments(pr)

    invalidated_users: set[str] = set()

    for cl in affected:
        cid = cl["id"]
        if cid not in existing:
            continue

        review = existing[cid]
        ok_comments = _find_ok_comments_for_checklist(pr, cid, review.id)

        for ok_comment in ok_comments:
            user = ok_comment.user.login
            invalidated_users.add(user)
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

    # Dismiss approvals from all invalidated users.
    for user in invalidated_users:
        _dismiss_approval(pr, user)

    if invalidated_users:
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

    When a reviewer modifies or removes their OK, dismiss their approval.
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
        deleted_body = comment_body.strip()
        was_ok = (
            deleted_body.upper() == OK_KEYWORD
            or "checklist-ok:" in deleted_body
        )
    elif action == "edited":
        old_body = (
            event.get("changes", {}).get("body", {}).get("from", "")
        )
        # If old body was OK-like but new body is not, this is a retraction.
        old_is_ok = old_body.strip().upper() == OK_KEYWORD or "checklist-ok:" in old_body
        new_is_ok = comment_body.strip().upper() == OK_KEYWORD or "checklist-ok:" in comment_body
        was_ok = old_is_ok and not new_is_ok

    if was_ok:
        _dismiss_approval(pr, comment_user)
        print(f"Dismissed approval for {comment_user} due to modified/deleted OK")

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
        description="Dismiss approvals and invalidate OK acknowledgements."
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

