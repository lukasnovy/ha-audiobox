"""The translation files render in the frontend and match each other."""

import json
from pathlib import Path
from typing import Any

import pytest

TRANSLATIONS = Path(__file__).parent.parent / "custom_components/audiobox/translations"


def _load(language: str) -> dict[str, Any]:
    return json.loads((TRANSLATIONS / f"{language}.json").read_text(encoding="utf-8"))


def _strings(node: Any, path: str = "") -> list[tuple[str, str]]:
    if isinstance(node, dict):
        return [item for key, value in node.items() for item in _strings(value, f"{path}.{key}")]
    return [(path, node)]


@pytest.mark.parametrize("language", ["en", "cs"])
def test_no_angle_brackets(language: str) -> None:
    """The frontend reads `<...>` as markup and shows a translation error."""
    bad = [path for path, text in _strings(_load(language)) if "<" in text or ">" in text]
    assert bad == []


def test_same_keys() -> None:
    english = {path for path, _ in _strings(_load("en"))}
    czech = {path for path, _ in _strings(_load("cs"))}
    assert english == czech
