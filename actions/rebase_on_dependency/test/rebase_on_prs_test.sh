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

# Unit tests for rebase_on_prs.sh
# These tests use mocked gh and git commands

set -euo pipefail

# --- begin runfiles.bash initialization ---
if [[ ! -d "${RUNFILES_DIR:-/dev/null}" && ! -f "${RUNFILES_MANIFEST_FILE:-/dev/null}" ]]; then
  if [[ -f "$0.runfiles_manifest" ]]; then
    export RUNFILES_MANIFEST_FILE="$0.runfiles_manifest"
  elif [[ -f "$0.runfiles/MANIFEST" ]]; then
    export RUNFILES_MANIFEST_FILE="$0.runfiles/MANIFEST"
  elif [[ -f "$0.runfiles/bazel_tools/tools/bash/runfiles/runfiles.bash" ]]; then
    export RUNFILES_DIR="$0.runfiles"
  fi
fi
if [[ -f "${RUNFILES_DIR:-/dev/null}/bazel_tools/tools/bash/runfiles/runfiles.bash" ]]; then
  source "${RUNFILES_DIR}/bazel_tools/tools/bash/runfiles/runfiles.bash"
elif [[ -f "${RUNFILES_MANIFEST_FILE:-/dev/null}" ]]; then
  source "$(grep -m1 "^bazel_tools/tools/bash/runfiles/runfiles.bash " \
            "$RUNFILES_MANIFEST_FILE" | cut -d ' ' -f 2-)"
else
  echo >&2 "ERROR: cannot find @bazel_tools//tools/bash/runfiles:runfiles.bash"
  exit 1
fi
# --- end runfiles.bash initialization ---

# Test counters
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

# Create mock directory
MOCK_DIR="$(mktemp -d)"
export PATH="$MOCK_DIR:$PATH"
export GH_TOKEN="mock-token"

# Cleanup on exit
cleanup() {
    rm -rf "$MOCK_DIR"
}
trap cleanup EXIT

# Source the script under test
source "$(rlocation "${TEST_WORKSPACE}/actions/rebase_on_dependency/scripts/rebase_on_prs.sh")"

# Assert functions
assert_equals() {
    local expected="$1"
    local actual="$2"
    local test_name="$3"

    TESTS_RUN=$((TESTS_RUN + 1))

    if [[ "$expected" == "$actual" ]]; then
        echo -e "${GREEN}✓ PASS${NC}: $test_name"
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        echo -e "${RED}✗ FAIL${NC}: $test_name"
        echo "  Expected: '$expected'"
        echo "  Actual:   '$actual'"
        TESTS_FAILED=$((TESTS_FAILED + 1))
    fi
}

assert_status() {
    local expected="$1"
    local actual="$2"
    local test_name="$3"

    TESTS_RUN=$((TESTS_RUN + 1))

    if [[ "$expected" -eq "$actual" ]]; then
        echo -e "${GREEN}✓ PASS${NC}: $test_name"
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        echo -e "${RED}✗ FAIL${NC}: $test_name"
        echo "  Expected status: $expected"
        echo "  Actual status:   $actual"
        TESTS_FAILED=$((TESTS_FAILED + 1))
    fi
}

assert_contains() {
    local needle="$1"
    local haystack="$2"
    local test_name="$3"

    TESTS_RUN=$((TESTS_RUN + 1))

    if [[ "$haystack" == *"$needle"* ]]; then
        echo -e "${GREEN}✓ PASS${NC}: $test_name"
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        echo -e "${RED}✗ FAIL${NC}: $test_name"
        echo "  Expected to contain: '$needle'"
        echo "  Actual: '$haystack'"
        TESTS_FAILED=$((TESTS_FAILED + 1))
    fi
}

# Helper to create a mock gh command
create_gh_mock() {
    local script_content="$1"
    cat > "$MOCK_DIR/gh" << EOF
#!/usr/bin/env bash
$script_content
EOF
    chmod +x "$MOCK_DIR/gh"
}

# Helper to create a mock git command
create_git_mock() {
    local script_content="$1"
    cat > "$MOCK_DIR/git" << EOF
#!/usr/bin/env bash
$script_content
EOF
    chmod +x "$MOCK_DIR/git"
}

# ============================================================================
# Tests for get_pr_field function
# ============================================================================

echo "Testing get_pr_field function..."
echo ""

# Test: Returns branch name for valid PR
create_gh_mock 'echo "feature-branch"'
result=$(get_pr_field "123" "headRefName")
assert_equals "feature-branch" "$result" "get_pr_field: returns branch name for valid PR"

# Test: Returns empty for invalid PR
create_gh_mock 'exit 1'
result=$(get_pr_field "999" "headRefName")
assert_equals "" "$result" "get_pr_field: returns empty for invalid PR"

# Test: Returns state for PR
create_gh_mock 'echo "OPEN"'
result=$(get_pr_field "123" "state")
assert_equals "OPEN" "$result" "get_pr_field: returns state for PR"

