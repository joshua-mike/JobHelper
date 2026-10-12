"""Offline parsing tests for the source adapters (Microsoft, SmartRecruiters,
Workday, Amazon, Adzuna), plus the per-board cap share and stored-posting skip
of the multi-board adapters (Greenhouse, Lever, Ashby, SmartRecruiters, Workday),
and Adzuna's paging back to the previous run under a call budget (ITEM-40).
Uses a fake fetcher returning canned payloads — no network.
Run:  python tests/test_sources_parsing.py
"""
from __future__ import annotations

import logging
import os
import sys
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jobhelper.sources import adzuna
from jobhelper.sources.adzuna import AdzunaSource
from jobhelper.sources.amazon import AmazonSource
from jobhelper.sources.ashby import AshbySource
from jobhelper.sources.greenhouse import GreenhouseSource
from jobhelper.sources.lever import LeverSource
from jobhelper.sources.microsoft import MicrosoftSource
from jobhelper.sources.registry import build_sources
from jobhelper.sources.smartrecruiters import SmartRecruitersSource
from jobhelper.sources.workday import WorkdaySource
from jobhelper.util import get_logger, stable_hash


class FakeFetcher:
    """Returns canned JSON keyed by a substring of the URL (GET and POST)."""
    def __init__(self, routes):
        self.routes = routes

    def _resolve(self, url, arg):
        for key, payload in self.routes.items():
            if key in url:
                return payload(arg) if callable(payload) else payload
        raise AssertionError(f"unexpected url: {url}")

    def get_json(self, url, params=None, headers=None):
        return self._resolve(url, params)

    def post_json(self, url, json_body, headers=None):
        return self._resolve(url, json_body)


class WorkdayFake:
    """Multi-tenant Workday CXS stub: {tenant: [externalPath, ...]}.

    Pages the search like the real endpoint and records every detail call, so
    tests can assert which postings cost a detail fetch.
    """
    def __init__(self, boards):
        self.boards = boards
        self.detail_calls = []

    @staticmethod
    def _tenant(url):
        return url.split("//", 1)[1].split(".", 1)[0]

    def post_json(self, url, json_body, headers=None):
        paths = self.boards[self._tenant(url)]
        start = json_body["offset"]
        return {"total": len(paths), "jobPostings": [
            {"title": f"Software Engineer {p}", "externalPath": p,
             "locationsText": "Remote", "bulletFields": [p.rsplit("_", 1)[-1]]}
            for p in paths[start:start + json_body["limit"]]]}

    def get_json(self, url, params=None, headers=None):
        self.detail_calls.append(url)
        tenant, ext = self._tenant(url), "/job/" + url.split("/job/", 1)[1]
        return {"jobPostingInfo": {
            "jobDescription": f"<p>Posting {ext}</p>", "startDate": "2026-10-01",
            "externalUrl": f"https://{tenant}.wd1.myworkdayjobs.com/External{ext}"}}


def _wd_tenants(*names):
    return [{"tenant": n, "dc": "wd1", "site": "External", "company": n.upper()}
            for n in names]


# The list-only ATSes: one board fetch carries every posting, in each API's shape.
_LIST_ATS = {
    "greenhouse": (GreenhouseSource, lambda board, ids: {"jobs": [
        {"id": i, "absolute_url": f"https://boards.greenhouse.io/{board}/jobs/{i}",
         "title": f"Software Engineer {i}", "location": {"name": "Remote"},
         "content": "<p>Build things.</p>", "updated_at": "2026-10-01T00:00:00Z"}
        for i in ids]}),
    "lever": (LeverSource, lambda board, ids: [
        {"id": i, "hostedUrl": f"https://jobs.lever.co/{board}/{i}",
         "text": f"Software Engineer {i}", "categories": {"location": "Remote"},
         "workplaceType": "remote", "descriptionPlain": "Build things.",
         "createdAt": 1790000000000}
        for i in ids]),
    "ashby": (AshbySource, lambda board, ids: {"jobs": [
        {"id": i, "jobUrl": f"https://jobs.ashbyhq.com/{board}/{i}",
         "title": f"Software Engineer {i}", "location": "Remote", "isRemote": True,
         "descriptionHtml": "<p>Build things.</p>", "publishedAt": "2026-10-01"}
        for i in ids]}),
}


class BoardFake:
    """Multi-board stub for a list-only ATS: {board: n_postings or [ids]}; a count
    gives ids '{board}_{n}'."""
    def __init__(self, payload, boards):
        self.payload = payload
        self.boards = boards

    def get_json(self, url, params=None, headers=None):
        # .../boards/{token}/jobs (Greenhouse) or .../{site} (Lever, Ashby)
        parts = url.split("/")
        board = parts[-2] if parts[-1] == "jobs" else parts[-1]
        ids = self.boards[board]
        if isinstance(ids, int):
            ids = [f"{board}_{n}" for n in range(ids)]
        return self.payload(board, ids)


class SmartRecruitersFake:
    """Multi-slug SmartRecruiters stub: {slug: [(id, name, postingUrl), ...]}.

    Pages the list like the real endpoint (limit/offset/totalFound) and records
    every list page and detail call. A detail call for an id in `failing` raises.
    """
    def __init__(self, boards, failing=()):
        self.boards = boards
        self.failing = set(failing)
        self.list_calls = []
        self.detail_calls = []

    def get_json(self, url, params=None, headers=None):
        slug, _, pid = url.split("/companies/", 1)[1].partition("/postings")
        posts = self.boards[slug]
        if not pid:
            self.list_calls.append((slug, params["offset"]))
            page = posts[params["offset"]:params["offset"] + params["limit"]]
            return {"totalFound": len(posts), "content": [
                {"id": p, "name": name, "company": {"name": slug.upper()},
                 "location": {"city": "Austin", "country": "us", "remote": True}}
                for p, name, _ in page]}
        self.detail_calls.append(url)
        if pid.lstrip("/") in self.failing:
            raise RuntimeError("HTTP 503")
        posting_url = next(u for p, _, u in posts if p == pid.lstrip("/"))
        return {"postingUrl": posting_url, "jobAd": {"sections": {
            "jobDescription": {"text": f"<p>Posting {pid}</p>"}}}}


