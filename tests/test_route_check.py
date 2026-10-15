# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The check the unit runs before every start must hold a start only when pasta would get nothing.

The regression this pins is silent in one direction: a check that keeps answering "usable route"
lets the container come up dark exactly as before B07 - up, no way out, and nobody tells the
operator. The other direction (a host held although pasta would have worked) is loud: the unit
never starts and the journal says why.

The shapes below are the measured ones: the host's own `/proc/net/route` and `/proc/net/ipv6_route`,
and the files a sandbox carries when pasta drops to local mode (measured 2026-10-15 in a netns with
no usable address - the tap holds 169.254.2.1/16 and a default route via pasta's own 169.254.2.2,
which must not be mistaken for a way out). The check itself is not copied here: the snippet is read
out of `quadlet/atrust.container` and run with its two /proc paths pointed at the fixture directory,
so the rule under test is the rule the unit ships.

Run: python3 -m unittest tests.test_route_check
"""
from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

UNIT = Path(__file__).resolve().parent.parent / 'quadlet' / 'atrust.container'

# a host with an IPv4 default route, its on-link route and a global IPv6 address with an IPv6
# default (the addresses are the placeholders the repository's rules ask for, the layout is the
# measured one)
HEALTHY_ROUTE = """Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT
enp1s0\t00000000\t0100000A\t0003\t0\t0\t100\t00000000\t0\t0\t0
enp1s0\t0000000A\t00000000\t0001\t0\t0\t100\t00FFFFFF\t0\t0\t0
lo\t0000007F\t00000000\t0001\t0\t0\t0\t0000FFFF\t0\t0\t0
"""
HEALTHY_V6 = """20010db8000000000000000000000000 40 00000000000000000000000000000000 00 00000000000000000000000000000000 00000100 00000001 00000000 00000001  enp1s0
fe800000000000000000000000000000 40 00000000000000000000000000000000 00 00000000000000000000000000000000 00000100 00000001 00000000 00000001  enp1s0
00000000000000000000000000000000 00 00000000000000000000000000000000 00 fe800000000000000000000000000001 00000100 0000000d 00000000 00000003  enp1s0
00000000000000000000000000000001 80 00000000000000000000000000000000 00 00000000000000000000000000000000 00000000 00000006 00000000 80200001       lo
ff000000000000000000000000000000 08 00000000000000000000000000000000 00 00000000000000000000000000000000 00000100 00000006 00000000 00000001  enp1s0
"""

# measured in a sandbox pasta left in local mode: every line here is unusable, the default route
# included - its gateway is 169.254.2.2, i.e. pasta itself, and behind it nothing answers but pasta's
# own refusal
LOCAL_MODE_ROUTE = """Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT
tap0\t00000000\t0202FEA9\t0003\t0\t0\t0\t00000000\t0\t0\t0
tap0\t0000FEA9\t00000000\t0001\t0\t0\t0\t0000FFFF\t0\t0\t0
"""
LOCAL_MODE_V6 = """fe800000000000000000000000000000 40 00000000000000000000000000000000 00 00000000000000000000000000000000 00000100 00000001 00000000 00000001     tap0
00000000000000000000000000000000 00 00000000000000000000000000000000 00 fe800000000000000000000000000001 00000400 00000002 00000000 00000003     tap0
00000000000000000000000000000001 80 00000000000000000000000000000000 00 00000000000000000000000000000000 00000000 00000002 00000000 80200001       lo
fe80000000000000d42e8efffe413dda 80 00000000000000000000000000000000 00 00000000000000000000000000000000 00000000 00000002 00000000 80200001     tap0
ff000000000000000000000000000000 08 00000000000000000000000000000000 00 00000000000000000000000000000000 00000100 00000002 00000000 00000001     tap0
00000000000000000000000000000000 00 00000000000000000000000000000000 00 00000000000000000000000000000000 ffffffff 00000001 00000000 00200200       lo
"""

# a host that has not got its address yet: loopback only
DARK_ROUTE = """Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT
lo\t0000007F\t00000000\t0001\t0\t0\t0\t0000FFFF\t0\t0\t0
"""
DARK_V6 = """00000000000000000000000000000001 80 00000000000000000000000000000000 00 00000000000000000000000000000000 00000000 00000006 00000000 80200001       lo
"""

# only a link-local IPv4 address, but a usable IPv6 side: measured 2026-10-15, pasta takes the v6
# template there ("IPv4: no external interface as template, use local mode", v6 silent)
V6_ONLY_ROUTE = """Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT
d0\t0000FEA9\t00000000\t0001\t0\t0\t0\t0000FFFF\t0\t0\t0
lo\t0000007F\t00000000\t0001\t0\t0\t0\t0000FFFF\t0\t0\t0
"""

HELD = 'no usable route'


class RouteCheckTest(unittest.TestCase):

    def snippet(self) -> str:
        text = UNIT.read_text()
        match = re.search(r"^ExecStartPre=/bin/sh -c '(.*)'$", text, re.M)
        self.assertIsNotNone(match, 'the unit carries no single-line `ExecStartPre=/bin/sh -c ...`')
        return match.group(1)

    def run_check(self, route: str | None, ipv6: str | None) -> subprocess.CompletedProcess:
        snippet = self.snippet()
        with TemporaryDirectory() as tmp:
            for name, content in (('route', route), ('ipv6_route', ipv6)):
                path = Path(tmp) / name
                if content is not None:
                    path.write_text(content)
                snippet = snippet.replace('/proc/net/' + name, str(path))
            self.assertNotIn('/proc/net/', snippet, 'a /proc path in the check was not redirected')
            return subprocess.run(['/bin/sh', '-c', snippet], capture_output=True, text=True)

    def test_a_host_with_a_route_starts(self):
        result = self.run_check(HEALTHY_ROUTE, HEALTHY_V6)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_host_without_an_address_is_held(self):
        result = self.run_check(DARK_ROUTE, DARK_V6)
        self.assertEqual(result.returncode, 1)
        self.assertIn(HELD, result.stderr)

    def test_the_local_mode_shape_is_held(self):
        result = self.run_check(LOCAL_MODE_ROUTE, LOCAL_MODE_V6)
        self.assertEqual(result.returncode, 1)
        self.assertIn(HELD, result.stderr)

    def test_a_link_local_v4_address_only_is_held(self):
        result = self.run_check(V6_ONLY_ROUTE, DARK_V6)
        self.assertEqual(result.returncode, 1)

    def test_a_v6_only_host_starts(self):
        result = self.run_check(V6_ONLY_ROUTE, HEALTHY_V6.replace('enp1s0', 'd0'))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unreadable_files_fail_open(self):
        result = self.run_check(None, None)
        self.assertEqual(result.returncode, 0, result.stderr)
