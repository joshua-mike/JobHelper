"""Fetcher resilience: cookie-pin shedding + per-host circuit breaker.

Regression cover for the 2026-08-12 incident, where one long-lived httpx.Client
got pinned to a sick Workday backend (__cflb + wday_vps_cookie) and then replayed
those cookies on every retry, so a healthy tenant looked like a total outage for
an hour. No network — httpx.MockTransport serves the responses.
Run:  python tests/test_fetcher_resilience.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import httpx

from jobhelper.sources import base
from jobhelper.sources.base import Fetcher

URL = "https://caci.wd1.myworkdayjobs.com/wday/cxs/caci/External/jobs"


def _fetcher(handler, **kw) -> Fetcher:
    """A Fetcher whose client is backed by a mock transport, with sleeps disabled."""
    f = Fetcher(delay=0.0, use_cache=False, **kw)
    f._client = httpx.Client(transport=httpx.MockTransport(handler),
                             follow_redirects=True)
    return f


def test_cookies_cleared_between_attempts():
    """A pinning cookie from attempt 1 must not be replayed on attempt 2."""
    seen_cookies: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_cookies.append(request.headers.get("cookie", ""))
        if len(seen_cookies) == 1:  # sick backend pins us, then fails
            return httpx.Response(503, headers={"set-cookie": "__cflb=sickbackend"})
        return httpx.Response(200, json={"total": 1, "jobPostings": [{"title": "SWE"}]})

    f = _fetcher(handler)
    data = f.post_json(URL, json_body={"searchText": "c#"})

    assert data["total"] == 1, data
    assert len(seen_cookies) == 2, seen_cookies
    assert seen_cookies[0] == "", "first attempt should start with a clean jar"
    assert "sickbackend" not in seen_cookies[1], (
        f"retry replayed the pinning cookie: {seen_cookies[1]!r}")
    print("OK  cookie pin is shed between attempts")


def test_cookies_cleared_between_requests():
    """Affinity must not leak across separate calls either."""
    seen_cookies: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_cookies.append(request.headers.get("cookie", ""))
        return httpx.Response(200, json={"total": 0},
                              headers={"set-cookie": "wday_vps_cookie=12345"})

    f = _fetcher(handler)
    f.post_json(URL, json_body={"searchText": "c#"})
    f.post_json(URL, json_body={"searchText": ".net"})

    assert seen_cookies == ["", ""], seen_cookies
    print("OK  cookie pin is shed between requests")


def test_breaker_opens_after_consecutive_failures():
    """After host_fail_limit give-ups the host is skipped without any more I/O."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503)

    f = _fetcher(handler, max_retries=2, host_fail_limit=3)
    for _ in range(3):
        try:
            f.post_json(URL, json_body={"searchText": "c#"})
        except RuntimeError:
            pass
    assert calls["n"] == 6, f"expected 3 give-ups x 2 attempts, got {calls['n']}"

    # Breaker is now open: further calls raise with no network I/O at all.
    try:
        f.post_json(URL, json_body={"searchText": "wpf"})
        raise AssertionError("expected the breaker to raise")
    except RuntimeError as exc:
        assert "marked down" in str(exc), exc
    assert calls["n"] == 6, f"breaker still sent requests: {calls['n']}"
    print("OK  breaker opens and stops further requests")


def test_breaker_is_per_host_and_resets_on_success():
    """A sick tenant must not take healthy ones down, and a success clears the streak."""
    other = "https://leidos.wd5.myworkdayjobs.com/wday/cxs/leidos/External/jobs"

    def handler(request: httpx.Request) -> httpx.Response:
        if "caci" in str(request.url):
            return httpx.Response(503)
        return httpx.Response(200, json={"total": 7})

    f = _fetcher(handler, max_retries=1, host_fail_limit=2)
    for _ in range(3):
        try:
            f.post_json(URL, json_body={"searchText": "c#"})
        except RuntimeError:
            pass
    assert f._host_is_down("caci.wd1.myworkdayjobs.com")

    # The healthy tenant is untouched by its neighbour's breaker.
    assert f.post_json(other, json_body={"searchText": "c#"})["total"] == 7
    assert not f._host_is_down("leidos.wd5.myworkdayjobs.com")

    # And a success resets the streak rather than letting it accumulate all run.
    f._fails["leidos.wd5.myworkdayjobs.com"] = 1
    f.post_json(other, json_body={"searchText": ".net"})
    assert f._fails["leidos.wd5.myworkdayjobs.com"] == 0
    print("OK  breaker is per-host and resets on success")


def test_client_error_still_fails_fast():
    """A 404 (bad slug) must not be retried — that behaviour is unchanged."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404)

    f = _fetcher(handler, max_retries=3)
    try:
        f.get_json(URL)
        raise AssertionError("expected a 404 to raise")
    except RuntimeError as exc:
        assert "404" in str(exc), exc
    assert calls["n"] == 1, f"404 should not be retried, got {calls['n']} calls"
    # A dead board slug is a config problem, not a sick host: it must not count
    # toward the breaker, or a few stale slugs would disable a shared host
    # (boards-api.greenhouse.io serves every board) for the whole run.
    assert not f._host_is_down("caci.wd1.myworkdayjobs.com")
    assert f._fails.get("caci.wd1.myworkdayjobs.com", 0) == 0, f._fails
    print("OK  404 still fails fast and does not trip the breaker")


if __name__ == "__main__":
    base.time.sleep = lambda *_a, **_kw: None  # no real backoff waits in tests
    test_cookies_cleared_between_attempts()
    test_cookies_cleared_between_requests()
    test_breaker_opens_after_consecutive_failures()
    test_breaker_is_per_host_and_resets_on_success()
    test_client_error_still_fails_fast()
    print("ALL FETCHER RESILIENCE CHECKS PASSED")
