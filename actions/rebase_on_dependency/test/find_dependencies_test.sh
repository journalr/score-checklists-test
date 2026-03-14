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

# Unit tests for find_dependencies.sh

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

# Source the script under test
source "$(rlocation "${TEST_WORKSPACE}/actions/rebase_on_dependency/scripts/find_dependencies.sh")"

# Test counters
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

# Assert function
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

# ============================================================================
# Tests for parse_depends_on function
# ============================================================================

echo "Testing parse_depends_on function..."
echo ""

# Test: Single dependency with hash
input="This PR depends on another one.

Depends-On: #123

More description."
result=$(parse_depends_on "$input")
assert_equals "123" "$result" "Single dependency with hash"

# Test: Single dependency without hash
result=$(parse_depends_on "Depends-On: 456")
assert_equals "456" "$result" "Single dependency without hash"

# Test: Single dependency with hash, no space
result=$(parse_depends_on "Depends-On:#789")
assert_equals "789" "$result" "Single dependency with hash, no space"

# Test: Multiple dependencies
input="This PR has multiple deps.
Depends-On: #100
Depends-On: #200
Depends-On: #300"
result=$(parse_depends_on "$input")
assert_equals "100,200,300" "$result" "Multiple dependencies"

# Test: Multiple dependencies with mixed formats
input="Depends-On: #111
Depends-On: 222
Depends-On:#333"
result=$(parse_depends_on "$input")
assert_equals "111,222,333" "$result" "Multiple dependencies with mixed formats"

# Test: Case insensitivity - lowercase
result=$(parse_depends_on "depends-on: #555")
assert_equals "555" "$result" "Case insensitivity - lowercase"

# Test: Case insensitivity - uppercase
result=$(parse_depends_on "DEPENDS-ON: #666")
assert_equals "666" "$result" "Case insensitivity - uppercase"

# Test: Case insensitivity - mixed case
result=$(parse_depends_on "DePeNdS-On: #777")
assert_equals "777" "$result" "Case insensitivity - mixed case"

# Test: No dependencies in description
result=$(parse_depends_on "This is a normal PR description without any dependencies.")
assert_equals "" "$result" "No dependencies in description"

# Test: Empty description
result=$(parse_depends_on "")
assert_equals "" "$result" "Empty description"

# Test: Dependencies with extra whitespace
result=$(parse_depends_on "Depends-On:    #888")
assert_equals "888" "$result" "Dependencies with extra whitespace"

# Test: Dependencies in markdown list
input="## Dependencies
- Depends-On: #999
- Depends-On: #1000"
result=$(parse_depends_on "$input")
assert_equals "999,1000" "$result" "Dependencies in markdown list"

# Test: Dependencies with surrounding text on same line
result=$(parse_depends_on "Please merge Depends-On: #1111 first before this one")
assert_equals "1111" "$result" "Dependencies with surrounding text"

# Test: Large PR numbers
result=$(parse_depends_on "Depends-On: #99999")
assert_equals "99999" "$result" "Large PR numbers"

# Test: Partial match - no closing number returns empty
result=$(parse_depends_on "Depends-On:")
assert_equals "" "$result" "Partial match - no closing number"

# Test: Invalid format - number before keyword returns empty
result=$(parse_depends_on "123 Depends-On")
assert_equals "" "$result" "Invalid format - number before keyword"

# ============================================================================
# Tests for count_dependencies function
# ============================================================================

echo ""
echo "Testing count_dependencies function..."
echo ""

# Test: Empty string returns 0
result=$(count_dependencies "")
assert_equals "0" "$result" "count_dependencies: empty string returns 0"

# Test: Single dependency returns 1
result=$(count_dependencies "123")
assert_equals "1" "$result" "count_dependencies: single dependency returns 1"

# Test: Multiple dependencies returns correct count
result=$(count_dependencies "100,200,300")
assert_equals "3" "$result" "count_dependencies: multiple dependencies returns 3"

# Test: Two dependencies returns 2
result=$(count_dependencies "111,222")
assert_equals "2" "$result" "count_dependencies: two dependencies returns 2"

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