def _sr_board(slug, n):
    return [(f"{slug}{i}", f"Software Engineer {i}",
             f"https://jobs.smartrecruiters.com/{slug}/{slug}{i}-software-engineer-{i}")
            for i in range(n)]


class AdzunaFake:
    """Adzuna search stub: {query: page(n) -> [result, ...]} serves page n of a
    query, n read from the URL path; a page function may raise. Records every
    (url, params) call."""
    def __init__(self, queries):
        self.queries = queries
        self.calls = []

    def get_json(self, url, params=None, headers=None):
        self.calls.append((url, dict(params or {})))
        page = int(url.rsplit("/", 1)[1])
        return {"count": 99999, "results": self.queries[params["what"]](page)}

    def pages_of(self, query):
        return [int(u.rsplit("/", 1)[1]) for u, p in self.calls if p["what"] == query]


def _az_ago(hours):
    t = datetime.now(timezone.utc) - timedelta(hours=hours)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _az_item(ad_id, created):
    return {"id": str(ad_id), "title": f"Remote Software Engineer {ad_id}",
            "description": "Remote role.", "created": created,
            "redirect_url": f"https://www.adzuna.com/land/ad/{ad_id}",
            "company": {"display_name": "Acme"}, "location": {"display_name": "US"}}


def _az_pages(prefix, size=50, step_hours=0.25, last_page=None, last_size=None,
              created=None):
    """Newest-first pages of `size` ads named {prefix}{n}, each `step_hours` older
    than the one before; page `last_page` holds `last_size` ads and nothing comes
    after it (endless without one). `created` overrides every timestamp."""
    def page(n):
        if last_page is not None and n > last_page:
            return []
        count = last_size if n == last_page else size
        start = (n - 1) * size
        return [_az_item(f"{prefix}{i}", created if created is not None
                         else _az_ago(i * step_hours))
                for i in range(start, start + count)]
    return page


def _az_hash(ad_id):
    """An Adzuna ad's job_hash: volatile_url makes it source + ad id."""
    return stable_hash("adzuna", ad_id)


@contextmanager
def _adzuna_keys(app_id="test-id", app_key="test-key"):
    old = {k: os.environ.get(k) for k in ("ADZUNA_APP_ID", "ADZUNA_APP_KEY")}
    os.environ["ADZUNA_APP_ID"], os.environ["ADZUNA_APP_KEY"] = app_id, app_key
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@contextmanager
def _logged():
    """The jobhelper log messages emitted inside the block."""
    messages: list[str] = []

    class Collect(logging.Handler):
        def emit(self, record):
            messages.append(record.getMessage())

    logger, handler = get_logger(), Collect()
    level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        yield messages
    finally:
        logger.removeHandler(handler)
        logger.setLevel(level)


def check(cond, msg):
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        raise AssertionError(msg)


def test_microsoft():
    print("== Microsoft pcsx adapter ==")
    search = {"data": {"count": 1, "positions": [{
        "id": 123, "displayJobId": "200012345", "name": "Senior Software Engineer",
        "standardizedLocations": ["Redmond, WA, US"], "postedTs": 1781622057,
        "workLocationOption": "onsite", "positionUrl": "/careers/job/123",
        "department": "Software Engineering",
    }]}}
    detail = {"data": {
        "jobDescription": "<b>Overview</b><p>Build great .NET systems.</p>",
        "efcustomTextWorkSite": ["0 days / week in-office – remote"],
        "displayJobId": "200012345",
    }}
    f = FakeFetcher({"/search": search, "/position_details": detail})
    jobs = MicrosoftSource(f, cap=400, queries=["x"], per_query=5).fetch()
    check(len(jobs) == 1, "one job")
    j = jobs[0]
    check(j.company == "Microsoft", f"company is Microsoft ({j.company})")
    check(j.source_job_id == "200012345", f"source_job_id uses displayJobId ({j.source_job_id})")
    check(j.url == "https://apply.careers.microsoft.com/careers/job/123", f"url built ({j.url})")
    check(j.remote_type == "remote", f"remote from efcustomTextWorkSite, not workLocationOption ({j.remote_type})")
    check("great .net systems" in j.description_clean.lower(), "description pulled from detail")
    check(j.location == "Redmond, WA, US", f"location ({j.location})")


def test_smartrecruiters():
    print("== SmartRecruiters adapter ==")
    listing = {"totalFound": 1, "content": [{
        "id": "abc123", "name": "Staff Software Engineer",
        "company": {"name": "Visa"}, "releasedDate": "2026-06-03T11:08:12.368Z",
        "location": {"city": "Austin", "region": "TX", "country": "us", "remote": True},
        "department": {"label": "Technology"},
    }]}
    detail = {
        "postingUrl": "https://jobs.smartrecruiters.com/Visa/abc123-staff",
        "applyUrl": "https://jobs.smartrecruiters.com/Visa/abc123-staff?oga=true",
        "jobAd": {"sections": {
            "jobDescription": {"title": "Job Description", "text": "<p>Own backend services.</p>"},
            "qualifications": {"title": "Qualifications", "text": "<p>8+ years.</p>"},
        }},
    }
    f = FakeFetcher({"/postings/abc123": detail, "/postings": listing})
    jobs = SmartRecruitersSource(f, cap=400, slugs=["Visa"]).fetch()
    check(len(jobs) == 1, "one job")
    j = jobs[0]
    check(j.company == "Visa", f"company from company.name ({j.company})")
    check(j.url == "https://jobs.smartrecruiters.com/Visa/abc123-staff", f"url is postingUrl ({j.url})")
    check(j.remote_type == "remote", f"remote from location.remote bool ({j.remote_type})")
    check(j.location == "Austin, TX, US", f"location formatted ({j.location})")
    check("own backend services" in j.description_clean.lower(), "description from jobAd sections")
    check("8+ years" in j.description_clean.lower(), "multiple sections concatenated")


