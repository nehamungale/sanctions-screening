"""Text folding shared by names and countries.

Kept separate so ``countries`` can fold keys without importing the name matcher.
"""

from __future__ import annotations

import re
import unicodedata

# Applied after combining marks are stripped, before lowercase.
_TRANSLIT = str.maketrans({
    "ł": "l",
    "Ł": "L",
    "đ": "d",
    "Đ": "D",
    "ø": "o",
    "Ø": "O",
    "ß": "ss",
    "æ": "ae",
    "Æ": "AE",
    "œ": "oe",
    "Œ": "OE",
    "þ": "th",
    "Þ": "TH",
    "ı": "i",
    "İ": "I",
})

_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "`": "'", "ʼ": "'"})


def norm_text(value: object) -> str:
    """NFKD, drop combining marks, transliterate ł/đ/ø/ß/æ/œ/þ/ı, lowercase."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.translate(_TRANSLIT)
    return text.lower()


def country_fold(value: object) -> str:
    """Lookup key: ``norm_text``, apostrophes removed, punctuation to spaces."""
    text = norm_text(str(value).translate(_APOSTROPHES) if value is not None else "")
    text = text.replace("'", "")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())