# ============================================================================
# Tests for rebase_on_pr function
# ============================================================================

echo ""
echo "Testing rebase_on_pr function..."
echo ""

# Test: Successful rebase returns 0
create_gh_mock '
if [[ "$5" == "headRefName" ]]; then
    echo "feature-branch"
elif [[ "$5" == "state" ]]; then
    echo "OPEN"
fi
'
create_git_mock 'exit 0'
set +e
output=$(rebase_on_pr "123" 2>&1)
status=$?
set -e
assert_status 0 "$status" "rebase_on_pr: successful rebase returns 0"

# Test: Merged PR returns 1 (skip)
create_gh_mock '
if [[ "$5" == "headRefName" ]]; then
    echo "feature-branch"
elif [[ "$5" == "state" ]]; then
    echo "MERGED"
fi
'
set +e
output=$(rebase_on_pr "123" 2>&1)
status=$?
set -e
assert_status 1 "$status" "rebase_on_pr: merged PR returns 1 (skip)"
assert_contains "has been merged" "$output" "rebase_on_pr: merged PR shows correct message"

# Test: Closed PR returns 1 (skip)
create_gh_mock '
if [[ "$5" == "headRefName" ]]; then
    echo "feature-branch"
elif [[ "$5" == "state" ]]; then
    echo "CLOSED"
fi
'
set +e
output=$(rebase_on_pr "123" 2>&1)
status=$?
set -e
assert_status 1 "$status" "rebase_on_pr: closed PR returns 1 (skip)"
assert_contains "closed but not merged" "$output" "rebase_on_pr: closed PR shows correct message"

# Test: PR not found returns 2 (failure)
create_gh_mock 'echo ""'
set +e
output=$(rebase_on_pr "999" 2>&1)
status=$?
set -e
assert_status 2 "$status" "rebase_on_pr: PR not found returns 2 (failure)"
assert_contains "Could not fetch branch name" "$output" "rebase_on_pr: PR not found shows correct message"

# Test: Rebase conflict returns 2 (failure)
create_gh_mock '
if [[ "$5" == "headRefName" ]]; then
    echo "feature-branch"
elif [[ "$5" == "state" ]]; then
    echo "OPEN"
fi
'
create_git_mock '
if [[ "$1" == "fetch" ]]; then
    exit 0
elif [[ "$1" == "rebase" && "$2" != "--abort" ]]; then
    exit 1
elif [[ "$1" == "rebase" && "$2" == "--abort" ]]; then
    exit 0
elif [[ "$1" == "config" ]]; then
    exit 0
fi
'
set +e
output=$(rebase_on_pr "123" 2>&1)
status=$?
set -e
assert_status 2 "$status" "rebase_on_pr: rebase conflict returns 2 (failure)"
assert_contains "Rebase failed" "$output" "rebase_on_pr: rebase conflict shows correct message"

# ============================================================================
# Tests for main function
# ============================================================================

echo ""
echo "Testing main function..."
echo ""

# Test: Single successful rebase
create_gh_mock '
if [[ "$5" == "headRefName" ]]; then
    echo "feature-branch"
elif [[ "$5" == "state" ]]; then
    echo "OPEN"
fi
'
create_git_mock 'exit 0'
set +e
output=$(main "123" 2>&1)
status=$?
set -e
assert_status 0 "$status" "main: single successful rebase returns 0"
assert_contains "rebased=true" "$output" "main: single successful rebase sets rebased=true"
assert_contains "rebased_count=1" "$output" "main: single successful rebase sets rebased_count=1"

# Test: All PRs merged - no rebase needed
create_gh_mock '
if [[ "$5" == "headRefName" ]]; then
    echo "feature-branch"
elif [[ "$5" == "state" ]]; then
    echo "MERGED"
fi
'
set +e
output=$(main "123,456" 2>&1)
status=$?
set -e
assert_status 0 "$status" "main: all PRs merged returns 0"
assert_contains "rebased=false" "$output" "main: all PRs merged sets rebased=false"
assert_contains "rebased_count=0" "$output" "main: all PRs merged sets rebased_count=0"

# Test: One PR fails - returns error
create_gh_mock 'echo ""'
set +e
output=$(main "999" 2>&1)
status=$?
set -e
assert_status 1 "$status" "main: PR not found returns 1"
assert_contains "failed_prs=999" "$output" "main: PR not found sets failed_prs"

# ============================================================================
# Summary
# ============================================================================

echo ""
echo "=========================================="
echo "Test Summary"
echo "=========================================="
echo "Tests run:    $TESTS_RUN"
echo -e "Tests passed: ${GREEN}$TESTS_PASSED${NC}"
echo -e "Tests failed: ${RED}$TESTS_FAILED${NC}"
echo ""

if [[ $TESTS_FAILED -gt 0 ]]; then
    echo -e "${RED}SOME TESTS FAILED${NC}"
    exit 1
else
    echo -e "${GREEN}ALL TESTS PASSED${NC}"
    exit 0
fi

