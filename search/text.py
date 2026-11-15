"""Tokenizing for keyword search: lowercase words, stopwords removed, light suffix stemming.

Dependency-free on purpose so results are reproducible without extra packages.
"""

from __future__ import annotations

import re

_WORD = re.compile(r"[a-z0-9]+")

STOPWORDS = frozenset("""
a about above after again against all am an and any are as at be because been before being below
between both but by can could did do does doing down during each few for from further had has have
having he her here hers herself him himself his how i if in into is it its itself just me more most
my myself no nor not now of off on once only or other our ours ourselves out over own same she should
so some such than that the their theirs them themselves then there these they this those through to
too under until up very was we were what when where which while who whom why will with would you your
yours yourself yourselves shall may must also any upon such thereof therein whether within without
""".split())

# Longest suffix first; a suffix is stripped only if at least 3 characters remain.
_SUFFIXES = (
    "ational", "ization", "ations", "ation", "nesses", "ements", "ement", "ments", "ment",
    "ities", "ity", "ings", "ing", "ions", "ion", "ness", "edly", "ies", "ers", "est", "ed",
    "er", "es", "ly", "s",
)


def stem(word: str) -> str:
    if len(word) <= 3 or word.isdigit():
        return word
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)] + ("y" if suffix == "ies" else "")
            break
    if word.endswith("e") and len(word) > 4:
        word = word[:-1]
    return word


def tokenize(text: str) -> list[str]:
    return [stem(w) for w in _WORD.findall(text.lower()) if w not in STOPWORDS]
