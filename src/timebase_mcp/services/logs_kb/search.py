from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from typing import cast

from timebase_mcp.models.logs_kb import LogsKBMatch, SearchLogsKBResult

from .artifact import RuntimeEntry, load_runtime_entries

_DEFAULT_LIMIT = 5
_QUERY_LINE_LIMIT = 8
_QUERY_CHAR_LIMIT = 900
_TOKEN_CHARS = "_.:#/$-"
_TOKEN_SPLIT_CHARS = "._:#/$-"
_ADVICE_TOKEN_CHARS = "._$-"
_STRIP_TOKEN_CHARS = "`'\"()[]{}<>,;"
_STACK_FRAME_HEAD_CHARS = ".$<>_"
_LOG_LEVELS = ("TRACE", "DEBUG", "INFO", "WARN", "ERROR", "FATAL", "SEVERE")
_ALWAYS_SALIENT_LOG_LEVELS = frozenset({"ERROR", "FATAL", "SEVERE"})
_SALIENT_TEXT_SNIPPETS = (
    "caused by:",
    "exception",
    "error",
    "failed",
    "failure",
    "timeout",
    "timed out",
    "rejected",
)
_FIELD_WEIGHTS = {
    "symptom_signature": 5.0,
    "log_excerpt": 3.0,
    "symptom_summary": 1.5,
    "root_cause": 1.0,
    # search_text is a broad recall field built from the authoring entry.
    # Keep its weight low so it can surface useful hints like tags or suggested
    # actions without overpowering the more precise structured fields.
    "search_text": 0.5,
}
_CAMEL_PART_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z]|\d|$)|[A-Z]?[a-z]+|\d+")
_EMBEDDED_LOG_START_RE = re.compile(
    r"\s+(?=(?:[A-Za-z0-9_.-]+\s+\|\s+)?\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d{3,9})?\s+(?:TRACE|DEBUG|INFO|WARN|ERROR|FATAL|SEVERE)\b)"
)
_EXCEPTION_RE = re.compile(r"\b[A-Za-z0-9_$.]+(?:Exception|Error)\b")
_TOKEN_ALIASES = {
    "server": ("service",),
    "service": ("server",),
    "connect": ("connection", "connectivity", "reach"),
    "connection": ("connect", "connectivity", "reach"),
    "connectivity": ("connect", "connection", "reach"),
    "reach": ("connect", "connection", "connectivity"),
    "reachable": ("connect", "connection", "connectivity", "reach"),
    "reached": ("connect", "connection", "connectivity", "reach"),
}
_DISTINCTIVE_TOKEN_STOPWORDS = frozenset(
    {
        "error",
        "exception",
        "failed",
        "failure",
        "startup",
        "start",
        "stopped",
        "stopping",
        "reason",
        "invalid",
        "impossible",
        "unable",
        "cannot",
        "with",
        "from",
        "main",
        "bytes",
        "timebase",
        "java",
        "info",
    }
)
_GENERIC_EXCEPTION_TOKENS = frozenset(
    {
        "java",
        "exception",
        "error",
        "io",
        "ioexception",
        "java.io.ioexception",
    }
)
_VAGUE_QUERY_TOKENS = {
    "error",
    "exception",
    "failed",
    "failure",
    "startup",
    "start",
    "stopped",
    "stopping",
    "abort",
    "aborted",
    "problem",
    "issue",
    "unable",
    "cannot",
}

SearchCorpus = tuple[RuntimeEntry, ...]


@dataclass(frozen=True, slots=True)
class _EntryDoc:
    entry: RuntimeEntry
    field_tokens: dict[str, Counter[str]]
    all_tokens: frozenset[str]
    exception_head: str | None
    frame_head: str | None


@dataclass(frozen=True, slots=True)
class _RankedMatch:
    match: LogsKBMatch
    score: float


@dataclass(frozen=True, slots=True)
class _SearchIndex:
    docs: list[_EntryDoc]
    idf: dict[str, float]


@dataclass(frozen=True, slots=True)
class _QueryFeatures:
    query_lower: str
    distinctive_tokens: tuple[str, ...]
    has_stack_frame: bool


def clear_search_index_cache() -> None:
    _search_index.cache_clear()


