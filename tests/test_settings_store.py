"""Settings store unit checks: comment-preserving merge, atomic writes,
backups, unknown-key preservation, profile bootstrap, and schema validation.
Operates on temp copies of the real config files — never touches config/. Run:
    python tests/test_settings_store.py
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pydantic import ValidationError  # noqa: E402

from jobhelper.web import settings_store as st  # noqa: E402
from jobhelper.web.settings_schemas import (  # noqa: E402
    CriteriaConfig,
    ProfileConfig,
    SourcesConfig,
)

REAL_CONFIG = Path(__file__).resolve().parents[1] / "config"


def check(cond: bool, msg: str) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        raise AssertionError(msg)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="jobhelper-settings-"))
    cfg_dir = tmp / "config"
    cfg_dir.mkdir()
    for f in ("sources.yaml", "criteria.yaml", "profile.example.yaml"):
        shutil.copy2(REAL_CONFIG / f, cfg_dir / f)
    # Test profile = the example (real profile.yaml has PII and may not exist).
    shutil.copy2(REAL_CONFIG / "profile.example.yaml", cfg_dir / "profile.yaml")

    st.CONFIG_DIR = cfg_dir
    st.BACKUP_DIR = tmp / "backups"

    print("== load ==")
    criteria = st.load_data("criteria")
    sources = st.load_data("sources")
    profile = st.load_data("profile")
    check(isinstance(criteria.get("daily_target"), int), "criteria loads with ints")
    check(isinstance(sources["ats"]["greenhouse"], list), "sources ats lists load")
    check(profile["identity"]["full_name"] == "Jane Doe", "profile loads")

    print("== scalar edit preserves comments ==")
    # Derive edit values from the loaded config: locally tuned criteria.yaml
    # values must not turn these saves into no-ops or break backup checks.
    pre_save = st.config_path("criteria").read_text(encoding="utf-8")
    new_target = 9 if criteria["daily_target"] != 9 else 8
    new_score = 60 if criteria["min_score"] != 60 else 61
    backup, changed = st.save("criteria", {"daily_target": new_target,
                                           "min_score": new_score})
    check(changed, "save reports changed")
    text = st.config_path("criteria").read_text(encoding="utf-8")
    check(f"daily_target: {new_target}" in text, "value updated")
    check(f"min_score: {new_score}" in text, "second value updated")
    check("This is a CEILING, not" in text, "header comment kept")
    check("# ---- Role targeting ---" in text, "section comment kept")
    check(backup is not None and backup.exists(), "backup written")
    check(backup.read_text(encoding="utf-8") == pre_save,
          "backup holds pre-save content")

    print("== no-op save writes nothing ==")
    before = st.config_path("criteria").read_text(encoding="utf-8")
    backup2, changed2 = st.save("criteria", {"daily_target": new_target})
    check(not changed2 and backup2 is None, "identical save: no write, no backup")
    check(st.config_path("criteria").read_text(encoding="utf-8") == before,
          "file untouched")

    print("== list edit keeps surviving items' comments ==")
    gh = list(sources["ats"]["greenhouse"])
    gh.remove("perfectserve")          # delete one
    gh.append("newcompany")            # add one
    gh.insert(0, gh.pop(gh.index("praxent")))  # reorder another
    _, changed = st.save("sources", {"ats": {"greenhouse": gh}})
    check(changed, "sources save changed")
    text = st.config_path("sources").read_text(encoding="utf-8")
    check("perfectserve" not in text, "removed slug gone")
    check('- "newcompany"' in text, "added slug present")
    check("state-limited remote" in text, "surviving item's inline comment kept")
    check("board token is \"air\"" in text, "another surviving comment kept")
    check("# Politeness: seconds to wait" in text, "trailing section comments kept")
    reloaded = st.load_data("sources")
    check(reloaded["ats"]["greenhouse"][0] == "praxent", "reorder persisted")
    check(reloaded["ats"]["lever"] == sources["ats"]["lever"],
          "untouched sibling list intact")

    print("== workday flow-style rows survive a row edit ==")
    wd = list(sources["ats"]["workday"])
    wd.append({"tenant": "adobe", "dc": "wd5", "site": "external_experienced",
               "company": "Adobe"})
    _, _ = st.save("sources", {"ats": {"workday": wd}})
    text = st.config_path("sources").read_text(encoding="utf-8")
    check('- {tenant: "adobe"' in text or "- {tenant: adobe" in text,
          "new workday row written flow-style")
    check("myworkdayjobs.com/{site}" in text, "workday doc comment kept")

    print("== full-parity resave keeps quoting and folded style ==")
    crit_full = st.load_data("criteria")
    crit_full["judge_model"] = "claude-opus-4-8"  # one real edit
    _, changed = st.save("criteria", crit_full)   # ...but send every key
    check(changed, "full-parity save with one edit writes")
    text = st.config_path("criteria").read_text(encoding="utf-8")
    check('judge_model: "claude-opus-4-8"' in text,
          "edited string stays double-quoted")
    check('scoring: "auto"' in text, "untouched string keeps quotes")
    check('  - "engineer"' in text, "untouched list strings keep quotes")
    prof_full = st.load_data("profile")
    prof_full["identity"]["full_name"] = "Janet Doe"
    _, _ = st.save("profile", prof_full)
    ptext = st.config_path("profile").read_text(encoding="utf-8")
    check('full_name: "Janet Doe"' in ptext, "profile string stays quoted")
    check("summary: >" in ptext, "untouched folded summary keeps > style")

    print("== unknown keys survive ==")
    path = st.config_path("criteria")
    path.write_text(text_with := path.read_text(encoding="utf-8")
                    + "\n# hand-added\nmy_custom_flag: true\n", encoding="utf-8")
    _, changed = st.save("criteria", {"daily_target": 4})
    text = path.read_text(encoding="utf-8")
    check("my_custom_flag: true" in text, "hand-added unknown key kept")
    check("# hand-added" in text, "its comment kept too")

    print("== profile bootstrap seeds from example ==")
    st.config_path("profile").unlink()
    check(st.load_data("profile") is None, "profile gone")
    _, changed = st.save("profile", {"identity": {"full_name": "Josh Test"},
                                     "summary": "New summary."})
    check(changed, "bootstrap save writes")
    text = st.config_path("profile").read_text(encoding="utf-8")
    check("Josh Test" in text, "new identity merged")
    check("MASTER PROFILE" in text, "example header comment scaffolding kept")
    check("compensation:" in text and "qa_bank:" in text,
          "example sections seeded")

    print("== validation gates ==")
    for bad, model, why in [
        ({"scoring": "bogus"}, CriteriaConfig, "bad scoring literal"),
        ({"min_score": 200}, CriteriaConfig, "min_score > 100"),
        ({"daily_target": 0}, CriteriaConfig, "daily_target < 1"),
        ({"compensation": {"desired_salary_min": 200000,
                           "desired_salary_max": 100000}},
         ProfileConfig, "salary min > max"),
        ({"work_history": [{"title": "Dev"}]}, ProfileConfig,
         "work entry missing company"),
        ({"work_history": [{"company": "X", "title": "Dev",
                            "start_date": "2020-13"}]},
         ProfileConfig, "month 13"),
        ({"ats": {"workday": [{"tenant": "a", "dc": "wd1"}]}}, SourcesConfig,
         "workday row missing site/company"),
        ({"request_delay_seconds": -1}, SourcesConfig, "negative delay"),
    ]:
        try:
            model.model_validate(bad)
            check(False, f"rejects {why}")
        except ValidationError:
            check(True, f"rejects {why}")

    ok = CriteriaConfig.model_validate(st.load_data("criteria"))
    check(ok is not None, "real criteria file validates")
    check(SourcesConfig.model_validate(st.load_data("sources")) is not None,
          "real sources file validates")
    prof = st.load_example_profile()
    check(ProfileConfig.model_validate(prof) is not None,
          "example profile validates")

    print("== blank rows pruned, slugs untouched ==")
    parsed = SourcesConfig.model_validate(
        {"ats": {"lever": ["Mediafly", "  ", ""]}})
    check(parsed.ats.lever == ["Mediafly"], "blank rows dropped, case kept")

    shutil.rmtree(tmp, ignore_errors=True)
    print("\nALL SETTINGS STORE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
