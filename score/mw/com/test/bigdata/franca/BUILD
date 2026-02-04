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

filegroup(
    name = "bigdata-secpol",
    srcs = select({
        "//bazel/platforms/settings:arm64-qnx-virtual": ["bigdata-virtual.secpol"],
        "//conditions:default": [
            "bigdata.secpol",
        ],
    }),
    visibility = [
        "//pqr/abc/abc-lmn/config/common/os/bsw/qnx-secpol:__pkg__",
        "//pqr/abc/abc-lmn/config/project/cpu/os:__subpackages__",
        # "@xyz//pqr/abc/abc-lmn/config/common/os/bsw/qnx-secpol:__pkg__",
        # "@xyz//pqr/abc/abc-lmn/config/project/cpu/os:__subpackages__",
    ],
)
