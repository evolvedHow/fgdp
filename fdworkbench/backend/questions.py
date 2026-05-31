"""
FDP Policy Chat — Question Library loader
==========================================
Loads questions.yml and seeds it into fdp.question_library on startup.
Provides lookup helpers used by the pipeline.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_YAML_PATH = Path(__file__).parent.parent / "questions.yml"
_library: list[dict] = []   # in-memory copy of YAML for fast matching


def load_and_seed() -> list[dict]:
    """
    Parse questions.yml and upsert every entry into fdp.question_library.
    Called once at startup. Returns the loaded questions list.
    """
    from .cache import upsert_library_question  # noqa: PLC0415

    if not _YAML_PATH.exists():
        logger.warning("questions.yml not found at %s — skipping seed", _YAML_PATH)
        return []

    try:
        import yaml  # noqa: PLC0415
    except ImportError:
        logger.warning("PyYAML not installed — skipping question library seed")
        return []

    raw = yaml.safe_load(_YAML_PATH.read_text())
    questions = raw.get("questions", [])

    seeded = 0
    for q in questions:
        try:
            upsert_library_question(
                id=q["id"],
                question_text=q["question"],
                sql_query=q.get("sql"),
                source="predefined",
                tags=q.get("tags", []),
                expires_hours=q.get("expires_hours"),
                display_order=q.get("order", 999),
            )
            seeded += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to seed question %s: %s", q.get("id"), exc)

    logger.info("Seeded %d/%d questions into library", seeded, len(questions))
    global _library
    _library = questions
    return questions


def find_library_match(question: str) -> dict | None:
    """
    Check if the question exactly matches a library entry (normalized comparison).
    Returns the library dict if matched, else None.
    """
    normalized = _normalize(question)
    for q in _library:
        if _normalize(q["question"]) == normalized:
            return q
    return None


def _normalize(text: str) -> str:
    """Lowercase, collapse whitespace, strip trailing punctuation."""
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    text = text.rstrip("?.,!")
    return text
