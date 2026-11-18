"""The Porter stemming algorithm (M. F. Porter, 1980, "An algorithm for suffix stripping").

Faithful to the original paper's five steps, dependency-free. In each step the longest matching
suffix is chosen first and its condition is then tested; if the condition fails, no shorter suffix
is tried (as in Porter's reference implementation).
"""

from __future__ import annotations

_VOWELS = frozenset("aeiou")


def _is_consonant(word: str, i: int) -> bool:
    ch = word[i]
    if ch in _VOWELS:
        return False
    if ch == "y":
        return i == 0 or not _is_consonant(word, i - 1)
    return True


def _measure(stem: str) -> int:
    """m in [C](VC)^m[V]: the number of vowel-consonant sequences."""
    m, prev_vowel = 0, False
    for i in range(len(stem)):
        vowel = not _is_consonant(stem, i)
        if prev_vowel and not vowel:
            m += 1
        prev_vowel = vowel
    return m


def _has_vowel(stem: str) -> bool:
    return any(not _is_consonant(stem, i) for i in range(len(stem)))


def _ends_double_consonant(word: str) -> bool:
    return len(word) >= 2 and word[-1] == word[-2] and _is_consonant(word, len(word) - 1)


def _ends_cvc(word: str) -> bool:
    """*o: ends consonant-vowel-consonant, where the last consonant is not w, x or y."""
    return (len(word) >= 3 and _is_consonant(word, len(word) - 3) and not _is_consonant(word, len(word) - 2)
            and _is_consonant(word, len(word) - 1) and word[-1] not in "wxy")


def _replace(word: str, rules: tuple[tuple[str, str], ...], min_measure: int) -> str:
    for suffix, replacement in sorted(rules, key=lambda r: -len(r[0])):
        if word.endswith(suffix):
            stem = word[: -len(suffix)]
            return stem + replacement if _measure(stem) > min_measure else word
    return word


_STEP2 = (("ational", "ate"), ("tional", "tion"), ("enci", "ence"), ("anci", "ance"), ("izer", "ize"),
          ("abli", "able"), ("alli", "al"), ("entli", "ent"), ("eli", "e"), ("ousli", "ous"),
          ("ization", "ize"), ("ation", "ate"), ("ator", "ate"), ("alism", "al"), ("iveness", "ive"),
          ("fulness", "ful"), ("ousness", "ous"), ("aliti", "al"), ("iviti", "ive"), ("biliti", "ble"))
_STEP3 = (("icate", "ic"), ("ative", ""), ("alize", "al"), ("iciti", "ic"), ("ical", "ic"), ("ful", ""),
          ("ness", ""))
_STEP4 = ("al", "ance", "ence", "er", "ic", "able", "ible", "ant", "ement", "ment", "ent", "ion", "ou",
          "ism", "ate", "iti", "ous", "ive", "ize")


def stem(word: str) -> str:
    if len(word) <= 2:
        return word

    # Step 1a
    if word.endswith("sses"):
        word = word[:-2]
    elif word.endswith("ies"):
        word = word[:-2]
    elif word.endswith("ss"):
        pass
    elif word.endswith("s"):
        word = word[:-1]

    # Step 1b
    if word.endswith("eed"):
        if _measure(word[:-3]) > 0:
            word = word[:-1]
    else:
        for suffix in ("ed", "ing"):
            if word.endswith(suffix) and _has_vowel(word[: -len(suffix)]):
                word = word[: -len(suffix)]
                if word.endswith(("at", "bl", "iz")):
                    word += "e"
                elif _ends_double_consonant(word) and word[-1] not in "lsz":
                    word = word[:-1]
                elif _measure(word) == 1 and _ends_cvc(word):
                    word += "e"
                break

    # Step 1c
    if word.endswith("y") and _has_vowel(word[:-1]):
        word = word[:-1] + "i"

    word = _replace(word, _STEP2, 0)
    word = _replace(word, _STEP3, 0)

    # Step 4
    for suffix in sorted(_STEP4, key=len, reverse=True):
        if word.endswith(suffix):
            stem_ = word[: -len(suffix)]
            if _measure(stem_) > 1 and (suffix != "ion" or stem_.endswith(("s", "t"))):
                word = stem_
            break

    # Step 5a
    if word.endswith("e"):
        stem_ = word[:-1]
        m = _measure(stem_)
        if m > 1 or (m == 1 and not _ends_cvc(stem_)):
            word = stem_

    # Step 5b
    if _measure(word) > 1 and _ends_double_consonant(word) and word.endswith("l"):
        word = word[:-1]
    return word
