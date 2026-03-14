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

# find_dependencies.sh
# Parses a PR description and extracts Depends-On: references
#
# Usage: find_dependencies.sh <pr_body>
# Output: Comma-separated list of PR numbers, or empty string if none found

set -euo pipefail

# Parse Depends-On patterns from PR body text
# Supports formats: "Depends-On: #123", "Depends-On: 123", "Depends-On:#123"
# Case insensitive
parse_depends_on() {
    local pr_body="$1"

    if [[ -z "$pr_body" ]]; then
        echo ""
        return 0
    fi

    local dependency_prs
    dependency_prs=$(echo "$pr_body" | grep -ioE 'Depends-On:[[:space:]]*#?[0-9]+' | grep -oE '[0-9]+' | tr '\n' ',' | sed 's/,$//' || echo "")

    echo "$dependency_prs"
}

# Count the number of dependencies in a comma-separated list
count_dependencies() {
    local dependency_list="$1"

    if [[ -z "$dependency_list" ]]; then
        echo "0"
        return 0
    fi

    echo "$dependency_list" | tr ',' '\n' | wc -l | tr -d ' '
}

# Main execution when script is run directly (not sourced)
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    if [[ $# -lt 1 ]]; then
        echo "Usage: $0 <pr_body>" >&2
        exit 1
    fi

    PR_BODY="$1"
    DEPENDENCY_PRS=$(parse_depends_on "$PR_BODY")
    DEPENDENCY_COUNT=$(count_dependencies "$DEPENDENCY_PRS")

    echo "dependency_prs=${DEPENDENCY_PRS}"
    echo "dependency_count=${DEPENDENCY_COUNT}"
fi

