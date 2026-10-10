<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 07 — Registry orphan-version pruning

Status: ✅ done
Depends on: the `PACKAGES_TOKEN` repository secret (a PAT with `read:packages` + `delete:packages`)
Touches: `.github/workflows/prune-packages.yml` (new), `.github/prune-packages.py` (new), `AGENTS.md`,
`README.md`

## Goal

Every publish run pushes each platform under a temporary tag (`:linux-amd64`, `:linux-arm64`); the next
run overwrites it, and a version no other tag names stays in the package with nothing pointing at it.
The package carried more orphans than live versions once (33 against 10 on 2026-10-10, pruned by hand
with the keep-set algorithm below) and the pattern still appears - the two runs of 2026-10-10 show the
shape - whenever the only tag a manifest list had is one that later moves; it is rare because every push
also leaves a `sha-` tag behind. GitHub offers a retention policy for this to organisations only, so a
workflow does it here.

## Deliverables

- ✅ `.github/workflows/prune-packages.yml`, `workflow_dispatch` only (never on a push: deletion is not
  something a commit should trigger), running the keep-set algorithm: resolve every tag's digest, add
  the children of every index among them, then delete the versions with no tag whose digest is not in
  that set. It prints the deleted `(id, digest, created_at)` rows and the surviving tag count in the
  job summary. The algorithm is a file of its own (`.github/prune-packages.py`) so it can be run by
  hand against the live package before CI does; the workflow is the invocation and the documentation.
- ✅ The job refuses to run when the keep set is smaller than the number of tags resolved (a guard
  against deleting on a registry hiccup), and takes `dry_run` as an input, defaulting to true.
