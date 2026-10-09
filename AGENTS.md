<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# AGENTS.md

Notes for coding agents. `README.md` is user-facing, `docs/DESIGN.md` explains how it works,
`docs/STATUS.md` is the record of what was verified, `docs/ROADMAP.md` is the plan.

## Rules

* **No personal or private data - this repository is public.** Never commit a real portal hostname,
  a line-node or intranet address, an account or user name, a device id, an SID, a signkey, a token,
  a password, or a path from a private deployment. Quote log evidence with placeholders
  (`<portal>`, `10.0.0.10`, `app.intranet.example`, `<user>`, `<sid>`), and keep `~/.config/atrust.env`
  and `~/.atrust-data` out of the tree (`.gitignore` covers the first).
* **Python standard library only** - no pip, no `requests`, no `cryptography`. The engine runs on
  the bare `python3` of the image.
* **Everything is podman** - no docker in the runtime, no docker-only flags.
* **`base/` builds the client image, it is never published.** The pipeline builds it into a
  throwaway local tag (`localhost/atrust-base:latest`) and the main `Containerfile` consumes it
  through `--build-arg BASE_IMAGE`; the published artefact stays one image. `base/vendor/**` keeps
  the upstream body byte-identical (the upstream commit is recorded in `base/README.md`), this
  repository's changes go into `base/overlay/`. A client version bump is one commit:
  `base/build-args/<arch>.env` + the live acceptance + any `uiauto` geometry change.
* **Licence of the vendored plumbing.** `base/vendor/**` comes from `Hagb/docker-easyconnect`
  (WTFPL v2 upstream, provenance in every file) and is redistributed here under
  `GPL-3.0-or-later`; the client binary comes from Sangfor's CDN at build time and stays theirs.
* **REUSE**: every file carries `SPDX-FileCopyrightText` and `SPDX-License-Identifier`; `reuse lint`
  must stay green.
* **English** in code, comments, commits and docs; conventional commit subjects.
* Keep user-facing text in `README.md`; engineering detail belongs in `docs/DESIGN.md`,
  measurements in `docs/STATUS.md`, plans in `docs/ROADMAP.md`.
* Tests are stdlib `unittest` and offline: `python3 -m unittest discover -s tests`. Add one only for
  behaviour that can regress silently (the two files there show the pattern).

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
can be decided offline.

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