@lru_cache(maxsize=8)
def _search_index(entries: SearchCorpus) -> _SearchIndex:
    docs: list[_EntryDoc] = []
    doc_freq: Counter[str] = Counter()
    for entry in entries:
        field_tokens = {
            "symptom_signature": _tokenize(entry.symptom_signature),
            "log_excerpt": _tokenize(_excerpt_text_for_index(entry.log_excerpt)),
            "symptom_summary": _tokenize(entry.symptom_summary),
            "root_cause": _tokenize(entry.root_cause),
            "search_text": _tokenize(entry.search_text or ""),
        }
        doc_tokens: set[str] = set()
        for tokens in field_tokens.values():
            doc_tokens.update(tokens.keys())
        for token in doc_tokens:
            doc_freq[token] += 1
        exception_head, frame_head = _split_signature(entry.symptom_signature)
        docs.append(
            _EntryDoc(
                entry=entry,
                field_tokens=field_tokens,
                all_tokens=frozenset(doc_tokens),
                exception_head=exception_head.lower() if exception_head else None,
                frame_head=frame_head.lower() if frame_head else None,
            )
        )
    total_docs = max(len(docs), 1)
    idf = {
        token: math.log((1 + total_docs) / (1 + freq)) + 1.0
        for token, freq in doc_freq.items()
    }
    return _SearchIndex(docs=docs, idf=idf)


def search_logs_kb(query: str, limit: int = _DEFAULT_LIMIT) -> SearchLogsKBResult:
    return search_entries(load_runtime_entries(), query, limit=limit)


def search_entries(
    entries: SearchCorpus,
    query: str,
    limit: int = _DEFAULT_LIMIT,
) -> SearchLogsKBResult:
    raw_query = query.strip()
    if not raw_query:
        raise ValueError("query must be a non-empty string")
    if limit < 1:
        raise ValueError("limit must be an integer >= 1")

    normalized = normalize_query_text(raw_query)
    matches = [item.match for item in _search(entries, normalized, limit=limit)]
    return SearchLogsKBResult(
        query=raw_query,
        normalized_query=normalized,
        advice=query_advice(raw_query, normalized),
        matches=matches,
    )


def normalize_query_text(query_text: str) -> str:
    stripped = query_text.strip()
    if not stripped:
        return ""
    normalized = query_text_from_excerpt(stripped)
    return normalized or stripped


def query_text_from_excerpt(log_excerpt: str) -> str:
    lines = _excerpt_lines(log_excerpt)
    if not lines:
        return ""

    picked: list[str] = []
    found_salient = False
    for line in lines:
        normalized_line = _normalize_excerpt_line(line)
        if normalized_line in picked:
            continue
        if _is_salient_line(line):
            picked.append(normalized_line)
            found_salient = True
        if len(picked) >= _QUERY_LINE_LIMIT:
            break

    if not picked:
        picked.append(_normalize_excerpt_line(lines[0]))

    if len(picked) == 1 and not found_salient:
        for line in lines:
            normalized_line = _normalize_excerpt_line(line)
            if normalized_line and normalized_line not in picked:
                picked.append(normalized_line)
            if len(picked) >= _QUERY_LINE_LIMIT:
                break

    return _clip_query("\n".join(picked[:_QUERY_LINE_LIMIT]))


def query_advice(raw_query: str, normalized_query: str) -> list[str]:
    advice: list[str] = []
    text = normalized_query or raw_query
    if _is_broad_query(text):
        advice.append(
            "query looks broad; add the first stack frame or adjacent error lines to improve precision"
        )
    return advice


def _search(entries: SearchCorpus, query_text: str, limit: int) -> list[_RankedMatch]:
    query_tokens = _tokenize(query_text)
    if not query_tokens:
        return []

    scored: list[_RankedMatch] = []
    index = _search_index(entries)
    query_features = _build_query_features(query_text, query_tokens, index.idf)
    for doc in index.docs:
        score = _score_doc(doc, index.idf, query_tokens, query_features)
        if score <= 0:
            continue
        scored.append(_RankedMatch(match=_to_match(doc.entry), score=score))
    scored.sort(key=lambda item: (-item.score, item.match.id))
    return scored[:limit]


def _to_match(entry: RuntimeEntry) -> LogsKBMatch:
    return LogsKBMatch(
        id=entry.id,
        symptom_signature=entry.symptom_signature,
        symptom_summary=entry.symptom_summary,
        root_cause=entry.root_cause,
        suggested_action=entry.suggested_action,
        fix_version=entry.fix_version,
        fix_confidence=entry.fix_confidence,
        tags=list(entry.tags),
    )