def test_workday():
    print("== Workday CXS adapter ==")
    listing = {"total": 1, "jobPostings": [{
        "title": "Software Developer (.NET)", "externalPath": "/job/Norco-CA/SW-Dev_327568",
        "locationsText": "Norco, CA, US", "postedOn": "Posted 5 Days Ago",
        "bulletFields": ["327568"],
    }]}
    detail = {"jobPostingInfo": {
        "title": "Software Developer (.NET)", "jobDescription": "<p>Build .NET services.</p>",
        "location": "Norco, CA, US", "startDate": "2026-06-16", "timeType": "Full time",
        "externalUrl": "https://caci.wd1.myworkdayjobs.com/External/job/Norco-CA/SW-Dev_327568",
    }}
    # detail URL contains the externalPath ('/job/...'); list URL ends in '/jobs'
    f = FakeFetcher({"/SW-Dev_327568": detail, "/jobs": listing})
    tenants = [{"tenant": "caci", "dc": "wd1", "site": "External", "company": "CACI"}]
    jobs = WorkdaySource(f, cap=400, tenants=tenants, searches=[".net"], per_search=5).fetch()
    check(len(jobs) == 1, "one job")
    j = jobs[0]
    check(j.company == "CACI", f"company from config ({j.company})")
    check(j.source_job_id == "327568", f"source_job_id from bulletFields ({j.source_job_id})")
    check(j.url.endswith("/SW-Dev_327568"), f"url is externalUrl ({j.url})")
    check(j.date_posted == "2026-06-16", f"date from startDate ({j.date_posted})")
    check("build .net services" in j.description_clean.lower(), "description from jobPostingInfo")
    check(j.location == "Norco, CA, US", f"location from locationsText ({j.location})")
    check(j.remote_type == "unknown", f"onsite city -> unknown remote ({j.remote_type})")

    print("== Workday remote detection from locationsText ==")
    listing2 = {"total": 1, "jobPostings": [{
        "title": "Backend Engineer", "externalPath": "/job/Remote/Be_99",
        "locationsText": "USA - Remote", "bulletFields": ["99"]}]}
    detail2 = {"jobPostingInfo": {"jobDescription": "<p>x</p>", "startDate": "2026-06-01",
                                  "externalUrl": "https://x.wd1.myworkdayjobs.com/External/job/Remote/Be_99"}}
    f2 = FakeFetcher({"/Be_99": detail2, "/jobs": listing2})
    j2 = WorkdaySource(f2, cap=400, tenants=[{"tenant": "x", "dc": "wd1", "site": "External"}],
                       searches=[""], per_search=5).fetch()[0]
    check(j2.remote_type == "remote", f"'USA - Remote' -> remote ({j2.remote_type})")
    check(j2.company == "X", f"company falls back to tenant.title() ({j2.company})")

    print("== Workday structured remoteType beats the location string ==")
    # iHerb tags remote roles "Home Office, CA" and never writes "remote" in the
    # description, so the location sniff alone silently dropped all of them.
    listing3 = {"total": 1, "jobPostings": [{
        "title": "Sr. Software Engineer II - Catalog",
        "externalPath": "/job/Home-Office-CA/SE_R107002",
        "locationsText": "Home Office, CA", "bulletFields": ["R107002"]}]}
    detail3 = {"jobPostingInfo": {
        "jobDescription": "<p>Catalog services.</p>", "location": "Home Office, CA",
        "remoteType": "Remote",
        "externalUrl": "https://iherb.wd5.myworkdayjobs.com/Careers/job/Home-Office-CA/SE_R107002"}}
    f3 = FakeFetcher({"/SE_R107002": detail3, "/jobs": listing3})
    j3 = WorkdaySource(f3, cap=400, searches=[""], per_search=5, tenants=[
        {"tenant": "iherb", "dc": "wd5", "site": "Careers", "company": "iHerb"}]).fetch()[0]
    check(j3.remote_type == "remote",
          f"remoteType 'Remote' beats 'Home Office, CA' ({j3.remote_type})")

    print("== Workday remoteType 'Onsite' is recorded as onsite ==")
    listing4 = {"total": 1, "jobPostings": [{
        "title": "Systems Engineer", "externalPath": "/job/Chantilly-VA/SE_1",
        "locationsText": "Chantilly, VA", "bulletFields": ["1"]}]}
    detail4 = {"jobPostingInfo": {"jobDescription": "<p>y</p>", "location": "Chantilly, VA",
                                  "remoteType": "Onsite", "externalUrl": "https://x/y"}}
    f4 = FakeFetcher({"/SE_1": detail4, "/jobs": listing4})
    j4 = WorkdaySource(f4, cap=400, searches=[""], per_search=5, tenants=[
        {"tenant": "caci", "dc": "wd1", "site": "External"}]).fetch()[0]
    check(j4.remote_type == "onsite", f"remoteType 'Onsite' -> onsite ({j4.remote_type})")


