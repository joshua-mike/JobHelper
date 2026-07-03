"""Settings endpoints: read/validate/save the config YAMLs, verify sources,
and import a resume into a proposed profile.

Saves are allowed mid-run — the daily run is a child process that read its
config at launch, so responses carry applies_next_run instead of blocking.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import ValidationError
from starlette.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
    HTTP_409_CONFLICT,
    HTTP_413_CONTENT_TOO_LARGE,
    HTTP_422_UNPROCESSABLE_CONTENT,
    HTTP_502_BAD_GATEWAY,
)

from ..config import has_anthropic
from ..llm import LLM
from ..util import ROOT
from . import resume_import, schemas, settings_store, source_verify
from .runner import MANAGER
from .settings_schemas import (
    CriteriaConfig,
    ProfileConfig,
    SourcesConfig,
    WorkdayEntry,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])

_BODY_MODELS = {
    "profile": ProfileConfig,
    "sources": SourcesConfig,
    "criteria": CriteriaConfig,
}

FALLBACK_EXTRACT_MODEL = "claude-opus-4-8"


def _run_active() -> bool:
    return MANAGER.status()["state"] == "running"


@router.get("", response_model=schemas.SettingsStatus)
def settings_status():
    return {
        "anthropic_available": has_anthropic(),
        "run_active": _run_active(),
        "profile_exists": settings_store.config_path("profile").exists(),
    }


@router.get("/{name}", response_model=schemas.ConfigPayload)
def get_config(name: schemas.ConfigName):
    data = settings_store.load_data(name)
    if data is not None:
        return {"name": name, "exists": True, "data": data}
    if name == "profile":
        # Fresh clone: prefill the form from the example so bootstrap works.
        example = settings_store.load_example_profile()
        return {"name": name, "exists": False,
                "seeded_from_example": example is not None, "data": example}
    raise HTTPException(HTTP_404_NOT_FOUND,
                        f"config/{settings_store.FILES[name]} not found.")


@router.put("/{name}", response_model=schemas.SaveResult)
def put_config(name: schemas.ConfigName, body: dict[str, Any]):
    try:
        parsed = _BODY_MODELS[name].model_validate(body)
    except ValidationError as exc:
        raise HTTPException(
            HTTP_422_UNPROCESSABLE_CONTENT,
            detail=exc.errors(include_url=False, include_input=False))
    # exclude_unset: merge exactly the keys the client sent, nothing more.
    data = parsed.model_dump(mode="json", exclude_unset=True)
    backup_path, changed = settings_store.save(name, data)
    backup = None
    if backup_path is not None:
        try:
            backup = backup_path.relative_to(ROOT).as_posix()
        except ValueError:
            backup = str(backup_path)
    return {"changed": changed,
            "applies_next_run": changed and _run_active(),
            "backup": backup}


@router.post("/sources/verify", response_model=schemas.VerifySourceResult)
def verify_source(req: schemas.VerifySourceRequest):
    entry = None
    if req.kind == "workday":
        try:
            entry = WorkdayEntry.model_validate(req.entry or {}).model_dump()
        except ValidationError:
            raise HTTPException(HTTP_422_UNPROCESSABLE_CONTENT,
                                "Workday verify needs tenant, dc, site, company.")
    elif req.kind not in source_verify.AGGREGATOR_KINDS \
            and not (req.token or "").strip():
        raise HTTPException(HTTP_422_UNPROCESSABLE_CONTENT,
                            f"{req.kind} verify needs a slug/query.")
    sources_cfg = settings_store.load_data("sources") or {}
    return source_verify.verify(
        req.kind,
        token=(req.token or "").strip() or None,
        entry=entry,
        searches=sources_cfg.get("workday_searches") or None,
    )


@router.post("/profile/import-resume", response_model=schemas.ResumeImportResult)
async def import_resume(file: UploadFile):
    raw = await file.read()
    if len(raw) > resume_import.MAX_UPLOAD_BYTES:
        raise HTTPException(HTTP_413_CONTENT_TOO_LARGE,
                            "File is over 5 MB.")
    llm = LLM()
    if not llm.available:
        raise HTTPException(
            HTTP_409_CONFLICT,
            "Resume import needs Claude. Set ANTHROPIC_API_KEY in .env and "
            "restart the dashboard.")
    try:
        text = resume_import.extract_text(file.filename or "", raw)
    except ValueError as exc:
        raise HTTPException(HTTP_400_BAD_REQUEST, str(exc))

    criteria = settings_store.load_data("criteria") or {}
    model = criteria.get("tailor_model") or FALLBACK_EXTRACT_MODEL
    extracted = resume_import.extract_profile(llm, model, text)
    if extracted is None:
        raise HTTPException(HTTP_502_BAD_GATEWAY,
                            "Claude extraction failed — check the server log.")

    base = settings_store.load_data("profile")
    bootstrapped = base is None
    if bootstrapped:
        base = settings_store.load_example_profile() or {}
    proposed, sections = resume_import.sectional_merge(
        extracted, base, bootstrapped=bootstrapped)
    return {"proposed": proposed, "sections": sections, "model": model}