def _score_doc(
    doc: _EntryDoc,
    idf: dict[str, float],
    query_tokens: Counter[str],
    query_features: _QueryFeatures,
) -> float:
    score = 0.0
    for field, weight in _FIELD_WEIGHTS.items():
        field_tokens = doc.field_tokens[field]
        field_score = 0.0
        for token, qfreq in query_tokens.items():
            tf = field_tokens.get(token)
            if not tf:
                continue
            field_score += (
                min(qfreq, tf)
                * idf.get(token, 1.0)
                * _token_match_multiplier(field, token, query_features)
            )
        score += weight * field_score

    score += _distinctive_token_coverage_boost(
        doc.all_tokens, idf, query_features.distinctive_tokens
    )

    if doc.exception_head and doc.exception_head in query_features.query_lower:
        score += 12.0 if query_features.has_stack_frame else 4.0
    if doc.frame_head and doc.frame_head in query_features.query_lower:
        score += 9.0

    signature = doc.entry.symptom_signature.lower()
    if signature and signature in query_features.query_lower:
        score += 20.0
    return score


def _build_query_features(
    query_text: str,
    query_tokens: Counter[str],
    idf: dict[str, float],
) -> _QueryFeatures:
    distinctive_tokens = tuple(
        token
        for token in query_tokens
        if _is_distinctive_query_token(token, idf)
    )
    return _QueryFeatures(
        query_lower=query_text.lower(),
        distinctive_tokens=distinctive_tokens,
        has_stack_frame=any(_looks_like_stack_frame(line) for line in query_text.splitlines()),
    )


def _distinctive_token_coverage_boost(
    doc_tokens: frozenset[str],
    idf: dict[str, float],
    distinctive_tokens: tuple[str, ...],
) -> float:
    return 2.0 * sum(idf.get(token, 1.0) for token in distinctive_tokens if token in doc_tokens)


def _token_match_multiplier(
    field: str,
    token: str,
    query_features: _QueryFeatures,
) -> float:
    if query_features.has_stack_frame:
        return 1.0
    if field != "symptom_signature":
        return 1.0
    if token in _GENERIC_EXCEPTION_TOKENS:
        return 0.2
    return 1.0


def _is_distinctive_query_token(token: str, idf: dict[str, float]) -> bool:
    if token in _DISTINCTIVE_TOKEN_STOPWORDS:
        return False
    if len(token) < 5:
        return False
    return idf.get(token, 0.0) >= 1.2


def _is_broad_query(query_text: str) -> bool:
    text = query_text.strip()
    if not text:
        return False
    if any(_looks_like_stack_frame(line) for line in text.splitlines()):
        return False

    match = _EXCEPTION_RE.search(text)
    if not match:
        return False

    tokens = _tokenize_for_advice(text)
    if not tokens:
        return False

    exception_tokens = _tokenize_for_advice(match.group(0))
    remaining = [
        token
        for token in tokens
        if token not in exception_tokens and token not in {"exception", "error"}
    ]
    if not remaining:
        return True
    return len(remaining) <= 2 and all(
        token in _VAGUE_QUERY_TOKENS for token in remaining
    )


def _excerpt_lines(log_excerpt: str) -> list[str]:
    split_text = _split_embedded_log_lines(log_excerpt)
    return [line.rstrip() for line in split_text.splitlines() if line.strip()]


def _excerpt_text_for_index(log_excerpt: str | None) -> str:
    if not log_excerpt:
        return ""
    normalized = query_text_from_excerpt(log_excerpt)
    return normalized or log_excerpt.strip()


def _clip_query(query: str) -> str:
    text = query.strip()
    if len(text) <= _QUERY_CHAR_LIMIT:
        return text
    clipped = text[:_QUERY_CHAR_LIMIT].rstrip()
    if "\n" in clipped:
        clipped = clipped.rsplit("\n", 1)[0]
    return clipped.rstrip()


def _is_salient_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if _looks_like_stack_frame(stripped):
        return True

    level, body = _extract_log_level_and_body(stripped)
    candidate = body or stripped
    if _looks_like_stack_frame(candidate):
        return True
    if level in _ALWAYS_SALIENT_LOG_LEVELS:
        return True
    if _looks_like_exception_head(candidate) or _looks_like_exception_head(stripped):
        return True

    lowered = candidate.lower()
    return any(snippet in lowered for snippet in _SALIENT_TEXT_SNIPPETS)


def _looks_like_exception_head(line: str) -> bool:
    lowered = line.lower()
    return (
        lowered.startswith("caused by:")
        or "exception in thread" in lowered
        or bool(_EXCEPTION_RE.search(line))
    )


def _looks_like_stack_frame(line: str) -> bool:
    stripped = line.lstrip()
    if not stripped.startswith("at "):
        return False

    candidate = stripped[3:]
    if not candidate:
        return False

    head_chars: list[str] = []
    for ch in candidate:
        if ch.isspace() or ch == "(":
            break
        head_chars.append(ch)
    if not head_chars:
        return False

    head = "".join(head_chars)
    if "." not in head:
        return False
    return all(ch.isalnum() or ch in _STACK_FRAME_HEAD_CHARS for ch in head)


