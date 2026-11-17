"""Fetcher resilience: cookie-pin shedding + per-host circuit breaker.

Regression cover for the 2026-08-12 incident, where one long-lived httpx.Client
got pinned to a sick Workday backend (__cflb + wday_vps_cookie) and then replayed
those cookies on every retry, so a healthy tenant looked like a total outage for
an hour. No network — httpx.MockTransport serves the responses.
Run:  python tests/test_fetcher_resilience.py
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import httpx

from jobhelper.sources import base
from jobhelper.sources.base import Fetcher

URL = "https://caci.wd1.myworkdayjobs.com/wday/cxs/caci/External/jobs"


def _fetcher(handler, delay: float = 0.0, **kw) -> Fetcher:
    """A Fetcher whose client is backed by a mock transport, with sleeps disabled."""
    f = Fetcher(delay=delay, use_cache=False, **kw)
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


def test_host_delay_overrides_default():
    """ITEM-40: a host in host_delays is spaced by its own delay (Adzuna's
    per-minute limit); every other host keeps the default delay."""
    adzuna = "https://api.adzuna.com/v1/api/jobs/us/search/1"
    slept: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": []})

    f = _fetcher(handler, delay=1.0, host_delays={"api.adzuna.com": 2.5})
    real_sleep = base.time.sleep
    base.time.sleep = slept.append
    try:
        f.get_json(adzuna)
        f.get_json(adzuna)
        f.get_json(URL)
        f.get_json(URL)
    finally:
        base.time.sleep = real_sleep
    assert len(slept) == 2, slept
    assert 2.0 < slept[0] <= 2.5, f"Adzuna should wait ~2.5s, waited {slept[0]}"
    assert 0.5 < slept[1] <= 1.0, f"other hosts keep the 1.0s default, waited {slept[1]}"

    # A host delay below the default never shortens the wait.
    slept.clear()
    f = _fetcher(handler, delay=1.0, host_delays={"api.adzuna.com": 0.1})
    base.time.sleep = slept.append
    try:
        f.get_json(adzuna)
        f.get_json(adzuna)
    finally:
        base.time.sleep = real_sleep
    assert len(slept) == 1 and 0.5 < slept[0] <= 1.0, slept
    print("OK  per-host delay spaces that host only")


def test_threads_on_one_host_stay_spaced():
    """Sources are fetched concurrently: threads sharing a host must queue up
    `delay` apart, not all send at once."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    slept: list[float] = []
    f = _fetcher(handler, delay=1.0)
    real_sleep = base.time.sleep
    base.time.sleep = slept.append
    try:
        threads = [threading.Thread(target=f.get_json, args=(URL,)) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        base.time.sleep = real_sleep
    # One thread sends at once; the others wait ~1s, ~2s and ~3s for their slots.
    waits = sorted(slept)
    assert len(waits) == 3, waits
    for want, got in zip((1.0, 2.0, 3.0), waits):
        assert want - 0.5 < got <= want, f"slots should be 1s apart, waited {waits}"
    print("OK  threads sharing a host stay spaced")


LEIDOS = "https://leidos.wd5.myworkdayjobs.com/wday/cxs/leidos/External/jobs"
WORKDAY = ["myworkdayjobs.com"]


def test_shared_limit_paces_hosts_as_one():
    """2026-11-17: Workday counts requests across all tenants, so tenant hosts
    under a shared-limit domain must queue together, not each at their own 1/s."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    slept: list[float] = []
    f = _fetcher(handler, delay=1.0, shared_limits=WORKDAY)
    real_sleep = base.time.sleep
    base.time.sleep = slept.append
    try:
        f.get_json(URL)                                   # caci: sends at once
        f.get_json(LEIDOS)                                # another tenant: must wait
        f.get_json("https://api.lever.co/v0/postings/x")  # unrelated host: no wait
    finally:
        base.time.sleep = real_sleep
    assert len(slept) == 1 and 0.5 < slept[0] <= 1.0, slept
    print("OK  hosts under a shared limit are paced as one")


def test_429_backs_off_and_holds_the_shared_limit():
    """A 429 must wait far longer than a sick backend's 1s, and the wait must
    hold every host under the same limit, not just the one that was refused."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429 if calls["n"] == 1 else 200, json={})

    slept: list[float] = []
    f = _fetcher(handler, delay=1.0, shared_limits=WORKDAY)
    real_sleep = base.time.sleep
    base.time.sleep = slept.append
    try:
        f.get_json(URL)      # 429, then the retry succeeds
        assert len(slept) == 1 and 4.5 < slept[0] <= 5.0, (
            f"the retry should wait ~5s, waited {slept}")
        f.get_json(LEIDOS)   # a sibling tenant queues behind the hold too
        assert len(slept) == 2 and slept[1] > 5.0, slept
    finally:
        base.time.sleep = real_sleep
    print("OK  a 429 backs off ~5s and holds the whole shared limit")


def test_rate_limit_trips_the_shared_breaker():
    """When Workday keeps refusing us, every tenant is skipped: they share the
    limit, so each burning its own retries would only prolong the block."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429)

    f = _fetcher(handler, max_retries=1, host_fail_limit=2, shared_limits=WORKDAY)
    for _ in range(2):
        try:
            f.get_json(URL)
        except RuntimeError:
            pass
    try:
        f.get_json(LEIDOS)
        raise AssertionError("expected the sibling tenant to be skipped")
    except RuntimeError as exc:
        assert "marked down" in str(exc), exc
    assert calls["n"] == 2, f"the skipped tenant still sent a request: {calls['n']}"

    # Without a shared limit a 429 stays that host's own problem.
    f = _fetcher(handler, max_retries=1, host_fail_limit=2)
    for _ in range(2):
        try:
            f.get_json(URL)
        except RuntimeError:
            pass
    assert f._host_is_down("caci.wd1.myworkdayjobs.com")
    assert not f._host_is_down("leidos.wd5.myworkdayjobs.com")
    print("OK  rate-limit refusals skip every host under the shared limit")


def test_bot_challenge_stops_the_shared_limit_at_once():
    """2026-11-17: once Cloudflare challenged the client, every Workday tenant
    answered 429 + cf-mitigated. Retrying only keeps the flag up, so the first
    challenge must end the run for every host under the shared limit."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, headers={"cf-mitigated": "challenge"},
                              text="<!DOCTYPE html>")

    f = _fetcher(handler, shared_limits=WORKDAY)
    for url in (URL, URL, LEIDOS):
        try:
            f.get_json(url)
            raise AssertionError("expected the challenge to raise")
        except RuntimeError:
            pass
    assert calls["n"] == 1, f"a challenge must not be retried or re-sent: {calls['n']}"
    assert f._host_is_down("leidos.wd5.myworkdayjobs.com")
    assert not f._host_is_down("api.lever.co")
    print("OK  a bot challenge is not retried and skips the whole shared limit")


