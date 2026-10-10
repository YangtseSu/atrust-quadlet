#!/usr/bin/env python3
#
# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Delete the versions of the GHCR package that no tag resolves to any more.

Called by .github/workflows/prune-packages.yml (manual only, `dry_run` true by default) and
runnable by hand for the very same reason - to see what a run would delete before one does:

    GH_TOKEN=$(gh auth token) GITHUB_REPOSITORY=YangtseSu/atrust-quadlet \
        DRY_RUN=true python3 .github/prune-packages.py

Needs `GH_TOKEN`, a PAT with `read:packages` and `delete:packages`: `GITHUB_TOKEN` can push to the
package but can neither list nor delete a version of it. The registry reads need no token at all -
the package is public and a pull token is fetched anonymously.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"
REGISTRY = "https://ghcr.io"
MANIFEST_ACCEPT = ", ".join((
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
))


def call(url, method="GET", accept=None, token=None):
    """One request; an HTTP error carries the API's own message."""
    request = urllib.request.Request(url, method=method)
    request.add_header("user-agent", "atrust-quadlet-prune")
    request.add_header("accept", accept or "application/vnd.github+json")
    request.add_header("x-github-api-version", "2022-11-28")
    if token:
        request.add_header("authorization", "Bearer %s" % token)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.headers, response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace").strip()[:300]
        sys.exit("::error::%s %s answered %s: %s" % (method, url, error.code, detail))


def tags_of(version):
    return version.get("metadata", {}).get("container", {}).get("tags", [])


def versions(owner, package, token):
    """Every version of the package, newest first (the packages API pages at 100)."""
    listed = []
    page = 1
    while True:
        query = urllib.parse.urlencode({"per_page": 100, "page": page})
        _, body = call("%s/users/%s/packages/container/%s/versions?%s" % (API, owner, package, query),
                       token=token)
        batch = json.loads(body)
        listed += batch
        if len(batch) < 100:
            return listed
        page += 1


def pull_token(owner, package):
    """A pull token for the public package; nothing secret is sent for it."""
    query = urllib.parse.urlencode({"scope": "repository:%s/%s:pull" % (owner, package),
                                    "service": "ghcr.io"})
    _, body = call("%s/token?%s" % (REGISTRY, query))
    return json.loads(body)["token"]


def resolve(owner, package, token, tag):
    """What one tag resolves to: its digest and, when it is a manifest list, its children."""
    path = urllib.parse.quote(tag, safe="")
    headers, body = call("%s/v2/%s/%s/manifests/%s" % (REGISTRY, owner, package, path),
                         accept=MANIFEST_ACCEPT, token=token)
    digest = headers.get("docker-content-digest")
    if not digest:
        sys.exit("::error::the registry served tag %s without Docker-Content-Digest" % tag)
    children = [child["digest"] for child in json.loads(body).get("manifests", [])]
    return digest, children


def delete(owner, package, token, version_id):
    call("%s/users/%s/packages/container/%s/versions/%s" % (API, owner, package, version_id),
         method="DELETE", token=token)


def main():
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" not in repository:
        sys.exit("::error::GITHUB_REPOSITORY is not set as owner/repo")
    owner, package = repository.split("/", 1)
    token = os.environ.get("GH_TOKEN")
    if not token:
        sys.exit("::error::GH_TOKEN is not set: the run needs read:packages and delete:packages")
    dry_run = os.environ.get("DRY_RUN", "true").strip().lower() not in ("false", "0", "no")

    listed = versions(owner, package, token)
    tagged = [v for v in listed if tags_of(v)]
    tags = sorted({tag for v in tagged for tag in tags_of(v)})
    if not tagged:
        sys.exit("::error::the package lists no tagged version at all: refusing to touch anything")

    registry_token = pull_token(owner, package)
    resolved = {tag: resolve(owner, package, registry_token, tag) for tag in tags}

    # Guard 1, and the reason the keep set is computed from the registry rather than from a naming
    # rule: both APIs must agree about every tag. A hiccup during the pass would show up here as a
    # tag the registry resolves to something the packages API does not list, or the other way round.
    served = {digest for digest, _ in resolved.values()}
    listed_digests = {v["name"] for v in tagged}
    if served != listed_digests:
        sys.exit("::error::the registry serves %s, the package lists %s: refusing to delete"
                 % (sorted(served), sorted(listed_digests)))

    # Guard 2 is Guard 1's shape for the packages the tags do not name directly - the children of a
    # manifest list. Their digests are kept, so a platform image a live tag still resolves to cannot
    # be deleted while the list that carries it stays.
    children = {child for _, kids in resolved.values() for child in kids}
    keep = served | children
    if not keep:
        sys.exit("::error::resolved %d tags but kept no digest: refusing to delete" % len(tags))

    orphans = [v for v in listed if not tags_of(v) and v["name"] not in keep]

    rows = []
    for version in orphans:
        if not dry_run:
            delete(owner, package, token, version["id"])
        rows.append("| %s | `%s` | %s |" % (version["id"], version["name"], version["created_at"]))
        print("%s %s %s" % ("would delete" if dry_run else "deleted", version["id"], version["name"]))

    verdict = "dry run, nothing deleted" if dry_run else "deleted"
    summary = [
        "## prune-packages - %s" % verdict,
        "",
        "%d versions in the package: %d tagged, %d distinct digests reachable from the tags "
        "(%d of them children of a manifest list), %d %s."
        % (len(listed), len(tagged), len(keep), len(children), len(orphans),
           "orphans found" if dry_run else "orphans deleted"),
        "",
        "Tags still resolving: %d" % len(tags),
        "",
        "| version id | digest | created |",
        "|---|---|---|",
    ] + (rows or ["| - | - | - |"])
    text = "\n".join(summary)
    print(text)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as out:
            out.write(text + "\n")


if __name__ == "__main__":
    main()
