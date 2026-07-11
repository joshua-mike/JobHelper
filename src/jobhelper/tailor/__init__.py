"""Resume tailoring, cover letters, screening answers, and .docx rendering."""
from .keywords import (KEYWORD_SCHEMA, coverage, count_hits, extract_keywords,
                       term_pattern)
from .resume_docx import build_resume
from .tailor import (cover_letter, passthrough_resume, screening_answers,
                     tailor_resume)
from .verify import build_ats_report, extract_docx_text, structural_failures

__all__ = ["KEYWORD_SCHEMA", "build_ats_report", "build_resume", "cover_letter",
           "coverage", "count_hits", "extract_docx_text", "extract_keywords",
           "passthrough_resume", "screening_answers", "structural_failures",
           "tailor_resume", "term_pattern"]
