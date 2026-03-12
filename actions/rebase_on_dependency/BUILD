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

filegroup(
    name = "scripts",
    srcs = glob(["scripts/*.sh"]),
    visibility = ["//visibility:public"],
)

sh_test(
    name = "find_dependencies_test",
    srcs = ["test/find_dependencies_test.sh"],
    data = ["scripts/find_dependencies.sh"],
    deps = ["@bazel_tools//tools/bash/runfiles"],
)

sh_test(
    name = "rebase_on_prs_test",
    srcs = ["test/rebase_on_prs_test.sh"],
    data = ["scripts/rebase_on_prs.sh"],
    deps = ["@bazel_tools//tools/bash/runfiles"],
)

