# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Drive the aTrust client's own login window with X level input (no OCR).

The client refuses every session that was obtained elsewhere: the tunnel only
comes up when *its own* window logs in (see ``docs/STATUS.md``). So this module
does what a human sitting in the VNC session would do:

    connection options (first run) -> account -> password -> agreement -> submit

It stays language independent on purpose:

* the page is recognised from its *input fields*, located by probing the screen
  dump near the position that page uses and verifying the shape of what is
  found (outlined box, white inside) - no labels are read, and it also works
  while the form is still empty and its submit button is greyed out,
* the agreement box is ticked only when its pixels are not already filled,
* the outcome is never guessed from the screen: the supervisor keeps deciding
  with the data plane (routes on the tunnel interface).

The graphical captcha is not solved here either: a login window that does not
show the password form (captcha, QR code, another auth method) is reported so
the supervisor can hand the session over to VNC.

Coordinates are absolute screen pixels; the constants below are measured
relative to the client window and are only valid at the pinned window size:
the client's UI re-lays out on resize, so the window is normalised first -
which also makes a user changed VNC geometry harmless.
"""
from __future__ import annotations

import logging
import os
import shutil
import struct
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

log = logging.getLogger('atrustd.uiauto')

# --------------------------------------------------------------------------- layout
# Pinned window size: every constant below was measured on the client's own
# windows at exactly this size (Electron content box, no decorations).
WINDOW_W, WINDOW_H = 921, 570
MIN_WINDOW_W, MIN_WINDOW_H = 400, 300
WINDOW_NAME = '^aTrust$'

# "Local Password Auth" page, relative to the window origin: the account field
# and the offsets of everything else in the card (measured on the real client;
# the layout does not move when the fields are filled or the button enables).
USERNAME_BOX = (536, 177, 340, 40)
PASSWORD_DY = 60                  # password field top, from the account field top
AGREE_SIZE = 16
BUTTON_DY = 159                   # submit button top, from the account field top
BUTTON_SIZE = (340, 40)
# The agreement box and the button move together when the client inserts an
# error or captcha row, so the box is measured from the button instead.
AGREE_DY_FROM_BUTTON = -33
BUTTON_WIDTH_TOLERANCE = 30
BUTTON_HEIGHT_TOLERANCE = 12

# "Connection Options" page
ADDRESS_BOX = (124, 170, 360, 32)
OK_DX, OK_DY = -105, 62           # submit button centre, from the address box centre

# How far the real boxes may sit from the positions above (fonts, locales and
# client builds shift them a little).
SEARCH_X = 30
SEARCH_Y = 24

# page kinds
LOGIN = 'login'
CONNECTION = 'connection'
MANUAL = 'manual'      # a login window that is not the password form (captcha, QR, ...)
OTHER = 'other'

# outcomes of one attempt
SUBMITTED = 'submitted'
ADDRESS_SET = 'address_set'
NO_WINDOW = 'no_window'
NOT_READY = 'not_ready'
DISABLED = 'disabled'

BORDER_RGB = (228, 228, 228)      # outline of the client's input fields / buttons
BORDER_TOLERANCE = 12


def is_accent(rgb: tuple[int, int, int]) -> bool:
    """The client's primary colour (buttons, ticked box, selected menu item)."""
    r, g, b = rgb
    return b > 150 and b - r > 60 and b - g > 40


def _is_border(rgb: tuple[int, int, int]) -> bool:
    return all(abs(c - want) <= BORDER_TOLERANCE for c, want in zip(rgb, BORDER_RGB))


def _is_white(rgb: tuple[int, int, int]) -> bool:
    """Field interiors are flat white; the page background is not (#fdfeff)."""
    return min(rgb) == 255


@dataclass
class Outcome:
    kind: str
    detail: str = ''
    page: str = ''

    @property
    def acted(self) -> bool:
        return self.kind in (SUBMITTED, ADDRESS_SET)

    @property
    def needs_human(self) -> bool:
        return self.page == MANUAL

    def describe(self) -> str:
        text = self.kind if not self.detail else '%s: %s' % (self.kind, self.detail)
        return '%s [page=%s]' % (text, self.page) if self.page else text


