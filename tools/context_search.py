"""Rank current, scope-checked evidence. Scores never grant authority to a row."""

from collections import Counter
from hashlib import sha256
from functools import lru_cache
import math
import re
import time

import context_embeddings as embeddings

OPTIONAL_SECONDS = 0.30
SEMANTIC_FLOOR = 0.29
MAX_SUPPLEMENTAL = 6
SOURCE_TAG = re.compile(r"\[S[1-9]\d*\]")
ROW_PREFIX = re.compile(r"^- (?:Fact|Rule|Example|Reported metric|Question):\s*")
NAVIGATION = re.compile(r"(?:private/)?(?:context|workspace)/[\w./-]+\.(?:md|json)\b|\bcompany(?:-wide)?\b", re.I)


def passage(row):
    return SOURCE_TAG.sub("", ROW_PREFIX.sub("", row["text"])).strip(" |")


def bm25(query, documents):
    counts = [Counter(document) for document in documents]
    frequencies = Counter(term for count in counts for term in count if term in query)
    lengths = [sum(count.values()) for count in counts]
    average = sum(lengths) / max(1, len(lengths)) or 1
    scores = []
    for count, length in zip(counts, lengths):
        score = 0.0
        for term in query.intersection(count):
            inverse = math.log1p((len(counts) - frequencies[term] + 0.5) / (frequencies[term] + 0.5))
            score += inverse * count[term] * 2.2 / (count[term] + 1.2 * (0.25 + 0.75 * length / average))
        scores.append(score)
    return scores


def vector(model, index, record, text):
    key = sha256((embeddings.VERSION + text).encode()).hexdigest()
    blob = index.vector(record, key)
    if isinstance(blob, bytes) and len(blob) == embeddings.PACK.size:
        return embeddings.PACK.unpack(blob)
    blob = embeddings.PACK.pack(*model.encode(text))
    index.save_vector(record, key, blob)
    return embeddings.PACK.unpack(blob)


def windows(text):
    terms = text.split()
    for start in range(0, max(len(terms), 1), 64):
        yield " ".join(terms[max(0, start - 8):start + 64])


TIME_QUESTION = re.compile(r"(?:^|[,:;.!?]\s*)(?:when|how (?:often|frequently|long)|"
                           r"how many (?:days|weeks|months))\b", re.I)
FUNCTION_WORDS = set("does did how who whose someone something any another with have that than them "
                     "their there when from what which one the for are this can our and into were should".split())


def alignment_terms(text):
    return list(dict.fromkeys(term for term in re.findall(r"[^\W_]+", text.lower())
                              if len(term) > 2 and term not in FUNCTION_WORDS))

TIME_VALUE = re.compile(r"\b(?:daily|weekly|monthly|quarterly|annually|nightly|every|each|"
                        r"(?:day|week|month|quarter|year|hour|minute)s?|"
                        r"(?:mon|tues|wednes|thurs|fri|satur|sun)day|\d{4}-\d{2}-\d{2})\b", re.I)


def rerank(model, query, bodies, semantic, deadline):
    """Use token alignment and answer form to resolve close sentence-level matches."""
    encode = lru_cache(maxsize=160)(model.encode)
    query_vectors = [encode(term) for term in alignment_terms(query)[:12]]
    temporal = TIME_QUESTION.search(query.strip())
    best = max(semantic, default=0)
    candidates = sorted(range(len(bodies)), key=lambda i: -semantic[i])[:8]
    for i in candidates:
        if semantic[i] < max(0.16, best - 0.16) or time.monotonic() >= deadline:
            break
        # Body terms carry evidence. A similar title by itself cannot answer the question.
        terms = [encode(term) for term in alignment_terms(bodies[i])[:32]]
        if not terms or not query_vectors:
            continue
        matches = [max(embeddings.similarity(q, t) for t in terms) for q in query_vectors]
        semantic[i] = 0.78 * semantic[i] + 0.22 * (sum(matches) / len(matches))
        if temporal:
            semantic[i] += 0.085 if TIME_VALUE.search(bodies[i]) else -0.055


def rank(prompt, scope, rows, labels, index, tokenize, identifiers):
    query = NAVIGATION.sub(" ", prompt)
    for key in ("product", "area", "initiative"):
        if scope.get(key):
            pattern = re.escape(scope[key]).replace(r"\-", r"[\s-]+")
            query = re.sub(r"(?<!\w)" + pattern + r"(?!\w)", " ", query, flags=re.I)
    terms = set(tokenize(query))
    bodies = [passage(row) for row in rows]
    body_terms = [tokenize(body) for body in bodies]
    documents = [tokens + tokenize(labels[row["record"], row["section"]])
                 for row, tokens in zip(rows, body_terms)]
    lexical = bm25(terms, documents)
    exact_ids = set(identifiers.findall(prompt.casefold()))
    exact = [bool(exact_ids.intersection(identifiers.findall(row["text"].casefold()))) for row in rows]
    semantic = [0.0] * len(rows)
    mode = "lexical"
    deadline = time.monotonic() + OPTIONAL_SECONDS
    if terms and rows:
        try:
            model = embeddings.encoder()
            query_vector = model.encode(query[:4000])
            mode = "hybrid"
            # Lexical finalists retain priority if a large cold scope exhausts its vector budget.
            for i in sorted(range(len(rows)), key=lambda i: -lexical[i]):
                for span in windows(bodies[i]):
                    if time.monotonic() >= deadline:
                        mode = "hybrid-time-limited"
                        break
                    context = labels[rows[i]["record"], rows[i]["section"]] + ". " + span
                    semantic[i] = max(semantic[i], embeddings.similarity(query_vector, vector(
                        model, index, rows[i]["record"], context)))
                if mode == "hybrid-time-limited":
                    break
            rerank(model, query, bodies, semantic, deadline)
        except (OSError, ValueError):
            mode = "lexical"

    # Weighted reciprocal rank fusion keeps raw BM25 and cosine scales independent.
    fused = [0.0] * len(rows)
    for scores, minimum in ((lexical, 0), (semantic, SEMANTIC_FLOOR)):
        ranks = {}
        for position, i in enumerate(sorted(range(len(rows)), key=lambda i: -scores[i]), 1):
            if scores[i] <= minimum:
                break
            ranks.setdefault(scores[i], position)
            fused[i] += 1 / (12 + ranks[scores[i]])
    best = max(semantic, default=0)
    selected = set()
    for i in sorted(range(len(rows)), key=lambda i: (not exact[i], -fused[i], -semantic[i], i)):
        shared = terms.intersection(body_terms[i])
        lexical_hit = bool(shared) and (mode != "hybrid" or len(shared) >= 2 or shared == terms
                                        or semantic[i] >= SEMANTIC_FLOOR)
        semantic_hit = semantic[i] >= max(SEMANTIC_FLOOR, min(0.45, best - 0.065))
        if exact[i] or (len(selected) < MAX_SUPPLEMENTAL and (lexical_hit or semantic_hit)):
            selected.add(i)
    return selected, [(exact[i], fused[i], semantic[i]) for i in range(len(rows))], mode