def _split_signature(signature: str) -> tuple[str | None, str | None]:
    text = signature.strip()
    if not text:
        return None, None
    if " at " not in text:
        return text, None
    exc, frame = text.split(" at ", 1)
    return exc.strip(), frame.strip()


def _normalize_excerpt_line(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return ""
    if _looks_like_stack_frame(stripped):
        return stripped

    _level, body = _extract_log_level_and_body(stripped)
    return body or stripped


def _split_embedded_log_lines(text: str) -> str:
    return _EMBEDDED_LOG_START_RE.sub("\n", text)


def _extract_log_level_and_body(line: str) -> tuple[str | None, str]:
    stripped = line.strip()
    if not stripped:
        return None, ""

    for level in _LOG_LEVELS:
        if stripped.startswith(level):
            return level, _trim_log_body_prefix(stripped[len(level) :].lstrip()) or stripped

        marker = f" {level}"
        start = stripped.find(marker)
        while start >= 0:
            prefix = stripped[:start].rstrip()
            if _looks_like_log_prefix(prefix):
                body = stripped[start + len(marker) :].lstrip()
                return level, _trim_log_body_prefix(body) or stripped
            start = stripped.find(marker, start + 1)

    return None, stripped


def _looks_like_log_prefix(prefix: str) -> bool:
    if not prefix:
        return False
    if "|" in prefix:
        return True

    digit_count = sum(ch.isdigit() for ch in prefix)
    if digit_count < 2:
        return False
    return prefix.count(":") >= 2 or prefix.count("-") >= 2 or prefix.count("/") >= 2


def _trim_log_body_prefix(body: str) -> str:
    text = body.lstrip()
    if text.startswith("["):
        close = text.find("]")
        if close >= 0:
            text = text[close + 1 :].lstrip()
    if text.startswith(":"):
        text = text[1:].lstrip()
    if text.startswith("-"):
        text = text[1:].lstrip()
    return text.strip()


def _tokenize(text: str) -> Counter[str]:
    counter: Counter[str] = Counter()
    for raw in _scan_token_chunks(text, _TOKEN_CHARS):
        for token in _expand_token(raw):
            counter[token] += 1
    return counter


def _expand_token(raw: str) -> set[str]:
    tokens: set[str] = set()
    cleaned = raw.strip(_STRIP_TOKEN_CHARS)
    if not cleaned:
        return tokens

    lowered = cleaned.lower()
    if _keep_token(lowered):
        tokens.add(lowered)
        tokens.update(_token_aliases(lowered))

    for piece in _split_on_chars(cleaned, _TOKEN_SPLIT_CHARS):
        piece_lower = piece.lower()
        if _keep_token(piece_lower):
            tokens.add(piece_lower)
            tokens.update(_token_aliases(piece_lower))
        if any(ch.isalpha() for ch in piece):
            camel_parts = cast(list[str], _CAMEL_PART_RE.findall(piece))
            if len(camel_parts) > 1:
                for part in camel_parts:
                    part_lower = part.lower()
                    if _keep_token(part_lower):
                        tokens.add(part_lower)
                        tokens.update(_token_aliases(part_lower))
    return tokens


def _keep_token(token: str) -> bool:
    if len(token) < 2:
        return False
    if token.isdigit():
        return False
    return any(ch.isalpha() for ch in token)


def _token_aliases(token: str) -> tuple[str, ...]:
    return _TOKEN_ALIASES.get(token, ())


def _tokenize_for_advice(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in _scan_token_chunks(text, _ADVICE_TOKEN_CHARS):
        for part in _split_on_chars(raw, _ADVICE_TOKEN_CHARS):
            lowered = part.strip().lower()
            if lowered and any(ch.isalpha() for ch in lowered):
                tokens.append(lowered)
    return tokens


def _scan_token_chunks(text: str, extra_chars: str) -> list[str]:
    chunks: list[str] = []
    start = -1
    for index, ch in enumerate(text):
        if ch.isalnum() or ch in extra_chars:
            if start < 0:
                start = index
            continue
        if start >= 0:
            chunks.append(text[start:index])
            start = -1
    if start >= 0:
        chunks.append(text[start:])
    return chunks


def _split_on_chars(text: str, separators: str) -> list[str]:
    pieces: list[str] = []
    current: list[str] = []
    for ch in text:
        if ch in separators:
            if current:
                pieces.append("".join(current))
                current = []
            continue
        current.append(ch)
    if current:
        pieces.append("".join(current))
    return pieces