def test_workday_tenant_share():
    # ITEM-37: the cap used to be first-come across tenants, so the first few
    # in sources.yaml used all of it every run and the rest were never crawled.
    print("== Workday: the cap is split fairly, every tenant crawled ==")
    boards = {t: [f"/job/Remote/{t}_{n}" for n in range(5)] for t in ("a", "b", "c")}
    f = WorkdayFake(boards)
    jobs = WorkdaySource(f, cap=6, tenants=_wd_tenants("a", "b", "c"),
                         searches=[""], per_search=25).fetch()
    by = Counter(j.company for j in jobs)
    check(by == {"A": 2, "B": 2, "C": 2}, f"2 jobs from each tenant ({dict(by)})")
    check(len(f.detail_calls) == 6, f"no detail calls past the cap ({len(f.detail_calls)})")

    print("== Workday: a small tenant's unused share rolls forward ==")
    boards = {"a": ["/job/Remote/a_0"],
              "b": [f"/job/Remote/b_{n}" for n in range(5)],
              "c": [f"/job/Remote/c_{n}" for n in range(5)]}
    jobs = WorkdaySource(WorkdayFake(boards), cap=6, tenants=_wd_tenants("a", "b", "c"),
                         searches=[""], per_search=25).fetch()
    by = Counter(j.company for j in jobs)
    check(by == {"A": 1, "B": 2, "C": 3}, f"A 1, B 5//2, C the rest ({dict(by)})")


def test_workday_known_skip():
    print("== Workday: stored postings skip the detail call ==")
    boards = {"a": [f"/job/Remote/a_{n}" for n in range(3)]}
    first = WorkdaySource(WorkdayFake(boards), cap=400, tenants=_wd_tenants("a"),
                          searches=[""], per_search=25).fetch()
    stored = {j.job_hash for j in first[:2]}
    f = WorkdayFake(boards)
    again = WorkdaySource(f, cap=400, tenants=_wd_tenants("a"), searches=[""],
                          per_search=25, is_known=stored.__contains__).fetch()
    check([j.url for j in again] == [first[2].url],
          "only the unstored posting comes back")
    check(len(f.detail_calls) == 1,
          f"one detail call; the hash is predicted before it ({len(f.detail_calls)})")

    print("== Workday: stored postings don't use up the cap ==")
    boards = {"a": [f"/job/Remote/a_{n}" for n in range(4)],
              "b": [f"/job/Remote/b_{n}" for n in range(2)]}
    seen = WorkdaySource(WorkdayFake(boards), cap=400, tenants=_wd_tenants("a", "b"),
                         searches=[""], per_search=25).fetch()
    stored = {j.job_hash for j in seen if j.company == "A"
              and not j.url.endswith("a_3")}
    jobs = WorkdaySource(WorkdayFake(boards), cap=2, tenants=_wd_tenants("a", "b"),
                         searches=[""], per_search=25,
                         is_known=stored.__contains__).fetch()
    check(sorted(j.url.rsplit("/", 1)[1] for j in jobs) == ["a_3", "b_0"],
          f"A's one new posting plus B's share ({[j.url for j in jobs]})")


def test_list_ats_board_share():
    # ITEM-39: Greenhouse/Lever/Ashby joined every board then cut at the cap, so
    # the boards at the end of sources.yaml never produced a row.
    for kind, (cls, payload) in _LIST_ATS.items():
        print(f"== {kind}: the cap is split fairly, every board kept ==")
        jobs = cls(BoardFake(payload, {"a": 5, "b": 5, "c": 5}), 6, ["a", "b", "c"]).fetch()
        ids = [j.source_job_id for j in jobs]
        check(ids == ["a_0", "a_1", "b_0", "b_1", "c_0", "c_1"],
              f"the first 2 from each board ({ids})")

        print(f"== {kind}: a small board's unused share rolls forward ==")
        jobs = cls(BoardFake(payload, {"a": 1, "b": 5, "c": 5}), 6, ["a", "b", "c"]).fetch()
        by = Counter(j.company for j in jobs)
        check(by == {"A": 1, "B": 2, "C": 3}, f"A 1, B 5//2, C the rest ({dict(by)})")

        # Every posting is in hand, so unused cap can go to an EARLIER board too.
        print(f"== {kind}: unused share flows back to an earlier board ==")
        jobs = cls(BoardFake(payload, {"a": 10, "b": 0, "c": 0}), 6, ["a", "b", "c"]).fetch()
        ids = [j.source_job_id for j in jobs]
        check(ids == [f"a_{n}" for n in range(6)], f"A takes all 6, not 6//3 ({ids})")

        print(f"== {kind}: small boards keep all theirs, the big one the rest ==")
        jobs = cls(BoardFake(payload, {"a": 5, "b": 1, "c": 1}), 6, ["a", "b", "c"]).fetch()
        ids = [j.source_job_id for j in jobs]
        check(ids == ["a_0", "a_1", "a_2", "a_3", "b_0", "c_0"],
              f"A 4, B 1, C 1, in sources.yaml order ({ids})")


def test_list_ats_duplicates():
    for kind, (cls, payload) in _LIST_ATS.items():
        print(f"== {kind}: a repeated posting takes one slot ==")
        boards = {"a": ["a_0", "a_0", "a_1"], "b": 1}
        jobs = cls(BoardFake(payload, boards), 3, ["a", "b"]).fetch()
        ids = [j.source_job_id for j in jobs]
        check(ids == ["a_0", "a_1", "b_0"], f"a_0 once, a_1 not crowded out ({ids})")


def test_list_ats_known_skip():
    for kind, (cls, payload) in _LIST_ATS.items():
        print(f"== {kind}: stored postings don't use up the cap ==")
        boards = {"a": 4, "b": 2}
        seen = cls(BoardFake(payload, boards), 400, ["a", "b"]).fetch()
        stored = {j.job_hash for j in seen
                  if j.company == "A" and j.source_job_id != "a_3"}
        jobs = cls(BoardFake(payload, boards), 2, ["a", "b"],
                   is_known=stored.__contains__).fetch()
        ids = [j.source_job_id for j in jobs]
        check(ids == ["a_3", "b_0"], f"A's one new posting plus B's share ({ids})")


