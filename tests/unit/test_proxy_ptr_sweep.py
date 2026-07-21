"""Tests for the offline proxy PTR sweep hostname matcher.

The DB/DNS orchestration is integration-level; the correctness-critical piece is
the dot-anchored suffix match that decides whether an rDNS hostname is proxy
egress — a loose match here would delete real visitors, so it is unit-pinned."""

import pytest

from apps.api.services.proxy_ptr_sweep import _hostname_is_proxy


class TestHostnameIsProxy:
    @pytest.mark.parametrize("host", [
        "host-192-171-82-117.static.sprious.com",  # the Charter-announced Sprious case
        "sprious.com",                              # exact registrable domain
        "pool.oxylabs.io",
        "x.y.z.rayobyte.com",
        "HOST-1.STATIC.SPRIOUS.COM",                # case-insensitive
        "host.brightdata.com.",                     # trailing dot tolerated
    ])
    def test_proxy_hostnames_match(self, host):
        assert _hostname_is_proxy(host) is True

    @pytest.mark.parametrize("host", [
        "c-68-34-58-201.hsd1.mi.comcast.net",       # real Comcast human
        "pool-71-105-22-133.nycmny.fios.verizon.net",  # real Verizon human
        "notsprious.com",                           # dot-anchor: must NOT match "sprious.com"
        "sprious.com.evil.example",                 # suffix spoof: not a real proxy domain
        "",
        None,
    ])
    def test_non_proxy_hostnames_do_not_match(self, host):
        assert _hostname_is_proxy(host) is False
