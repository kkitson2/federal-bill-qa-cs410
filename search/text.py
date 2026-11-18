"""Tokenizing for keyword search (bag of words, CS410 Week 1-2): lowercase alphanumeric words,
stopwords removed, Porter stemming. Dependency-free so results are reproducible anywhere."""

from __future__ import annotations

import re

from .porter import stem

_WORD = re.compile(r"[a-z0-9]+")

STOPWORDS = frozenset("""
a about above after again against all am an and any are as at be because been before being below
between both but by can could did do does doing down during each few for from further had has have
having he her here hers herself him himself his how i if in into is it its itself just me more most
my myself no nor not now of off on once only or other our ours ourselves out over own same she should
so some such than that the their theirs them themselves then there these they this those through to
too under until up very was we were what when where which while who whom why will with would you your
yours yourself yourselves shall may must also upon thereof therein whether within without
""".split())


def tokenize(text: str) -> list[str]:
    return [stem(w) for w in _WORD.findall(text.lower()) if w not in STOPWORDS]