def test_smartrecruiters_slug_share():
    print("== SmartRecruiters: the cap is split fairly, no detail past a share ==")
    f = SmartRecruitersFake({s: _sr_board(s, 5) for s in ("a", "b", "c")})
    jobs = SmartRecruitersSource(f, cap=6, slugs=["a", "b", "c"]).fetch()
    by = Counter(j.company for j in jobs)
    check(by == {"A": 2, "B": 2, "C": 2}, f"2 jobs from each slug ({dict(by)})")
    check(len(f.detail_calls) == 6, f"no detail calls past the cap ({len(f.detail_calls)})")

    print("== SmartRecruiters: the list stops paging once the share is reached ==")
    f = SmartRecruitersFake({s: _sr_board(s, 250) for s in ("a", "b")})
    SmartRecruitersSource(f, cap=6, slugs=["a", "b"]).fetch()
    check(f.list_calls == [("a", 0), ("b", 0)],
          f"one list page per slug, not all 3 ({f.list_calls})")

    print("== SmartRecruiters: a repeated id takes one detail call and one slot ==")
    posts = _sr_board("a", 2)
    f = SmartRecruitersFake({"a": [posts[0], posts[0], posts[1]]})
    jobs = SmartRecruitersSource(f, cap=400, slugs=["a"]).fetch()
    ids = [j.source_job_id for j in jobs]
    check(ids == ["a0", "a1"], f"a0 once ({ids})")
    check(len(f.detail_calls) == 2, f"one detail call for a0 ({len(f.detail_calls)})")


def test_smartrecruiters_known_skip():
    print("== SmartRecruiters: stored postings skip the detail call ==")
    boards = {"a": _sr_board("a", 4), "b": _sr_board("b", 2)}
    seen = SmartRecruitersSource(SmartRecruitersFake(boards), 400, ["a", "b"]).fetch()
    stored = {j.job_hash for j in seen if j.company == "A" and j.source_job_id != "a3"}
    f = SmartRecruitersFake(boards)
    jobs = SmartRecruitersSource(f, 2, ["a", "b"], is_known=stored.__contains__).fetch()
    ids = [j.source_job_id for j in jobs]
    check(ids == ["a3", "b0"], f"A's one new posting plus B's share ({ids})")
    check(len(f.detail_calls) == 2,
          f"no detail call for a stored posting ({len(f.detail_calls)})")

    print("== SmartRecruiters: stored postings are paged past, not counted ==")
    boards = {"a": _sr_board("a", 250)}
    stored = {j.job_hash for j in
              SmartRecruitersSource(SmartRecruitersFake(boards), 120, ["a"]).fetch()}
    f = SmartRecruitersFake(boards)
    jobs = SmartRecruitersSource(f, 10, ["a"], is_known=stored.__contains__).fetch()
    ids = [j.source_job_id for j in jobs]
    check(ids == [f"a{n}" for n in range(120, 130)], f"the 10 after the stored 120 ({ids})")
    check(len(f.detail_calls) == 10, f"detail calls for new ones only ({len(f.detail_calls)})")
    check(f.list_calls == [("a", 0), ("a", 100)],
          f"second page reached, third never requested ({f.list_calls})")

    print("== SmartRecruiters: a posting stored under the fallback url is recognized ==")
    # Its detail call failed last run, so it was stored as {slug}/{id}, which the
    # postingUrl prediction never matches.
    boards = {"a": _sr_board("a", 3)}
    first = SmartRecruitersSource(SmartRecruitersFake(boards, failing={"a0"}),
                                  400, ["a"]).fetch()
    check(first[0].url == "https://jobs.smartrecruiters.com/a/a0",
          f"a failed detail stores the fallback url ({first[0].url})")
    f = SmartRecruitersFake(boards)
    jobs = SmartRecruitersSource(f, 2, ["a"],
                                 is_known={first[0].job_hash}.__contains__).fetch()
    ids = [j.source_job_id for j in jobs]
    check(ids == ["a1", "a2"], f"a0 skipped, not counted toward the cap ({ids})")
    check(not any(u.endswith("/a0") for u in f.detail_calls),
          f"no detail call for a0 ({f.detail_calls})")

    print("== SmartRecruiters: the predicted hash matches real postingUrls ==")
    # Real stored URLs (2026-10-11): {slug}/{id}-{slugified name}, no dash trimming.
    tricky = [
        ("744000135330850", " Client Executive – West Region",
         "744000135330850--client-executive-west-region"),
        ("744000100000001", "Data Scientist (Contract)",
         "744000100000001-data-scientist-contract-"),
        ("744000100000002", "[Expression of Interest] - Product Owner",
         "744000100000002--expression-of-interest-product-owner"),
        ("744000100000003", "Analista de Dados em Finanças Sênior",
         "744000100000003-analista-de-dados-em-financas-senior"),
        ("744000100000004", ".Net Engineer", "744000100000004--net-engineer"),
    ]
    boards = {"Experian": [(p, name, f"https://jobs.smartrecruiters.com/Experian/{tail}")
                           for p, name, tail in tricky]}
    first = SmartRecruitersSource(SmartRecruitersFake(boards), 400, ["Experian"]).fetch()
    check([j.url for j in first] == [u for _, _, u in boards["Experian"]],
          "urls are the detail's postingUrl")
    f = SmartRecruitersFake(boards)
    again = SmartRecruitersSource(f, 400, ["Experian"],
                                  is_known={j.job_hash for j in first}.__contains__).fetch()
    check(again == [] and f.detail_calls == [],
          f"every tricky title recognized before its detail call ({len(f.detail_calls)})")


def test_registry_passes_is_known():
    print("== build_sources hands the stored-posting check to the multi-board adapters ==")
    def is_known(h):
        return False
    multi = ("greenhouse", "lever", "ashby", "smartrecruiters", "workday")
    cfg = {"ats": {"workday": _wd_tenants("a"), "greenhouse": ["a"], "lever": ["a"],
                   "ashby": ["a"], "smartrecruiters": ["a"]},
           "workday_searches": [""]}
    srcs = [s for s in build_sources(cfg, is_known=is_known) if s.name in multi]
    check(sorted(s.name for s in srcs) == sorted(multi), "all five built")
    for s in srcs:
        check(s.is_known is is_known, f"{s.name} gets is_known")
    for s in build_sources(cfg):
        if s.name in multi:
            check(s.is_known("anything") is False,
                  f"{s.name}: without it every posting counts as new (Settings Verify path)")


