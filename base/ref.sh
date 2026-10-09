#!/bin/bash
#
# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Print the content-addressed tag of the client image: "<client version>-<recipe hash8>".
#
# The hash covers the recipe (Containerfile, vendor/, overlay/) with relative paths only, so both
# architectures compute the same value; the client version comes from that architecture's
# build-args file, so a version bump or any recipe change produces a new tag and a rebuild, while
# an unchanged recipe reuses the published image (which is what publish.yml keys on).
#
# Usage: base/ref.sh [amd64|arm64]
set -euo pipefail

arch="${1:-amd64}"
root="$(dirname "$(readlink -f "$0")")"
version="$(sed -n 's/^ATRUST_VERSION=//p' "$root/build-args/$arch.args")"
[ -n "$version" ] || { echo "no ATRUST_VERSION in $root/build-args/$arch.args" >&2; exit 1; }
hash="$(cd "$root" && find Containerfile vendor overlay -type f -print0 \
        | sort -z | xargs -0 sha256sum | sha256sum | cut -c1-8)"
printf '%s-%s\n' "$version" "$hash"
