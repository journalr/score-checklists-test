#!/usr/bin/env bash

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

# rebase_on_prs.sh
# Rebases the current branch onto dependency PR branches
#
# Usage: rebase_on_prs.sh <comma_separated_pr_numbers>
# Requires: GH_TOKEN environment variable for GitHub CLI authentication
# Output: Sets outputs for rebased status and counts

set -euo pipefail

# Get PR information using GitHub CLI
# Arguments: pr_number, json_field
get_pr_field() {
    local pr_number="$1"
    local field="$2"
    gh pr view "$pr_number" --json "$field" --jq ".$field" 2>/dev/null || echo ""
}

# Perform rebase onto a single PR
# Arguments: pr_number
# Returns: 0 on success, 1 on skip, 2 on failure
rebase_on_pr() {
    local pr_number="$1"

    echo ""
    echo "=========================================="
    echo "Processing dependency PR #${pr_number}..."
    echo "=========================================="

    # Get the head ref (branch name) of the dependency PR
    local dependency_branch
    dependency_branch=$(get_pr_field "$pr_number" "headRefName")

    if [[ -z "$dependency_branch" ]]; then
        echo "::error::Could not fetch branch name for PR #${pr_number}. Make sure the PR exists and is open."
        return 2
    fi

    echo "Dependency PR branch: ${dependency_branch}"

    # Check if the dependency PR is still open
    local dependency_state
    dependency_state=$(get_pr_field "$pr_number" "state")

    if [[ "$dependency_state" == "MERGED" ]]; then
        echo "Dependency PR #${pr_number} has been merged. Skipping."
        return 1
    fi

    if [[ "$dependency_state" == "CLOSED" ]]; then
        echo "::warning::Dependency PR #${pr_number} is closed but not merged. Consider removing the Depends-On reference."
        return 1
    fi

    # Fetch the dependency branch
    echo "Fetching dependency branch..."
    git fetch origin "${dependency_branch}:refs/remotes/origin/${dependency_branch}"

    # Perform the rebase
    echo "Rebasing current branch onto origin/${dependency_branch}..."
    if git rebase "origin/${dependency_branch}"; then
        echo "Rebase onto PR #${pr_number} successful!"
        return 0
    else
        echo "::error::Rebase failed for PR #${pr_number}. There may be conflicts."
        git rebase --abort || true
        return 2
    fi
}

# Main execution
main() {
    local dependency_prs="$1"
    local rebased_count=0
    local skipped_prs=""
    local failed_prs=""

    # Configure git user for the rebase
    git config user.name "github-actions[bot]"
    git config user.email "github-actions[bot]@users.noreply.github.com"

    # Process each dependency PR
    IFS=',' read -ra pr_array <<< "$dependency_prs"
    for pr_number in "${pr_array[@]}"; do
        local result=0
        rebase_on_pr "$pr_number" || result=$?

        case $result in
            0)
                rebased_count=$((rebased_count + 1))
                ;;
            1)
                skipped_prs="${skipped_prs}${pr_number},"
                ;;
            2)
                failed_prs="${failed_prs}${pr_number},"
                ;;
        esac
    done

    # Output results
    if [[ $rebased_count -gt 0 ]]; then
        echo "rebased=true"
    else
        echo "rebased=false"
    fi
    echo "rebased_count=${rebased_count}"
    echo "skipped_prs=${skipped_prs%,}"
    echo "failed_prs=${failed_prs%,}"

    echo ""
    echo "=========================================="
    echo "Summary: Rebased onto ${rebased_count} PR(s)"
    if [[ -n "$skipped_prs" ]]; then
        echo "Skipped: ${skipped_prs%,}"
    fi
    if [[ -n "$failed_prs" ]]; then
        echo "Failed: ${failed_prs%,}"
        return 1
    fi
    echo "=========================================="
    return 0
}

# Run main if script is executed directly (not sourced)
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    if [[ $# -lt 1 ]]; then
        echo "Usage: $0 <comma_separated_pr_numbers>" >&2
        exit 1
    fi

    main "$1"
fi