def test_amazon():
    print("== Amazon search.json adapter ==")
    search = {"hits": 1, "jobs": [{
        "id_icims": "10454256", "title": "Software Development Engineer, AWS",
        "job_path": "/en/jobs/10454256/software-development-engineer-aws",
        "normalized_location": "Virtual Location, USA", "city": "Virtual",
        "posted_date": "June 19, 2026", "job_category": "Software Development",
        "description": "<p>Build distributed systems.</p>",
        "basic_qualifications": "<p>5+ years.</p>",
        "preferred_qualifications": "<p>.NET a plus.</p>",
    }]}
    f = FakeFetcher({"/search.json": search})
    jobs = AmazonSource(f, cap=400, queries=["sde"], per_query=5).fetch()
    check(len(jobs) == 1, "one job")
    j = jobs[0]
    check(j.company == "Amazon", f"company is Amazon ({j.company})")
    check(j.source_job_id == "10454256", f"id from id_icims ({j.source_job_id})")
    check(j.url == "https://www.amazon.jobs/en/jobs/10454256/software-development-engineer-aws",
          f"url from job_path ({j.url})")
    check(j.date_posted == "2026-06-19", f"posted_date normalized to ISO ({j.date_posted})")
    check(j.remote_type == "remote", f"'Virtual Location' -> remote ({j.remote_type})")
    check("distributed systems" in j.description_clean.lower(), "description inline")
    check(".net a plus" in j.description_clean.lower(), "qualifications concatenated")


def test_adzuna():
    print("== Adzuna adapter ==")
    search = {"count": 2776, "results": [
        {
            "id": "5501", "title": "Remote .NET C# Developer",
            "description": "Build APIs. " * 30,  # truncated-style blob
            "redirect_url": "https://www.adzuna.com/land/ad/5501",
            "company": {"display_name": "Gainwell Technologies"},
            "location": {"display_name": "Andover, Butler County"},
            "category": {"label": "IT Jobs", "tag": "it-jobs"},
            "created": "2026-07-01T21:11:28Z",
            "salary_min": 90000.0, "salary_max": 120000.0,
            "salary_is_predicted": "0",
        },
        {
            "id": "5502", "title": "C# Engineer",
            "description": "Onsite-ish text without the r-word visible.",
            "redirect_url": "https://www.adzuna.com/land/ad/5502",
            "company": {"display_name": "Acme"},
            "location": {"display_name": "Columbus, Ohio"},
            "category": {"label": "IT Jobs", "tag": "it-jobs"},
            "created": "2026-07-02T10:00:00Z",
            "salary_min": 88493.23, "salary_max": 88493.23,
            "salary_is_predicted": "1",
        },
        {   # duplicate id must be dropped
            "id": "5501", "title": "Remote .NET C# Developer (dupe)",
            "redirect_url": "https://www.adzuna.com/land/ad/5501b",
        },
    ]}
    f = FakeFetcher({"api.adzuna.com": search})
    with _adzuna_keys():
        jobs = AdzunaSource(f, cap=400, queries=["c#"], per_query=50).fetch()
    check(len(jobs) == 2, f"two jobs (dupe id dropped) ({len(jobs)})")
    j = jobs[0]
    check(j.company == "Gainwell Technologies", f"company ({j.company})")
    check(j.url == "https://www.adzuna.com/land/ad/5501", "url is redirect_url")
    check(j.remote_type == "remote", f"remote detected in title ({j.remote_type})")
    check(j.salary_min == 90000 and j.salary_max == 120000,
          "listed salary kept")
    check(j.date_posted == "2026-07-01T21:11:28Z", "created carried as-is")
    check("IT Jobs" in j.tags and "c#" in j.tags, f"tags ({j.tags})")
    k = jobs[1]
    check(k.remote_type == "unknown", f"no visible 'remote' -> unknown ({k.remote_type})")
    check(k.salary_min is None and k.salary_max is None,
          "predicted salary kept OUT of salary fields")
    check(k.extra.get("salary_predicted", {}).get("min") == 88493.23,
          "predicted salary stored in extra")

    # No keys -> graceful skip, no fetch attempted
    with _adzuna_keys("", ""):
        jobs2 = AdzunaSource(FakeFetcher({}), cap=400, queries=["c#"]).fetch()
    check(jobs2 == [], "missing keys -> [] without any HTTP call")


def test_adzuna_pages_to_cutoff():
    print("== Adzuna: pages back to the previous run's start minus the overlap ==")
    # 50 ads a page, each 15 min older: page 1 is 0-12.25h old, page 2 12.5-24.75h,
    # page 3 25-37.25h. Previous run 24h ago -> cutoff 36h ago, crossed on page 3.
    f = AdzunaFake({"c#": _az_pages("a")})
    last = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    with _adzuna_keys():
        jobs = AdzunaSource(f, 400, ["c#"], 500, last_run_started=last).fetch()
    check(f.pages_of("c#") == [1, 2, 3],
          f"pages 1-3, none after the cutoff page ({f.pages_of('c#')})")
    check(len(jobs) == 150, f"the cutoff page's postings are kept ({len(jobs)})")
    check(jobs[-1].source_job_id == "a149", f"oldest ad kept ({jobs[-1].source_job_id})")
    url, params = f.calls[0]
    check(url == "https://api.adzuna.com/v1/api/jobs/us/search/1", f"page in path ({url})")
    check(f.calls[2][0].endswith("/search/3"), f"page 3 in path ({f.calls[2][0]})")
    check(params["results_per_page"] == 50 and params["sort_by"] == "date"
          and params["what_and"] == "remote" and params["what"] == "c#"
          and params["app_id"] == "test-id" and params["app_key"] == "test-key",
          f"query params ({params})")

    # A missing or unparseable `created` never stops paging.
    for bad in ("not-a-date", ""):
        f = AdzunaFake({"c#": _az_pages("b", last_page=3, last_size=10, created=bad)})
        with _adzuna_keys():
            jobs = AdzunaSource(f, 400, ["c#"], 500, last_run_started=last).fetch()
        check(f.pages_of("c#") == [1, 2, 3] and len(jobs) == 110,
              f"created={bad!r}: pages on to the end ({f.pages_of('c#')}, {len(jobs)})")


