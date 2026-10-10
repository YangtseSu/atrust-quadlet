<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# AGENTS.md

Notes for coding agents. `README.md` is user-facing, `docs/DESIGN.md` explains how it works,
`docs/ROADMAP.md` is the direction, `docs/plans/` is the live plan (one file per step, progress in
the file) and `docs/archive/` holds the records a later decision replaced.

## Rules

* **No personal or private data - this repository is public.** Never commit a real portal hostname,
  a line-node or intranet address, an account or user name, a device id, an SID, a signkey, a token,
  a password, or a path from a private deployment. Quote log evidence with placeholders
  (`<portal>`, `10.0.0.10`, `app.intranet.example`, `<user>`, `<sid>`), and keep `~/.config/atrust.env`
  and `~/.atrust-data` out of the tree (`.gitignore` covers the first).
* **Python standard library only** - no pip, no `requests`, no `cryptography`. The engine runs on
  the bare `python3` of the image.
* **Everything is podman** - no docker in the runtime, no docker-only flags.
* **`base/` builds the client image; it is published content-addressed and reused.** The tag is
  `<package>:base-<client version>-<recipe hash8>-<arch>` (`base/ref.sh` derives it), the pipeline
  skips the build when that tag already exists, and the main `Containerfile` consumes it through
  `--build-arg BASE_IMAGE` (locally it defaults to `localhost/atrust-base:latest`, so a hand build
  still works without the registry). The base lives in the same GHCR package as the app image:
  GITHUB_TOKEN only has write access to packages linked to the repository. `base/vendor/**` keeps
  the upstream files byte-identical (no header is added; the commit is recorded in
  `base/README.md`), this repository's changes go into `base/overlay/`. A client version bump is
  one commit: `base/build-args/<arch>.env` + the live acceptance + any `uiauto` geometry change.
* **Licence of the vendored plumbing.** `base/vendor/**` comes from `docker-easyconnect/docker-easyconnect`
  and stays byte-identical to it under the upstream WTFPL v2 (declared in `REUSE.toml`, the pinned
  commit in `base/README.md`); the client binary comes from Sangfor's CDN at build time and stays
  theirs.
* **REUSE**: every file carries its licensing information - inline `SPDX-FileCopyrightText` +
  `SPDX-License-Identifier` tags, or a `REUSE.toml` annotation for what cannot carry a header
  (`base/vendor/**` stays byte-identical to upstream, `tests/data/screens/**` are dumps); `reuse
  lint` must stay green.
* **English** in code, comments, commits and docs; conventional commit subjects.
* Keep user-facing text in `README.md`; engineering detail belongs in `docs/DESIGN.md`, the plan in
  `docs/plans/`, direction in `docs/ROADMAP.md`. See "Plan discipline" below.
* Tests are stdlib `unittest` and offline: `python3 -m unittest discover -s tests`. Add one only for
  behaviour that can regress silently (the two files there show the pattern).

## Plan discipline

The work is planned as steps under `docs/plans/` - one file per step, `NN-<slug>.md` (backlog:
`B<NN>-<slug>.md`), whose `Status:` line, `- ⬜`/`- ✅` markers and append-only `## Progress log` carry
its state. `docs/plans/README.md` is the index and the phases; the conventions are borrowed from
`YangtseSu/cirrocast`.

* A step is worked top to bottom, one `- ⬜` item per commit. Closing a step means its `Status:`, its
  `## Progress log` and its row in the index change in the same commit - never before every `- ⬜` is
  a `- ✅`.
* A one-off task is not a step: a CI fix, a document edit, a bumped constant, a bug fixed on the spot
  is a `docs:` / `chore:` / `fix:` commit and adds no file to `docs/plans/`.
* **Never cite `docs/plans/` or `docs/archive/` from code.** Both are the process record and are
  retired when their work closes; a constant or a comment carries its reason and its measured value
  inline, beside it.
* A finding is written to disk in the same turn it is learned - a conclusion that exists only in a
  conversation has not happened.
* A step that ends on a human criterion or waits on an external condition says so in its
  `Depends on:` line and stays open (`⛔ blocked`), with the reason in its `## Progress log`.

## Verifying a change

```bash
python3 -m unittest discover -s tests   # offline
reuse lint
podman build -f base/Containerfile --build-arg-file base/build-args/amd64.env \
  -t localhost/atrust-base:latest base/            # the client image (slow: apt + a 200 MB deb)
podman build --build-arg BASE_IMAGE=localhost/atrust-base:latest -t localhost/atrust-quadlet:dev .
podman exec atrust python3 -m atrustd --status   # live state (JSON)
podman exec atrust python3 -m atrustd --once     # one supervision cycle
journalctl --user -u atrust.service -f           # supervisor log
```

Anything that changes behaviour has to be seen on the live container; the unit tests only cover what
can be decided offline. A change the image cannot see (docs, `.gitignore`, `tests/`) runs `reuse lint`
only - and the publish workflow skips those paths for the same reason (`paths-ignore`).

## Things that already bit us

* `cycle()` must not sleep internally - it returns the delay and `run_daemon` sleeps it. A missing
  sleep turned the supervisor into a 40 Hz loop that flooded the client's netstack.
* The client's userspace netstack drops an occasional connection, so the proxy probe retries before
  it calls the tunnel down.
* GHCR goes through registry mirrors here and their tag cache can be stale: use
  `podman pull --policy=always` or a digest when an image looks old.
* buildx needs the repository in the output when pushing by digest (`name=...`), otherwise it fails
  with `tag is needed when pushing to registry`.
* The portal ends the client's session on its own after ~20 minutes; the supervisor recovers in
  ~130 s, most of it detection latency.
* `.gitignore` has `*.env` for the secrets file, which silently swallowed `base/build-args/*.env`:
  the files were never committed and CI failed with exit 2 reading one. Public build arguments live
  in `base/build-args/*.args` for that reason.
* The client image is pushed per architecture, so its tag carries the architecture: without it the
  two platform jobs overwrite each other and one of them builds on the other architecture's client
  (`Exec format error`). `--platform` in the build makes that a hard failure instead of a warning.
* podman does not create a missing bind source: adding `Volume=%h/.atrust-data/run:/run/atrustd` made
  `atrust.service` fail with `Error: statfs /home/<user>/.atrust-data/run: no such file or directory`,
  and `Restart=always` turned that into a start-limit crash loop. Every host side of a `Volume=` must
  exist first (`install -d`), which the README's quick start now does.
* A GHCR version survives as long as some tag resolves to it, and a manifest list keeps the platform
  images it names alive with it - so what keeps a pushed platform image out of the orphan pile is the
  *manifest list pushed under a tag that does not move* (`sha-<40 hex>` for the app image, the
  content-addressed `base-<version>-<recipe hash>-<arch>` for the client image). A per-architecture
  staging tag is not one: it moves on the next run. Runs that pushed platforms with nothing but a
  staging tag left their images behind, which is where the orphans pruned by hand on 2026-10-10 came
  from; `prune-packages.yml` is the keep-set pass that deletes them, and while every push keeps its
  `sha-` tag, it has nothing to find (51 versions, 0 orphans, 2026-10-10).
* The container runs with the journald log driver, so every `podman exec` session writes
  `container exec` / `container exec_died` records into the journal through the driver itself:
  stderr redirection and `--log-level=error` do not touch them (both measured, 2 records per exec).
  A read-only poll belongs on `podman cp` or on the state directory mounted for the host, not on an
  exec session.
