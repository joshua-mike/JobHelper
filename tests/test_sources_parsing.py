"""Offline parsing tests for the Microsoft (pcsx) and SmartRecruiters adapters.
Uses a fake fetcher returning canned payloads — no network.
Run:  python tests/test_sources_parsing.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jobhelper.sources.microsoft import MicrosoftSource
from jobhelper.sources.smartrecruiters import SmartRecruitersSource
from jobhelper.sources.workday import WorkdaySource


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
    test_fetcher_get_unchanged()
    print("\nALL SOURCE-PARSING CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