def test_client_stores_no_cookies():
    """The shared client's own jar refuses cookies, so one thread's response
    can't pin another thread's request to a backend."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={},
                              headers={"set-cookie": "__cflb=pin; Path=/"})

    f = Fetcher(delay=0.0, use_cache=False)
    f._client = httpx.Client(transport=httpx.MockTransport(handler),
                             cookies=f._client.cookies.jar)
    f.get_json(URL)
    assert len(f._client.cookies.jar) == 0, list(f._client.cookies.jar)
    print("OK  the client's jar stores no cookies")


if __name__ == "__main__":
    base.time.sleep = lambda *_a, **_kw: None  # no real backoff waits in tests
    test_cookies_cleared_between_attempts()
    test_cookies_cleared_between_requests()
    test_breaker_opens_after_consecutive_failures()
    test_breaker_is_per_host_and_resets_on_success()
    test_client_error_still_fails_fast()
    test_host_delay_overrides_default()
    test_threads_on_one_host_stay_spaced()
    test_shared_limit_paces_hosts_as_one()
    test_429_backs_off_and_holds_the_shared_limit()
    test_rate_limit_trips_the_shared_breaker()
    test_bot_challenge_stops_the_shared_limit_at_once()
    test_client_stores_no_cookies()
    print("ALL FETCHER RESILIENCE CHECKS PASSED")
