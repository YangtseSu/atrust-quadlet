<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 07 — Registry orphan-version pruning

Status: ⬜ not-started
Depends on: the `PACKAGES_TOKEN` repository secret (a PAT with `read:packages` + `delete:packages`)
Touches: `.github/workflows/prune-packages.yml` (new), `AGENTS.md`, `README.md`

## Goal

Every publish run pushes each platform under a temporary tag (`:linux-amd64`, `:linux-arm64`); the next
run overwrites it, the previous version loses its last tag and stays in the package forever. The package
already carried more orphans than live versions (33 against 10 on 2026-10-10, pruned by hand with the
keep-set algorithm below). GitHub offers a retention policy for this only to organisations, so a
workflow does it here.

## Deliverables

- ⬜ `.github/workflows/prune-packages.yml`, `workflow_dispatch` only (never on a push: deletion is not
  something a commit should trigger), running the keep-set algorithm: resolve every tag's digest, add
  the children of every index among them, then delete the versions with no tag whose digest is not in
  that set. It prints the deleted `(id, digest, created_at)` rows and the surviving tag count in the
  job summary.
- ⬜ The job refuses to run when the keep set is smaller than the number of tags resolved (a guard
  against deleting on a registry hiccup), and takes `dry_run` as an input, defaulting to true.
- ⬜ `AGENTS.md` records the rule the incident taught: a per-architecture push tag must carry the run's
  sha, or the next run's orphan is unavoidable.
- ⬜ `README.md` mentions the secret's purpose in one line (the workflow is the only consumer).

## Exit criteria

- ⬜ A `dry_run` run prints exactly the orphans a manual pass would delete (compared against
  `gh api /user/packages/container/atrust-quadlet/versions` before and after).
- ⬜ A real run deletes at least one version, and the tag check that follows resolves every tag and every
  child manifest (`broken: none`) - the check is the script recorded in the `## Progress log`.
- ⬜ The next normal publish run still pushes and its tags resolve.

## Progress log

* 2026-10-10 — written as step 07. The manual pass that ran today (43 versions → 26, 17 deleted, all
  tags resolving) is the reference behaviour of the job to be written.
