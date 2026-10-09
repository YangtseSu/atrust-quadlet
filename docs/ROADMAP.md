<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Roadmap

The direction, in one page. The execution lives in [`docs/plans/`](plans/) — one file per step with its
own progress — and the retired records in [`docs/archive/`](archive/). This file says where the project
is going and what it deliberately does not do; the steps say how, in what order.

## What it is

A supervisor that keeps one Sangfor aTrust client logged in inside a rootless podman container, on
headless hosts: the client, its X/VNC desktop and the proxies come from an image this repository builds
itself (`base/`, from Sangfor's own package), and `atrustd` drives the client's own window when the
session has to be rebuilt. Everything user-facing is in [`README.md`](../README.md), the engineering in
[`DESIGN.md`](DESIGN.md).

## Direction

* **The data plane decides.** The tunnel interface, its routes and a real intranet request through the
  proxy answer "is it up"; the client's internal API is not reproduced.
* **The client's own window is driven, never its internals.** A page this project cannot recognise ends
  in the VNC hand-over rather than in blind clicking, and the human is told (step 02).
* **podman only, standard library only.** No docker, no pip, no third-party Python package, no
  `unsafe`-style shortcuts with the image's contents.
* **The base is ours.** The client version is pinned in `base/build-args/`, published content-addressed,
  and reused between builds; a vendor bump is an explicit commit with a live acceptance.
* **State on disk, not in a session.** Measurements, rulings and reasons live in the step files and in
  the code beside the constants they justify.

## Not doing

* No reimplementation of the client, no scraping of its private APIs, no captcha solving.
* No Windows or macOS support; the target is a Linux host with podman and a user session.
* No GUI of our own: the desktop in the container (VNC) is the interface for anything a human must do.
* No multi-account or multi-portal supervision in one container.

## Where the work is

| | |
|---|---|
| [`docs/plans/`](plans/) | the live plan, one file per step, progress inside the file |
| [`docs/archive/`](archive/) | what the plan replaced: the milestone record to 2026-10-10 and the item roadmap |
| [`docs/DESIGN.md`](DESIGN.md) | how it works |
| [`AGENTS.md`](../AGENTS.md) | the rules, including "Plan discipline" |
