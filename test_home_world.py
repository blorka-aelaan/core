#!/usr/bin/env python3
"""Tests for bounded local and opt-in external environment observations."""

import socket
from unittest.mock import patch

import home_world


def test_internet_disabled_by_default():
    world = home_world.HomeWorld({})
    observed = world.observe()
    assert not world.internet_enabled
    assert "internet:observation:disabled" in observed["tokens"]
    assert not world._request_in_flight


def test_allowlist_is_https_and_origin_only():
    sites = home_world.HomeWorld._validated_sites([
        "https://example.com/",
        "http://example.org/",
        "https://127.0.0.1/",
        "https://localhost/",
        "https://example.net/?q=private",
        "https://user@example.io/",
        "https://example.com:bad/",
        "https://example.com/",
    ])
    assert sites == ("example.com",)


def test_private_dns_result_is_rejected():
    world = home_world.HomeWorld({
        "internet": {
            "enabled": True,
            "allowlist": ["https://example.com/"],
        }
    })
    records = [(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                ("192.168.1.10", 443))]
    with patch.object(socket, "getaddrinfo", return_value=records):
        try:
            world._public_address("example.com")
        except ValueError as exc:
            assert str(exc) == "host_not_public"
        else:
            raise AssertionError("private address was accepted")


def test_enabled_sites_schedule_immediately_without_blocking():
    world = home_world.HomeWorld({
        "internet": {
            "enabled": True,
            "allowlist": ["https://example.com/"],
        }
    }, clock=lambda: 0.0)
    with patch.object(home_world.threading, "Thread") as thread:
        observed = world.observe()
        assert observed["tokens"][-1] == "internet:observation:waiting"
        thread.assert_called_once()
        thread.return_value.start.assert_called_once()
        world.observe()
        thread.assert_called_once()


def test_web_observation_is_metadata_only_and_bounded():
    world = home_world.HomeWorld({
        "internet": {
            "enabled": True,
            "allowlist": ["https://example.com/"],
        }
    })

    class Response:
        status = 200

        def getheader(self, name):
            assert name == "Content-Type"
            return "text/html; charset=utf-8"

        def read(self, _size=-1):
            raise AssertionError("response body must not be read")

    class Connection:
        def __init__(self, host, address, timeout):
            assert (host, address) == ("example.com", "93.184.216.34")
            assert timeout == 2.0
            self.request_args = None

        def request(self, method, path, headers):
            self.request_args = (method, path, headers)

        def getresponse(self):
            assert self.request_args[0:2] == ("GET", "/")
            return Response()

        def close(self):
            pass

    with patch.object(world, "_public_address", return_value="93.184.216.34"), \
            patch.object(home_world, "_PinnedHTTPSConnection", Connection):
        result = world._fetch_site("example.com")
    assert result == {
        "host": "example.com",
        "status": 200,
        "content_type": "text/html",
    }


def test_local_snapshot_uses_compact_resource_context():
    world = home_world.HomeWorld({})
    observed = world.observe()
    assert len(observed["local"]["tokens"]) == 2
    assert observed["local"]["tokens"][0].startswith("home:os:")
    assert observed["local"]["tokens"][1].startswith("home:resources:")
    assert all("private page text" not in token for token in observed["tokens"])


if __name__ == "__main__":
    for test in (
        test_internet_disabled_by_default,
        test_allowlist_is_https_and_origin_only,
        test_private_dns_result_is_rejected,
        test_enabled_sites_schedule_immediately_without_blocking,
        test_web_observation_is_metadata_only_and_bounded,
        test_local_snapshot_uses_compact_resource_context,
    ):
        test()
    print("Home world observer: 6/6 OK")
