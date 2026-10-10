<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 09 — loginctl shim: answer the shapes the client asks

Status: 🚧 in-progress — the shim, its Containerfile/README wiring and an offline test have landed;
the live acceptance is the same maintenance window as step 08 (it needs the base rebuilt and a real
client login)
Depends on: the next base rebuild (any change under `base/` changes the recipe hash) and a login
Touches: `base/overlay/loginctl`, `base/vendor/loginctl` (left `vendor/`), `base/Containerfile`,
`base/README.md`, `tests/test_loginctl_shim.py`

## Goal

The vendored shim answers two exact spellings — `--no-legend list-sessions` and `show-session` — and
exits 1 for everything else. The client's own shell helpers ask in four:

| caller | invocation | today |
|---|---|---|
| `aTrustTrayStart.sh`, `aTrustShellExec.sh` | `loginctl --no-legend list-sessions` | works |
| `aTrustTrayStart.sh`, `aTrustShellExec.sh` | `loginctl show-session <id>` (parsed as `key=value`) | works |
| `get_current_user_session.sh`, reached from `plugins/aTrustCore/libEAIOSDKWrapper.so` | `loginctl list-sessions` | exit 1, no session id |
| same | `loginctl show-session -p Display <id>` | the whole session is printed, so `awk -F= '{print $2}'` yields `10644` instead of `:1` |

Measured in the live container 2026-10-10, with the client's own script:

```
$ loginctl list-sessions                       ; echo rc=$?      → rc=1
$ bash .../shell/get_current_user_session.sh :1 ; echo rc=$?     → (no output) rc=1
```

The AUR package solves the same class of problem with a wrapper around the real `loginctl` that
rewrites one line of its output, which is how it keeps every argument shape working. A container has
no logind to wrap, so the lesson transfers as shape coverage, not as a rewrite: parse the verb and
the property options, not one fixed argument string. Whether the empty answer costs anything visible
is unproven — the core service runs as `sangfor` through the `fake-getlogin` shim, not through this
script — so this is fidelity, not a known defect.

Candidate verified in the live container (`podman cp`, `PATH` override, the client's own caller):
`get_current_user_session.sh :1` prints `10644`, rc=0; `--no-legend list-sessions` and
`show-session <id>` return what they returned before; `show-session -p Display|Leader|Type` filter to
one line (`--value` to the bare value); an unknown verb still exits 1.

## Deliverables

- ✅ `base/overlay/loginctl`, derived from upstream's `docker-root-preinst/usr/bin/loginctl` at
  `e8fc56a7c518d83b6817e16713f765e3c652e3bf` — the `overlay/start.sh` pattern: the body is ours now,
  so the file cannot stay in `vendor/` (that directory is upstream bodies verbatim, see `AGENTS.md`),
  and the header says `Derived from ...` instead of `Vendored from ...`. Same session values
  (`Id=10644`, `User=1234`/`sangfor`, `Display=:1`, `Type=x11`, `Class=user`, `Active=yes`), the same
  `useradd sangfor` side effect, plus argument parsing for `list-sessions`/`show-session`,
  `--no-legend`/`-n`/`--no-pager`, `-p`/`--property[=]`, `--value`. Exit 1 for a verb it does not
  model. The vendored copy left `vendor/` (`git mv`): its body is no longer upstream's, and a file
  nobody copies is dead weight. `base/README.md` and the Containerfile carry the provenance and the
  list of caller shapes a client bump has to re-check.
- ✅ `tests/test_loginctl_shim.py`: the four caller shapes plus `--property=`, `--value` and an
  unknown verb, run against the file itself with a stubbed `useradd` (no account is ever created on
  the machine running the tests).
- ✅ Decision, written down rather than deferred: only the shapes the client actually uses are
  modelled. `list-sessions --json` and filters other than `-p` stay unimplemented and exit 1, which
  is the honest answer for a command this shim does not know; the file header lists the shapes so
  the next client version can be checked against them.

## Exit criteria

- ✅ In the container: `get_current_user_session.sh :1` prints the session id, and the tray-start and
  shell-exec shapes return byte-identical output to the shim they replaced. Measured with the new
  file at the real path (`/usr/bin/loginctl`, `podman cp` into a throwaway container of the published
  image - the same image the next base rebuild starts from).
- ⬜ The tray still logs in and the core plugin still runs as user `sangfor` on a real login; the next
  base rebuild and the maintenance window of step 08 carry this.

## Progress log

* 2026-10-10 — written as backlog from the AUR review; the candidate script was copied into the live
  container and exercised with the client's own `get_current_user_session.sh :1` (before: no output,
  rc=1; after: `10644`, rc=0), then removed from the container.
* 2026-10-10 — promoted to step 09 and implemented: the shim moved out of `vendor/` into
  `base/overlay/`, the Containerfile copies the overlay file, `base/README.md` describes the widened
  shape coverage and why the file cannot live in `vendor/`. Verified with the file at
  `/usr/bin/loginctl` in a throwaway container: `get_current_user_session.sh :1` → `10644`, rc=0;
  `--no-legend list-sessions` → `10644 1234 sangfor seat0`; `show-session 10644` → the same key=value
  blob as before; `-p Display`/`-p Leader`/`--property=Type --value` filter to the one property;
  `list-users` still exits 1. `python3 -m unittest discover -s tests` covers the shim offline.