def test_adzuna_ignores_source_cap():
    print("== Adzuna: per_source_cap doesn't cut paging short (ITEM-40 review) ==")
    # A share of the cap bound a busy query after ~2 pages; the next run's cutoff
    # then moved past the rest of the day, so it was never read. Same pages as
    # above: 3 pages of new ads above a cutoff 36h back, crossed on page 3.
    f = AdzunaFake({"software engineer": _az_pages("a")})
    last = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    with _adzuna_keys(), _logged() as logged:
        jobs = AdzunaSource(f, 10, ["software engineer"], 500,
                            last_run_started=last).fetch()
    check(f.pages_of("software engineer") == [1, 2, 3],
          f"every page up to the cutoff read ({f.pages_of('software engineer')})")
    check(len(jobs) == 150, f"more new postings than cap=10 returned ({len(jobs)})")
    check("adzuna[software engineer]: 150 new, 0 stored skipped, 3 pages (reached cutoff)"
          in logged, f"stopped by the cutoff ({logged})")
    check("adzuna: 150 new jobs from 1 queries (0 stored postings skipped), "
          "3 of 75 API calls used" in logged, f"closing total line ({logged})")


def test_adzuna_end_of_results():
    print("== Adzuna: a short page ends the query ==")
    f = AdzunaFake({"c#": _az_pages("a", step_hours=0.01, last_page=2, last_size=20)})
    with _adzuna_keys():
        jobs = AdzunaSource(f, 400, ["c#"], 500).fetch()
    check(f.pages_of("c#") == [1, 2], f"stops after the short page ({f.pages_of('c#')})")
    check(len(jobs) == 70, f"every result kept ({len(jobs)})")


def test_adzuna_per_query():
    print("== Adzuna: per_query bounds results read per query, across pages ==")
    # Settings Verify's call: AdzunaSource(fetcher, 5, [token], 5) -> one call.
    f = AdzunaFake({"c#": _az_pages("a", size=5, step_hours=0.01)})
    with _adzuna_keys():
        jobs = AdzunaSource(f, 5, ["c#"], 5).fetch()
    check(len(f.calls) == 1, f"one call ({len(f.calls)})")
    check(f.calls[0][1]["results_per_page"] == 5, "results_per_page = per_query when < 50")
    check(len(jobs) == 5, f"5 results ({len(jobs)})")

    f = AdzunaFake({"c#": _az_pages("a", step_hours=0.01)})
    with _adzuna_keys():
        jobs = AdzunaSource(f, 400, ["c#"], 120).fetch()
    check(f.pages_of("c#") == [1, 2, 3], f"3 pages of 50 for 120 ({f.pages_of('c#')})")
    check(all(p["results_per_page"] == 50 for _, p in f.calls), "50 per page")
    check(len(jobs) == 120, f"no more than per_query read ({len(jobs)})")


def test_adzuna_call_budget():
    print("== Adzuna: the call budget is shared fairly across queries ==")
    endless = {q: _az_pages(q, step_hours=0.001) for q in ("a", "b")}
    f = AdzunaFake(endless)
    with _adzuna_keys():
        jobs = AdzunaSource(f, 400, ["a", "b"], 500, max_calls=6).fetch()
    check(len(f.calls) == 6, f"total calls = max_calls ({len(f.calls)})")
    check(f.pages_of("a") == [1, 2, 3] and f.pages_of("b") == [1, 2, 3],
          f"3 calls each ({f.pages_of('a')}, {f.pages_of('b')})")
    check(len(jobs) == 300, f"every page's postings kept ({len(jobs)})")

    # What a query doesn't use carries forward.
    f = AdzunaFake({"a": _az_pages("a", step_hours=0.001, last_page=1, last_size=10),
                    "b": _az_pages("b", step_hours=0.001)})
    with _adzuna_keys():
        AdzunaSource(f, 400, ["a", "b"], 500, max_calls=6).fetch()
    check(f.pages_of("a") == [1] and f.pages_of("b") == [1, 2, 3, 4, 5],
          f"b gets a's unused calls ({f.pages_of('a')}, {f.pages_of('b')})")

    # Fewer calls than queries: one call each while any are left, never more.
    f = AdzunaFake(endless)
    with _adzuna_keys():
        AdzunaSource(f, 400, ["a", "b"], 500, max_calls=1).fetch()
    check(f.pages_of("a") == [1] and f.pages_of("b") == [],
          f"never more than max_calls ({f.pages_of('a')}, {f.pages_of('b')})")


