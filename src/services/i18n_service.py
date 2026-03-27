import json
from pathlib import Path
from typing import Dict


DEFAULT_LANGUAGE = "es"
SUPPORTED_LANGUAGES = {"es", "en"}


def load_translations(locales_dir: Path) -> Dict[str, Dict[str, str]]:
    translations: Dict[str, Dict[str, str]] = {}

    for lang in sorted(SUPPORTED_LANGUAGES):
        path = locales_dir / f"{lang}.json"
        if not path.exists():
            translations[lang] = {}
            continue

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                translations[lang] = {str(k): str(v) for k, v in data.items()}
            else:
                translations[lang] = {}
        except Exception:
            translations[lang] = {}

    return translations


def normalize_language(value: str) -> str:
    lang = str(value or "").strip().lower()
    if lang in SUPPORTED_LANGUAGES:
        return lang
    return DEFAULT_LANGUAGE
