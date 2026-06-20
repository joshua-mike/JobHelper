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


class FakeFetcher:
    """Returns canned JSON keyed by a substring of the URL."""
    def __init__(self, routes):
        self.routes = routes

    def get_json(self, url, params=None, headers=None):
        for key, payload in self.routes.items():
            if key in url:
                return payload(params) if callable(payload) else payload
        raise AssertionError(f"unexpected url: {url}")


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


def main() -> int:
    test_microsoft()
    test_smartrecruiters()
    print("\nALL SOURCE-PARSING CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
