# *******************************************************************************
# Copyright (c) 2026 Contributors to the Eclipse Foundation
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
load("@review_checklists_pip//:requirements.bzl", "requirement")
load("@rules_python//python:defs.bzl", "py_binary", "py_library", "py_test")

py_library(
    name = "helpers",
    srcs = ["helpers.py"],
    data = ["//actions/review-checklists:checklists_config"],
    imports = ["."],
    visibility = ["//actions/review-checklists:__subpackages__"],
    deps = [
        requirement("bazel-runfiles"),
        requirement("pygithub"),
        requirement("pyyaml"),
    ],
)

py_library(
    name = "post_checklists_lib",
    srcs = ["post_checklists.py"],
    imports = ["."],
    deps = [":helpers"],
)

py_library(
    name = "check_acknowledgements_lib",
    srcs = ["check_acknowledgements.py"],
    imports = ["."],
    deps = [":helpers"],
)

py_library(
    name = "dismiss_and_invalidate_lib",
    srcs = ["dismiss_and_invalidate.py"],
    imports = ["."],
    deps = [":helpers"],
)

py_library(
    name = "merge_evidence_commit_lib",
    srcs = ["merge_evidence_commit.py"],
    imports = ["."],
    deps = [":helpers"],
)

py_binary(
    name = "post_checklists",
    srcs = ["post_checklists.py"],
    main = "post_checklists.py",
    visibility = ["//visibility:public"],
    deps = [":helpers"],
)

py_binary(
    name = "check_acknowledgements",
    srcs = ["check_acknowledgements.py"],
    main = "check_acknowledgements.py",
    visibility = ["//visibility:public"],
    deps = [":helpers"],
)

py_binary(
    name = "dismiss_and_invalidate",
    srcs = ["dismiss_and_invalidate.py"],
    main = "dismiss_and_invalidate.py",
    visibility = ["//visibility:public"],
    deps = [":helpers"],
)

py_binary(
    name = "merge_evidence_commit",
    srcs = ["merge_evidence_commit.py"],
    main = "merge_evidence_commit.py",
    visibility = ["//visibility:public"],
    deps = [":helpers"],
)

py_test(
    name = "helpers_test",
    srcs = ["helpers_test.py"],
    imports = ["."],
    deps = [
        ":helpers",
        requirement("pytest"),
    ],
)

py_test(
    name = "post_checklists_test",
    srcs = ["post_checklists_test.py"],
    imports = ["."],
    deps = [
        ":post_checklists_lib",
        requirement("pytest"),
    ],
)

py_test(
    name = "check_acknowledgements_test",
    srcs = ["check_acknowledgements_test.py"],
    imports = ["."],
    deps = [
        ":check_acknowledgements_lib",
        requirement("pytest"),
    ],
)

py_test(
    name = "dismiss_and_invalidate_test",
    srcs = ["dismiss_and_invalidate_test.py"],
    imports = ["."],
    deps = [
        ":dismiss_and_invalidate_lib",
        requirement("pytest"),
    ],
)

py_test(
    name = "merge_evidence_commit_test",
    srcs = ["merge_evidence_commit_test.py"],
    imports = ["."],
    deps = [
        ":merge_evidence_commit_lib",
        requirement("pytest"),
    ],
)