@dataclass
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def cx(self) -> int:
        return self.x + self.w // 2

    @property
    def cy(self) -> int:
        return self.y + self.h // 2


@dataclass
class Window:
    id: int
    x: int
    y: int
    w: int
    h: int


# --------------------------------------------------------------------------- X plumbing
def _env(cfg) -> dict[str, str]:
    env = dict(os.environ)
    env['DISPLAY'] = cfg.display
    return env


def _xdotool(cfg, *args: str, timeout: float = 10.0) -> tuple[int, str]:
    try:
        proc = subprocess.run(['xdotool', *args], env=_env(cfg), capture_output=True,
                              text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 255, str(exc)
    return proc.returncode, (proc.stdout or '') + (proc.stderr or '')


def available() -> bool:
    return shutil.which('xdotool') is not None and shutil.which('xwd') is not None


def find_window(cfg) -> Window | None:
    """The client's main window: the largest window named "aTrust".

    The tray keeps a 1x1 helper window with the same name, and overlays
    (messages, panels) are smaller, so size is the discriminator.
    """
    rc, out = _xdotool(cfg, 'search', '--name', WINDOW_NAME)
    if rc != 0:
        return None
    best: Window | None = None
    for wid in out.split():
        rc, geo = _xdotool(cfg, 'getwindowgeometry', '--shell', wid)
        if rc != 0:
            continue
        fields = dict(line.split('=', 1) for line in geo.splitlines() if '=' in line)
        try:
            win = Window(int(fields['WINDOW']), int(fields['X']), int(fields['Y']),
                         int(fields['WIDTH']), int(fields['HEIGHT']))
        except (KeyError, ValueError):
            continue
        if win.w < MIN_WINDOW_W or win.h < MIN_WINDOW_H:
            continue
        if best is None or win.w * win.h > best.w * best.h:
            best = win
    return best


def wait_for_window(cfg, timeout: float) -> Window | None:
    end = time.time() + timeout
    while True:
        win = find_window(cfg)
        if win is not None:
            return win
        if time.time() >= end:
            return None
        time.sleep(2.0)


def normalize(cfg, win: Window) -> Window:
    """Pin the window size so the layout above applies, then focus it."""
    if (win.w, win.h) != (WINDOW_W, WINDOW_H):
        log.info('resizing the client window from %dx%d to %dx%d',
                 win.w, win.h, WINDOW_W, WINDOW_H)
        _xdotool(cfg, 'windowsize', str(win.id), str(WINDOW_W), str(WINDOW_H))
        time.sleep(1.0)
        again = find_window(cfg)
        if again:
            win = again
        if (win.w, win.h) != (WINDOW_W, WINDOW_H):
            log.warning('the client window stayed at %dx%d; the login layout is not '
                        'the one this module knows', win.w, win.h)
    _xdotool(cfg, 'windowraise', str(win.id))
    # flwm does not implement _NET_ACTIVE_WINDOW, so focus directly (the click
    # on the field below focuses it as well).
    _xdotool(cfg, 'windowfocus', str(win.id))
    time.sleep(0.3)
    return win


def fit_on_screen(cfg, win: Window, screen: 'Screen') -> Window:
    """Move the window back on screen if it hangs over an edge."""
    if (win.x >= 0 and win.y >= 0 and win.x + win.w <= screen.width
            and win.y + win.h <= screen.height):
        return win
    x = max(0, min(win.x, screen.width - win.w))
    y = max(0, min(win.y, screen.height - win.h))
    log.info('moving the client window to %d,%d to fit the %dx%d screen',
             x, y, screen.width, screen.height)
    _xdotool(cfg, 'windowmove', str(win.id), str(x), str(y))
    time.sleep(0.5)
    return find_window(cfg) or win


def show_window(cfg) -> bool:
    """Click the tray icon to make the main window visible again."""
    rc, out = _xdotool(cfg, 'search', '--name', '^aTrustTray2$')
    for wid in out.split() if rc == 0 else []:
        rc, geo = _xdotool(cfg, 'getwindowgeometry', '--shell', wid)
        fields = dict(line.split('=', 1) for line in geo.splitlines() if '=' in line)
        try:
            x, y = int(fields['X']), int(fields['Y'])
            w, h = int(fields['WIDTH']), int(fields['HEIGHT'])
        except (KeyError, ValueError):
            continue
        if w < 8 or h < 8:
            continue
        log.info('clicking the tray icon at %d,%d to show the client window',
                 x + w // 2, y + h // 2)
        _xdotool(cfg, 'mousemove', str(x + w // 2), str(y + h // 2), 'click', '1')
        time.sleep(2.0)
        return True
    return False


def click(cfg, x: int, y: int) -> None:
    """Click at absolute screen coordinates."""
    _xdotool(cfg, 'mousemove', str(x), str(y), 'click', '1')


def type_text(cfg, text: str) -> None:
    # 80ms/char: Electron drops characters typed faster than it polls X events.
    _xdotool(cfg, 'type', '--delay', '80', '--', text, timeout=30.0)


def press(cfg, *keys: str) -> None:
    _xdotool(cfg, 'key', '--clearmodifiers', *keys)


def fill(cfg, x: int, y: int, text: str) -> None:
    """Type into a field idempotently: select what is there, then replace it."""
    click(cfg, x, y)
    time.sleep(0.4)
    press(cfg, 'ctrl+a')
    time.sleep(0.2)
    type_text(cfg, text)
    time.sleep(0.4)


# --------------------------------------------------------------------------- screen dump
class Screen:
    """An ``xwd`` dump of the root window, parsed just enough for pixel probes."""

    def __init__(self, raw: bytes):
        if len(raw) < 100:
            raise ValueError('short XWD dump')
        header = struct.unpack('>25I', raw[:100])
        (self.header_size, version, pixmap_format, self.depth, self.width, self.height,
         _xoffset, self.byte_order, _bitmap_unit, _bitmap_bit_order, _bitmap_pad, self.bpp,
         self.stride, _visual_class, self.red_mask, self.green_mask, self.blue_mask,
         *_rest) = header
        if version != 7 or pixmap_format != 2 or self.bpp < 8:
            raise ValueError('unsupported XWD dump (version=%s format=%s bpp=%s)'
                             % (version, pixmap_format, self.bpp))
        self.offset = self.header_size + header[19] * 12
        self.pixel_bytes = self.bpp // 8
        self._raw = raw

    @staticmethod
    def _channel(mask: int, value: int) -> int:
        if not mask:
            return 0
        shift = (mask & -mask).bit_length() - 1
        return (value & mask) >> shift

    def pixel(self, x: int, y: int) -> tuple[int, int, int]:
        if not (0 <= x < self.width and 0 <= y < self.height):
            return (0, 0, 0)
        start = self.offset + y * self.stride + x * self.pixel_bytes
        unit = self._raw[start:start + self.pixel_bytes]
        if len(unit) < self.pixel_bytes:
            return (0, 0, 0)
        value = int.from_bytes(unit, 'little' if self.byte_order == 0 else 'big')
        return (self._channel(self.red_mask, value), self._channel(self.green_mask, value),
                self._channel(self.blue_mask, value))


def screenshot(cfg, timeout: float = 15.0) -> Screen | None:
    if not shutil.which('xwd'):
        log.warning('xwd is missing, cannot inspect the client window')
        return None
    try:
        proc = subprocess.run(['xwd', '-silent', '-root', '-nobdrs'], env=_env(cfg),
                              capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning('xwd failed: %s', exc)
        return None
    try:
        return Screen(proc.stdout)
    except ValueError as exc:
        log.warning('cannot parse the screen dump: %s', exc)
        return None


def _interior_is_white(screen: Screen, rect: Rect) -> bool:
    """The inside of a field is white; a field holding text still is, mostly."""
    samples = [(rect.cx + dx, rect.cy + dy) for dx in (-60, 0, 60) for dy in (-8, 8)]
    white = sum(1 for point in samples if _is_white(screen.pixel(*point)))
    return white > len(samples) // 2


def _is_border_line(screen: Screen, rect: Rect, y: int,
                    fractions: tuple[float, ...] = (0.05, 0.25, 0.5, 0.75, 0.95)) -> bool:
    """The outline runs the whole way (rounded corners are probed around)."""
    for fraction in fractions:
        if not _is_border(screen.pixel(int(rect.x + (rect.w - 1) * fraction), y)):
            return False
    return True


def _is_border_column(screen: Screen, rect: Rect, x: int) -> bool:
    for fraction in (0.2, 0.5, 0.8):
        if not _is_border(screen.pixel(x, int(rect.y + (rect.h - 1) * fraction))):
            return False
    return True


def find_box(screen: Screen, win: Window, expect: tuple[int, int],
             size: tuple[int, int]) -> Rect | None:
    """Locate an outlined (input) box near the position a page uses for it.

    Verified by its outline: continuous top and bottom borders, continuous left
    and right borders (the corners are rounded, so they prove nothing) and a
    white inside. The plain page background passes none of these.
    """
    left0, top0 = expect
    width, height = size
    for dy in range(SEARCH_Y + 1):
        for sy in (top0 - dy, top0 + dy):
            for dx in range(SEARCH_X + 1):
                for sx in (left0 - dx, left0 + dx):
                    rect = Rect(win.x + sx, win.y + sy, width, height)
                    if rect.x < win.x or rect.y < win.y:
                        continue
                    if not _is_border_line(screen, rect, rect.y):
                        continue
                    if not _is_border_line(screen, rect, rect.y + height - 1):
                        continue
                    if not _is_border_column(screen, rect, rect.x):
                        continue
                    if not _is_border_column(screen, rect, rect.x + width - 1):
                        continue
                    if _interior_is_white(screen, rect):
                        return rect
    return None


def classify(screen: Screen, win: Window) -> tuple[str, Rect | None]:
    """Which page is the client showing?"""
    account = find_box(screen, win, USERNAME_BOX[:2], USERNAME_BOX[2:])
    if account is not None:
        password = find_box(screen, win, (USERNAME_BOX[0], USERNAME_BOX[1] + PASSWORD_DY),
                            USERNAME_BOX[2:])
        if password is not None:
            return LOGIN, account
        # An account field without a password field right below it: the client
        # is asking for something else as well (captcha, QR code, ...).
        return MANUAL, account
    address = find_box(screen, win, ADDRESS_BOX[:2], ADDRESS_BOX[2:])
    if address is not None:
        return CONNECTION, address
    return OTHER, None


# --------------------------------------------------------------------------- client state
def tray_log(cfg) -> Path | None:
    """The client's own log (its window writes the SPA console there)."""
    try:
        logs = [p for p in Path(cfg.client_log_dir).glob('aTrustTray*.log') if p.is_file()]
    except OSError:
        return None
    return max(logs, key=lambda p: p.stat().st_mtime) if logs else None


def log_offset(cfg) -> int:
    path = tray_log(cfg)
    try:
        return path.stat().st_size if path else 0
    except OSError:
        return 0


def log_since(cfg, offset: int) -> str:
    path = tray_log(cfg)
    if not path:
        return ''
    try:
        with path.open('r', errors='replace') as handle:
            size = path.stat().st_size
            handle.seek(min(offset, size))
            return handle.read()
    except OSError as exc:
        log.debug('cannot read %s: %s', path, exc)
        return ''


def captcha_requested(cfg, offset: int) -> bool:
    """Did the client ask the portal for a captcha after ``offset``?

    The client's window fetches ``/public/checkCode`` only when the portal
    demands the graphical captcha and logs every request it makes, so this is a
    language independent "a human is needed" signal.
    """
    return 'checkCode' in log_since(cfg, offset)


# --------------------------------------------------------------------------- actions
def address(cfg) -> str:
    """The portal address as the client stores it (scheme://host:port, no path)."""
    parts = urlsplit(cfg.portal_url)
    return '%s://%s' % (parts.scheme, parts.netloc or parts.path)


def seed_address(cfg) -> bool:
    """Write the portal address where the client looks for it.

    Without it the client opens on "Connection Options" and asks for the
    address; with it the window opens on the login page. Written before the
    client starts, so a freshly created container needs no address typing.
    """
    path = Path(cfg.client_addr_conf)
    want = address(cfg)
    try:
        if path.exists() and path.read_text(encoding='utf-8', errors='replace').strip() == want:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(want, encoding='utf-8')
        os.chmod(path, 0o644)
        log.info('wrote the portal address into %s', path)
        return True
    except OSError as exc:
        log.warning('cannot write %s: %s', path, exc)
        return False


def _expand(screen: Screen, cx: int, cy: int, max_w: int, max_h: int) -> Rect | None:
    """Grow a filled accent rectangle out of a point known to be inside it."""
    if not is_accent(screen.pixel(cx, cy)):
        return None
    x0 = x1 = cx
    while x1 - x0 < max_w and is_accent(screen.pixel(x1 + 1, cy)):
        x1 += 1
    while x1 - x0 < max_w and is_accent(screen.pixel(x0 - 1, cy)):
        x0 -= 1
    y0 = y1 = cy
    while y1 - y0 < max_h and is_accent(screen.pixel(cx, y1 + 1)):
        y1 += 1
    while y1 - y0 < max_h and is_accent(screen.pixel(cx, y0 - 1)):
        y0 -= 1
    rect = Rect(x0, y0, x1 - x0 + 1, y1 - y0 + 1)
    # a rounded corner is not part of the rectangle: check the body, not the corners
    inset = 4
    for px, py in ((rect.x + inset, rect.y + inset),
                   (rect.x + rect.w - 1 - inset, rect.y + inset),
                   (rect.x + inset, rect.y + rect.h - 1 - inset),
                   (rect.x + rect.w - 1 - inset, rect.y + rect.h - 1 - inset)):
        if not is_accent(screen.pixel(px, py)):
            return None
    return rect


def find_button(screen: Screen, password: Rect) -> Rect | None:
    """The submit button, found by its fill.

    The button carries the primary colour once the form is complete, and it is
    the reliable anchor for the rest of the card: the client inserts error and
    captcha rows between the password field and the button, which moves the
    agreement box and the button down together, away from the fields.
    """
    want_w, want_h = BUTTON_SIZE
    for cy in range(password.y + password.h + 6, password.y + password.h + 260, 6):
        for cx in range(password.x + 8, password.x + password.w - 8, 8):
            rect = _expand(screen, cx, cy, want_w + 2 * BUTTON_WIDTH_TOLERANCE,
                           want_h + 2 * BUTTON_HEIGHT_TOLERANCE)
            if rect is None:
                continue
            if (abs(rect.w - want_w) > BUTTON_WIDTH_TOLERANCE
                    or abs(rect.h - want_h) > BUTTON_HEIGHT_TOLERANCE):
                continue
            return rect
    return None


def _agreement_checked(screen: Screen, button: Rect) -> bool:
    """Read the agreement box: a ticked one is filled with the primary colour.

    Sampled inside the box (not at its centre, where the tick mark is white).
    """
    left, top = button.x, button.y + AGREE_DY_FROM_BUTTON
    samples = [(left + dx, top + dy) for dx in (3, 6, 9, 12) for dy in (3, 6, 9, 12)]
    filled = sum(1 for point in samples if is_accent(screen.pixel(*point)))
    return filled > len(samples) // 2


def _set_address(cfg, box: Rect) -> None:
    fill(cfg, box.cx, box.cy, address(cfg))
    click(cfg, box.cx + OK_DX, box.cy + OK_DY)
    time.sleep(2.0)


def _submit_login(cfg, fields: Rect, screen: Screen) -> Outcome:
    password = Rect(fields.x, fields.y + PASSWORD_DY, fields.w, fields.h)
    button = find_button(screen, password)
    if button is None:
        # A greyed out button means an empty form, and an empty form cannot
        # carry an error or captcha row: the button is where it always is.
        button = Rect(fields.x, fields.y + BUTTON_DY, *BUTTON_SIZE)
    if not _agreement_checked(screen, button):
        log.info('the agreement box is not ticked, clicking it')
        click(cfg, button.x + AGREE_SIZE // 2,
              button.y + AGREE_DY_FROM_BUTTON + AGREE_SIZE // 2)
        time.sleep(0.5)
        again = screenshot(cfg)
        if again is not None:
            moved = find_button(again, password) or button
            if not _agreement_checked(again, moved):
                return Outcome(NOT_READY, 'the agreement box did not tick: the form is not '
                                          'the one this module knows (captcha or another '
                                          'login step?)', MANUAL)
    fill(cfg, fields.cx, fields.cy, cfg.username)
    fill(cfg, password.cx, password.cy, cfg.password)
    click(cfg, button.cx, button.cy)
    log.info('submitted the login form of the client window')
    return Outcome(SUBMITTED, 'credentials submitted', LOGIN)


def _page_wait(cfg, win: Window, tries: int = 5, delay: float = 4.0) -> tuple[str, Rect | None, Screen | None]:
    """Read the page, giving the window time to render it.

    The window is mapped before its content is there (right after a client
    start the SPA still fetches its manifest), and an early look would classify
    the page as "not a login page" and give up for the whole cycle.
    """
    page, box, screen = OTHER, None, None
    for attempt in range(tries):
        screen = screenshot(cfg)
        if screen is None:
            return OTHER, None, None
        page, box = classify(screen, win)
        if page != OTHER or attempt == tries - 1:
            break
        log.info('the client window is not showing a known page yet, waiting')
        time.sleep(delay)
    return page, box, screen


def login(cfg, window_timeout: float = 30.0) -> Outcome:
    """One attempt at logging the client in through its own window.

    Addresses *only* the page the window is actually showing: on the login page
    it fills the form and submits, on the connection page it enters the portal
    address first. It never retries by itself - the supervisor owns the retry
    policy, so a wrong password cannot turn into a burst of failed logins.
    """
    if not available():
        return Outcome(DISABLED, 'xdotool/xwd are not installed')
    win = wait_for_window(cfg, window_timeout)
    if win is None:
        if not show_window(cfg):
            return Outcome(NO_WINDOW, 'no client window found')
        win = wait_for_window(cfg, 10.0)
        if win is None:
            return Outcome(NO_WINDOW, 'the client window did not come back')
    win = normalize(cfg, win)
    page, box, screen = _page_wait(cfg, win)
    if screen is None:
        return Outcome(NOT_READY, 'cannot take a screen dump')
    win = fit_on_screen(cfg, win, screen)
    if page == CONNECTION and box is not None:
        log.info('the client asks for the portal address: %s', address(cfg))
        _set_address(cfg, box)
        page, box, screen = _page_wait(cfg, win, tries=3)
        if screen is None:
            return Outcome(ADDRESS_SET, 'address entered', CONNECTION)
        if page != LOGIN or box is None:
            return Outcome(ADDRESS_SET, 'address entered, waiting for the login page', CONNECTION)
    if page == LOGIN and box is not None:
        return _submit_login(cfg, box, screen)
    if page == MANUAL:
        return Outcome(NOT_READY, 'the window is not showing the password form: captcha or '
                                  'another login method needs a human', MANUAL)
    return Outcome(NOT_READY, 'the window is not on a login page', page)