def test_adzuna_known_and_repeats():
    print("== Adzuna: stored postings and repeats across queries aren't returned ==")
    # a: 10 stored ads, then 20 new ones. b: repeats 5 of a's, a stored ad, then
    # 24 new ones of its own. One short page each.
    def page_a(n):
        return [_az_item(f"a{i}", _az_ago(i * 0.001)) for i in range(30)] if n == 1 else []

    def page_b(n):
        if n > 1:
            return []
        repeats = [_az_item(f"a{i}", _az_ago(0)) for i in range(10, 15)]
        return repeats + [_az_item(f"b{i}", _az_ago(i * 0.001)) for i in range(25)]

    stored = {_az_hash(f"a{i}") for i in range(10)} | {_az_hash("b0")}
    f = AdzunaFake({"a": page_a, "b": page_b})
    with _adzuna_keys(), _logged() as logged:
        jobs = AdzunaSource(f, 10, ["a", "b"], 500, is_known=stored.__contains__).fetch()
    ids = [j.source_job_id for j in jobs]
    check(ids == [f"a{i}" for i in range(10, 30)] + [f"b{i}" for i in range(1, 25)],
          f"every new ad returned, stored and repeated ones skipped ({ids})")
    check(len({j.job_hash for j in jobs}) == len(jobs), "no duplicates")
    check(not stored & {j.job_hash for j in jobs}, "no stored posting returned")
    check("adzuna[a]: 20 new, 10 stored skipped, 1 page (end of results)" in logged
          and "adzuna[b]: 24 new, 1 stored skipped, 5 repeats, 1 page (end of results)"
          in logged, f"per-query lines ({logged})")
    check(any(m.startswith("adzuna: 44 new jobs from 2 queries (11 stored postings "
                           "skipped)") for m in logged), f"stored skips totalled ({logged})")


def test_adzuna_max_days_old():
    print("== Adzuna: max_days_old bounds the search to the cutoff ==")
    now = datetime.now(timezone.utc)

    def sent(**kw):
        f = AdzunaFake({"c#": _az_pages("a", last_page=1, last_size=1)})
        with _adzuna_keys():
            AdzunaSource(f, 400, ["c#"], 500, **kw).fetch()
        return f.calls[0][1]["max_days_old"]

    check(sent() == 30, f"no previous run, no max_age_days -> 30 ({sent()})")
    check(sent(max_age_days=14) == 14,
          f"no previous run -> max_age_days ({sent(max_age_days=14)})")
    day = (now - timedelta(days=1)).isoformat()
    check(sent(last_run_started=day) == 2,
          f"1 day ago + 12h overlap -> 2 ({sent(last_run_started=day)})")
    hour = (now - timedelta(hours=1)).isoformat()
    check(sent(last_run_started=hour) == 1, f"1 hour ago -> 1 ({sent(last_run_started=hour)})")
    old = (now - timedelta(days=40)).isoformat()
    check(sent(last_run_started=old, max_age_days=14) == 14,
          f"previous run older than max_age_days -> max_age_days "
          f"({sent(last_run_started=old, max_age_days=14)})")


def test_adzuna_failed_page():
    print("== Adzuna: a failed page ends that query; later queries still run ==")
    ok = _az_pages("a", step_hours=0.001)

    def flaky(n):
        if n == 2:
            raise RuntimeError("GET failed after 3 tries (HTTP 503)")
        return ok(n)

    f = AdzunaFake({"a": flaky,
                    "b": _az_pages("b", step_hours=0.001, last_page=1, last_size=5)})
    with _adzuna_keys():
        jobs = AdzunaSource(f, 400, ["a", "b"], 500).fetch()
    check(f.pages_of("a") == [1, 2], f"a stops at the failed page ({f.pages_of('a')})")
    check(f.pages_of("b") == [1], f"b still runs ({f.pages_of('b')})")
    check(len(jobs) == 55, f"a's page 1 + b kept ({len(jobs)})")


def test_registry_configures_adzuna():
    print("== build_sources wires Adzuna's paging, call budget and spacing ==")
    def is_known(h):
        return False
    last = "2026-10-11T19:46:02+00:00"
    cfg = {"ats": {"adzuna": ["c#", ".net developer"]},
           "adzuna_per_query": 300, "adzuna_max_calls": 40}
    az = next(s for s in build_sources(cfg, is_known=is_known, last_run_started=last,
                                       max_age_days=14) if s.name == "adzuna")
    check(az.queries == ["c#", ".net developer"], f"queries ({az.queries})")
    check(az.is_known is is_known, "gets is_known")
    check(az.last_run_started == last, f"gets last_run_started ({az.last_run_started})")
    check(az.max_age_days == 14, f"gets max_age_days ({az.max_age_days})")
    check(az.per_query == 300 and az.max_calls == 40,
          f"per_query/max_calls from config ({az.per_query}, {az.max_calls})")
    check(az.fetcher.host_delays.get(adzuna.HOST) == adzuna.MIN_INTERVAL == 2.5,
          f"Fetcher spaces Adzuna calls ({az.fetcher.host_delays})")

    az = next(s for s in build_sources({"ats": {"adzuna": ["c#"]}}) if s.name == "adzuna")
    check(az.per_query == 500 and az.max_calls == 75,
          f"defaults 500/75 ({az.per_query}, {az.max_calls})")
    check(az.last_run_started is None and az.max_age_days == 30,
          f"no previous run; 30 days back by default ({az.max_age_days})")
    check(az.is_known("anything") is False, "every posting new without is_known")


def test_fetcher_get_unchanged():
    # The POST refactor must not change GET behavior: get_json still routes GETs.
    from jobhelper.sources.base import Fetcher
    print("== Fetcher GET path intact after POST refactor ==")
    check(hasattr(Fetcher, "post_json"), "post_json added")
    check(hasattr(Fetcher, "get_json"), "get_json preserved")


def main() -> int:
    test_microsoft()
    test_smartrecruiters()
    test_workday()
    test_workday_tenant_share()
    test_workday_known_skip()
    test_list_ats_board_share()
    test_list_ats_duplicates()
    test_list_ats_known_skip()
    test_smartrecruiters_slug_share()
    test_smartrecruiters_known_skip()
    test_registry_passes_is_known()
    test_amazon()
    test_adzuna()
    test_adzuna_pages_to_cutoff()
    test_adzuna_ignores_source_cap()
    test_adzuna_end_of_results()
    test_adzuna_per_query()
    test_adzuna_call_budget()
    test_adzuna_known_and_repeats()
    test_adzuna_max_days_old()
    test_adzuna_failed_page()
    test_registry_configures_adzuna()
    test_fetcher_get_unchanged()
    print("\nALL SOURCE-PARSING CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