- ✅ `AGENTS.md` records what the measurement taught, which is not what this line said when the step
  was drafted: a per-architecture staging tag is not a keep-anchor (it moves on the next run) - what
  keeps a platform image out of the orphan pile is the manifest list pushed under a tag that does not
  move (`sha-<40 hex>`, the version tags, the client image's content-addressed tag).
- ✅ `README.md` mentions the secret's purpose in one line (the workflow is the only consumer).

## Exit criteria

- ✅ A `dry_run` run prints exactly the orphans a manual pass would delete (compared against
  `gh api /user/packages/container/atrust-quadlet/versions` before and after): run 38036729994 listed
  the same three ids and digests the by-hand pass listed, "56 versions ... 23 tagged ... 3 orphans
  found", and the API answered 56 versions with 23 tagged.
- ✅ A real run deletes at least one version, and the tag check that follows resolves every tag and every
  child manifest (`broken: none`) - the check is the script recorded in the `## Progress log`: run
  38036773625 deleted 1364792102, 1364791667 and 1364791507, the API then answered 53 versions with 23
  tagged, the three ids answered `Package version not found`, and the check reported
  `tags: 33 child manifests: 32 broken: none`.
- ✅ The next normal publish run still pushes and its tags resolve: run 38036514072 (the push that
  carried this workflow to main) completed all five jobs and published both client images under the new
  recipe hash, `base-2.5.16.30-67913340-amd64` and `-arm64` both answering 200; the tag check against
  that state was `broken: none`.

## Progress log

* 2026-10-10 — written as step 07. The manual pass that ran today (43 versions → 26, 17 deleted, all
  tags resolving) is the reference behaviour of the job to be written.
* 2026-10-10 — the workflow and `.github/prune-packages.py` are in the tree, and the script was run by
  hand against the live package before CI ever did: **51 versions, 21 tagged, 32 distinct children of
  the tagged manifest lists, 0 orphans**; an independent throwaway pass over the same data (re-resolving
  all 30 tags through the registry API) agreed. The premise in the goal above therefore no longer holds
  as written - nothing orphans while every push carries `sha-<40 hex>` for the app image and the
  content-addressed `base-<version>-<recipe hash>-<arch>` for the client image, because those tags never
  move and a manifest list keeps the platform images it names alive. The 33 orphans of 2026-10-10 came
  from the runs whose only tags were the staging ones. What remains of "grows forever" is growth by
  design - one index plus two platform images per app push, two client images per recipe change - and
  this job keeps all of it on purpose.
* 2026-10-10 — the guard the deliverable above asks for is implemented in its stronger form: the job
  aborts unless the tags the package API lists and the digests the registry serves are the same set in
  both directions. A raw count ("keep set smaller than the tags resolved") would abort on a healthy
  registry: here `1.3`, `1.3.0`, `sha-...` and `latest` are one and the same manifest list, so a keep
  set of digest count is legitimately smaller than the tag count.
* 2026-10-10 — the algorithm is a file of its own rather than a heredoc inside the workflow, because
  being runnable by hand is what produced the measurement above and it is what the exit criteria's
  reference pass needs.
* 2026-10-10 — the first measurement aged by one push, and this is why: nothing orphans while a manifest
  list still carries a tag that does not move, but `:main` *does* move. The push that carried this
  workflow (076477c) moved `:main` off the index of 05:21, whose `sha-` twin had already moved to the
  release run's index at the same commit - so that index and its two platform children were left with
  no tag at all: 56 versions, 23 tagged, 53 reachable digests, 3 orphans. The dry run
  (`workflow_dispatch`, `dry_run=true`, run 38036729994) listed exactly those three and the by-hand
  pass listed the same three, id and digest for id and digest.
* 2026-10-10 — the real run (`dry_run=false`, run 38036773625) deleted them:
  `deleted 1364792102 sha256:7100424462…`, `deleted 1364791667 sha256:27d623d4d829…`,
  `deleted 1364791507 sha256:1925d14bdc35…`, then "3 orphans deleted"; the versions list went 56 → 53
  (23 tagged), the three ids answer `Package version not found`, and the tag check that follows reports
  `tags: 33 child manifests: 32 broken: none`, which is also its reading before the pass.
* 2026-10-10 — the check, kept here because the exit criteria name it (stdlib only; reads the tags from
  the versions API and resolves each one, then every child, through the registry):

  ```python
  import json, subprocess, urllib.parse, urllib.request
  pkg = "yangtsesu/atrust-quadlet"
  tok = json.load(urllib.request.urlopen(
      "https://ghcr.io/token?scope=repository:%s:pull&service=ghcr.io" % pkg))["token"]
  accept = ",".join(("application/vnd.oci.image.index.v1+json",
                     "application/vnd.docker.distribution.manifest.list.v2+json",
                     "application/vnd.oci.image.manifest.v1+json",
                     "application/vnd.docker.distribution.manifest.v2+json"))
  def get(ref):
      req = urllib.request.Request("https://ghcr.io/v2/%s/manifests/%s" % (pkg, urllib.parse.quote(ref, safe="")))
      req.add_header("accept", accept)
      req.add_header("authorization", "Bearer " + tok)
      with urllib.request.urlopen(req) as resp:
          return json.loads(resp.read())
  versions = json.loads(subprocess.run(["gh", "api",
      "/users/YangtseSu/packages/container/atrust-quadlet/versions?per_page=100"],
      capture_output=True, text=True, check=True).stdout)
  refs = [tag for v in versions for tag in v["metadata"]["container"]["tags"]]
  children, broken = [], []
  for ref in refs:
      children += [m["digest"] for m in get(ref).get("manifests", [])]
  for child in children:
      try:
          get(child)
      except Exception as error:
          broken.append((child, str(error)))
  print("tags:", len(refs), "child manifests:", len(set(children)), "broken:", broken or "none")
  ```
* 2026-10-10 — closed. The pass is a one-command guard now; what it does not do is bound the package,
  and that is by design rather than by oversight: every push to main keeps one index plus two platform
  images under its `sha-` tag, and every client-image recipe keeps two more under its content-addressed
  tag, so the count grows with the history and this job deliberately keeps all of it. If that ever needs
  a ceiling, the knob is a retention rule for the `sha-` tags in this workflow, not the keep-set
  algorithm.
