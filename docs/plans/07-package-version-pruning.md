<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 07 — Registry orphan-version pruning

Status: 🚧 in-progress
Depends on: the `PACKAGES_TOKEN` repository secret (a PAT with `read:packages` + `delete:packages`)
Touches: `.github/workflows/prune-packages.yml` (new), `.github/prune-packages.py` (new), `AGENTS.md`,
`README.md`

## Goal

Every publish run pushes each platform under a temporary tag (`:linux-amd64`, `:linux-arm64`); the next
run overwrites it, the previous version loses its last tag and stays in the package forever. The package
already carried more orphans than live versions (33 against 10 on 2026-10-10, pruned by hand with the
keep-set algorithm below). GitHub offers a retention policy for this only to organisations, so a
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

- ⬜ A `dry_run` run prints exactly the orphans a manual pass would delete (compared against
  `gh api /user/packages/container/atrust-quadlet/versions` before and after).
- ⬜ A real run deletes at least one version, and the tag check that follows resolves every tag and every
  child manifest (`broken: none`) - the check is the script recorded in the `## Progress log`.
- ⬜ The next normal publish run still pushes and its tags resolve.

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
