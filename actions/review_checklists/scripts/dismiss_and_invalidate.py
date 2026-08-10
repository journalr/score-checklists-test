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

"""Invalidate OK acknowledgements after a new push.

When new commits are pushed to the PR, this script determines which
checklist paths are affected by the *new* changes.  For each affected
checklist, all existing OK replies are deleted and the commit status is
set back to pending.  Approvals are **not** dismissed here — branch
rulesets handle dismissing stale reviews on new pushes.

(OK-comment edits/deletions no longer need dedicated handling here: the
"check" action already re-scans the current comment state on every
invocation, so an edited/deleted OK comment is naturally no longer
counted the next time acknowledgements are checked.)

The "files changed in the latest push" are found without needing the
``before``/``after`` SHAs from the original event payload: this script
looks up the previous run of the "Review Checklists (Trigger)" workflow
for the same head branch (ordered by run creation time) and uses that
run's head SHA as the "before" commit.  This keeps stage 1 → stage 2 data
transfer minimal while still comparing against exactly the commits
introduced by this push.
"""

from __future__ import annotations

import argparse
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

TRIGGER_WORKFLOW_FILE = "review_checklists_trigger.yml"
TRIGGER_EVENT_NAME = "pull_request_target"


def _get_files_in_latest_push(pr: Any, repo: Any) -> list[str]:
    """Return files changed in the most recent push to the PR.

    Finds the "before" SHA by locating the trigger-workflow run that
    immediately preceded the current one for this head branch, and
    compares it against the current head.  Falls back to the full PR
    changed-file list if the previous run cannot be found.
    """
    run_id_raw = os.environ.get("CURRENT_RUN_ID", "")
    head_branch = os.environ.get("HEAD_BRANCH", "")

    if run_id_raw and head_branch:
        try:
            run_id = int(run_id_raw)
            workflow = repo.get_workflow(TRIGGER_WORKFLOW_FILE)
            runs = list(
                workflow.get_runs(branch=head_branch, event=TRIGGER_EVENT_NAME)
            )
            run_ids = [r.id for r in runs]
            idx = run_ids.index(run_id)
            before_sha = runs[idx + 1].head_sha
            comparison = repo.compare(before_sha, pr.head.sha)
            return [f.filename for f in comparison.files]
        except (ValueError, IndexError) as e:
            print(f"Could not resolve previous push via run history: {e}")
        except Exception as e:
            print(f"Warning: could not resolve latest-push diff: {e}")

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


def handle_synchronize(pr: Any, repo: Any, config_path: str) -> None:
    """Handle new commits pushed to the PR.

    For each checklist whose covered paths were touched by the new push,
    delete all OK replies and set the commit status back to pending.
    Approvals are not dismissed — branch rulesets handle that.
    """
    checklists = load_checklists(config_path)
    new_files = _get_files_in_latest_push(pr, repo)
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
        set_commit_status(
            repo,
            pr.head.sha,
            "pending",
            "Checklist acknowledgements invalidated due to new changes",
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Invalidate OK acknowledgements after a new push."
    )
    parser.add_argument(
        "--config-path",
        default=".github/review_checklists.yml",
        help="Path to checklist configuration file (default: .github/review_checklists.yml)",
    )
    args = parser.parse_args()

    gh = get_github_client()
    repo, pr = get_repo_and_pr(gh)
    handle_synchronize(pr, repo, args.config_path)


if __name__ == "__main__":
    main()
