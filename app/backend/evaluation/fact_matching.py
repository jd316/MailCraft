"""Fact-inclusion detection used by the Fact Inclusion metric AND the
runtime generation path so the response's `fact_coverage` is verified.

Strategy (cheap → expressive):
1. Extract **salient tokens** from the fact: numbers, dates, proper nouns,
   product codes, and content words longer than 3 chars.
2. Match against the email body with normalized casing and light stemming
   (drop trailing 's'/'ed'/'ing').
3. A fact counts as included when *every* required salient token has a hit,
   or ≥70% of its content tokens are present when no "required" tokens exist.
   Numbers/dates/quoted-strings are treated as required.

This is deliberately dependency-free so tests are deterministic. An optional
embedding re-check would sit on top of this as a tiebreaker — not required
for the assignment.
"""

from __future__ import annotations

import re
import string

# Words we never treat as salient.
_STOPWORDS = frozenset(
    ["a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have", "in", "into", "is", "it", "of", "on", "or", "our", "that", "the", "their", "there", "these", "they", "this", "to", "was", "we", "were", "will", "with", "your", "you", "i", "me", "my", "us", "do", "does", "did", "not", "no", "any", "some", "all", "any", "can", "could", "should", "would", "may", "might", "will", "shall", "also", "more", "most", "less", "than", "then", "just", "very", "just", "really", "quite", "after", "before", "during", "between", "within", "about", "over", "under", "up", "down", "off", "over", "please", "kindly", "ensure", "let", "know", "need", "must", "want", "need", "needs"]
)

_NUMBER_RE = re.compile(r"\b\d[\d,.:/\-%]*\b")
_QUOTED_RE = re.compile(r"[\"'`]([^\"'`]{2,})[\"'`]")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z\-']+")


def _normalize(text: str) -> str:
    return text.lower()


def _simple_stem(token: str) -> str:
    for suffix in ("'s", "ing", "ed", "es", "s"):
        if len(token) > 4 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def _salient_tokens(fact: str) -> tuple[set[str], set[str]]:
    """Return (required, helpful) token sets for the fact.

    Required tokens must appear for the fact to count as included. These are
    numbers, dates, quoted strings, and multi-capital tokens (e.g. ACME, CR-2187,
    iPhone). Sentence-initial capitals are treated as helpful, not required,
    because they are ambiguous.
    """
    required: set[str] = set()
    helpful: set[str] = set()

    for m in _NUMBER_RE.findall(fact):
        required.add(m.lower().strip(string.punctuation))
    for m in _QUOTED_RE.findall(fact):
        required.add(m.lower().strip())

    words = list(_WORD_RE.finditer(fact))
    for idx, m in enumerate(words):
        w = m.group(0)
        wl = w.lower()
        if wl in _STOPWORDS or len(wl) <= 3:
            continue
        is_first_word = idx == 0 or fact[: m.start()].strip() in {"", "-"}
        has_internal_cap = any(c.isupper() for c in w[1:])
        has_leading_cap = w[0].isupper()
        looks_proper = has_internal_cap or (has_leading_cap and not is_first_word)
        if looks_proper:
            required.add(_simple_stem(wl))
        else:
            helpful.add(_simple_stem(wl))
    if len(required) > 5:
        keep = sorted(required, key=len, reverse=True)[:5]
        required = set(keep)
    return required, helpful


def _body_index(body: str) -> str:
    # Keep punctuation so numbers like "May 12" / "42%" still match.
    return _normalize(body)


def _contains(body_norm: str, token: str) -> bool:
    if not token:
        return False
    token = token.strip().lower()
    if not token:
        return False
    if token.isdigit() or any(ch.isdigit() for ch in token):
        # For numbers, allow a looser substring match (e.g. "12" inside "May 12th").
        return token in body_norm
    # word-boundary match with a light stemmer fallback
    pat = rf"\b{re.escape(token)}[a-z']*\b"
    if re.search(pat, body_norm):
        return True
    stem = _simple_stem(token)
    if stem != token:
        pat2 = rf"\b{re.escape(stem)}[a-z']*\b"
        if re.search(pat2, body_norm):
            return True
    return False


def fact_included(fact: str, email_body: str) -> tuple[bool, str | None]:
    """Return (included, evidence_snippet)."""
    body_norm = _body_index(email_body)
    required, helpful = _salient_tokens(fact)

    if required:
        missing = [t for t in required if not _contains(body_norm, t)]
        if missing:
            return False, None
        return True, _evidence_snippet(email_body, required | helpful)

    # No strong tokens — fall back to content-word coverage.
    tokens = list(helpful)
    if not tokens:
        # Degenerate fact (all stopwords); do a coarse substring check.
        short = fact.strip().lower()
        return (short in body_norm, short if short in body_norm else None)

    hit = sum(1 for t in tokens if _contains(body_norm, t))
    ratio = hit / max(1, len(tokens))
    if ratio >= 0.7:
        return True, _evidence_snippet(email_body, set(tokens))
    return False, None


def _evidence_snippet(body: str, tokens: set[str]) -> str | None:
    if not tokens:
        return None
    lower = body.lower()
    best: tuple[int, int] | None = None
    for token in tokens:
        idx = lower.find(token.lower())
        if idx == -1:
            continue
        if best is None or idx < best[0]:
            best = (idx, idx + len(token))
    if best is None:
        return None
    start = max(0, best[0] - 20)
    end = min(len(body), best[1] + 40)
    snippet = body[start:end].strip()
    return snippet[:120]


def fact_inclusion_score(facts: list[str], email_body: str) -> tuple[float, list[dict]]:
    """Score from 0.0 to 1.0 — share of facts included."""
    if not facts:
        return 1.0, []
    per_fact: list[dict] = []
    hits = 0
    for fact in facts:
        included, evidence = fact_included(fact, email_body)
        per_fact.append(
            {"fact": fact, "included": included, "evidence": evidence}
        )
        if included:
            hits += 1
    return hits / len(facts), per_fact
