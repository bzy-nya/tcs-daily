"""Canonical tag taxonomy, grouping, and color palette."""

from __future__ import annotations

import colorsys
import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class CategoryDef:
    key: str
    name: str
    hue: int


CATEGORY_DEFS: tuple[CategoryDef, ...] = (
    CategoryDef("complexity-theory", "Complexity Theory", 228),
    CategoryDef("algorithms", "Algorithms", 18),
    CategoryDef("data-structures", "Data Structures", 166),
    CategoryDef("graph-theory", "Graph Theory", 142),
    CategoryDef("cryptography", "Cryptography", 282),
    CategoryDef("coding-theory", "Coding Theory", 334),
    CategoryDef("learning-theory", "Learning Theory", 58),
    CategoryDef("quantum-computing", "Quantum Computing", 252),
    CategoryDef("logic-and-formal-methods", "Logic & Formal Methods", 204),
    CategoryDef("automata-and-formal-languages", "Automata & Formal Languages", 34),
    CategoryDef("computational-geometry", "Computational Geometry", 188),
    CategoryDef("distributed-computing-theory", "Distributed Computing Theory", 126),
    CategoryDef("algorithmic-game-theory", "Algorithmic Game Theory", 6),
    CategoryDef("randomness-and-pseudorandomness", "Randomness & Pseudorandomness", 94),
    CategoryDef("combinatorics-in-tcs", "Combinatorics in TCS", 318),
    CategoryDef("property-testing", "Property Testing", 76),
    CategoryDef("computational-social-choice", "Computational Social Choice", 346),
)


CATEGORY_TAGS: dict[str, tuple[str, ...]] = {
    "complexity-theory": (
        "time-complexity",
        "space-complexity",
        "circuit-complexity",
        "communication-complexity",
        "proof-complexity",
        "parameterized-complexity",
        "fine-grained-complexity",
        "average-case-complexity",
        "interactive-proofs",
        "pcp-theory",
        "approximate-counting",
    ),
    "algorithms": (
        "exact-algorithms",
        "approximation-algorithms",
        "randomized-algorithms",
        "online-algorithms",
        "streaming-algorithms",
        "sublinear-algorithms",
        "distributed-algorithms",
        "parallel-algorithms",
        "dynamic-algorithms",
        "external-memory-algorithms",
        "enumeration-algorithms",
        "linear-algebraic-algorithms",
    ),
    "data-structures": (
        "static-data-structures",
        "dynamic-data-structures",
        "succinct-data-structures",
        "persistent-data-structures",
        "cache-oblivious-data-structures",
        "geometric-data-structures",
        "string-data-structures",
    ),
    "graph-theory": (
        "graph-algorithms",
        "spectral-graph-theory",
        "extremal-graph-theory",
        "random-graphs",
        "graph-coloring",
        "graph-minor-theory",
        "network-flows",
        "matching-theory",
        "graph-drawing",
    ),
    "cryptography": (
        "symmetric-cryptography",
        "public-key-cryptography",
        "cryptographic-protocols",
        "secure-multiparty-computation",
        "zero-knowledge-proofs",
        "homomorphic-encryption",
        "post-quantum-cryptography",
        "cryptographic-hash-functions",
        "lattice-problems",
    ),
    "coding-theory": (
        "error-correcting-codes",
        "list-decoding",
        "locally-decodable-codes",
        "network-coding",
        "algebraic-coding-theory",
    ),
    "learning-theory": (
        "pac-learning",
        "online-learning",
        "statistical-learning-theory",
        "boosting",
        "sample-complexity",
        "active-learning",
        "differential-privacy",
    ),
    "quantum-computing": (
        "quantum-algorithms",
        "quantum-complexity-theory",
        "quantum-information",
        "quantum-cryptography",
        "quantum-error-correction",
    ),
    "logic-and-formal-methods": (
        "proof-theory",
        "model-theory",
        "type-theory",
        "program-verification",
        "model-checking",
        "temporal-logic",
        "hoare-logic",
    ),
    "automata-and-formal-languages": (
        "finite-automata",
        "pushdown-automata",
        "turing-machines",
        "formal-language-theory",
        "tree-automata",
        "omega-automata",
    ),
    "computational-geometry": (
        "geometric-algorithms",
        "range-searching",
        "convex-hull",
        "voronoi-diagrams",
        "existential-theory-of-the-reals",
    ),
    "distributed-computing-theory": (
        "consensus",
        "fault-tolerance",
        "self-stabilization",
        "distributed-graph-algorithms",
        "asynchronous-computation",
    ),
    "algorithmic-game-theory": (
        "mechanism-design",
        "auction-theory",
        "price-of-anarchy",
        "fair-division",
        "market-design",
    ),
    "randomness-and-pseudorandomness": (
        "pseudorandom-generators",
        "extractors",
        "derandomization",
        "random-walks",
        "expanders",
    ),
    "combinatorics-in-tcs": (
        "extremal-combinatorics",
        "ramsey-theory",
        "probabilistic-method",
        "combinatorial-designs",
        "additive-combinatorics",
    ),
    "property-testing": (
        "property-testing",
        "distribution-testing",
        "graph-property-testing",
        "sublinear-time-algorithms",
    ),
    "computational-social-choice": (
        "voting-theory",
        "fairness",
        "preference-aggregation",
    ),
}


ALIASES: dict[str, str] = {
    "linear-algebra": "linear-algebraic-algorithms",
    "lattice": "lattice-problems",
}


SPECIAL_TAG_NAMES: dict[str, str] = {
    "average-case-complexity": "Average-Case Complexity",
    "existential-theory-of-the-reals": "Existential Theory of the Reals",
    "fine-grained-complexity": "Fine-Grained Complexity",
    "linear-algebraic-algorithms": "Linear Algebraic Algorithms",
    "omega-automata": "Omega Automata",
    "pac-learning": "PAC Learning",
    "pcp-theory": "PCP Theory",
    "post-quantum-cryptography": "Post-Quantum Cryptography",
    "public-key-cryptography": "Public-Key Cryptography",
    "sublinear-time-algorithms": "Sublinear-Time Algorithms",
    "zero-knowledge-proofs": "Zero-Knowledge Proofs",
}


def _display_name(tag: str) -> str:
    return SPECIAL_TAG_NAMES.get(tag, tag.replace("-", " ").title())


def _hex_from_hsl(hue: float, sat: float, light: float) -> str:
    r, g, b = colorsys.hls_to_rgb((hue % 360) / 360.0, light, sat)
    return f"#{int(r * 255):02X}{int(g * 255):02X}{int(b * 255):02X}"


def category_accent(category: str) -> str:
    info = next((item for item in CATEGORY_DEFS if item.key == category), None)
    if info is None:
        return "#5E7A8B"
    return _hex_from_hsl(info.hue, 0.58, 0.54)


def tag_color(tag: str, category: str | None = None) -> str:
    defs = tag_defs()
    resolved_category = category or defs.get(tag, {}).get("category", "uncategorized")
    base = next(
        (item for item in CATEGORY_DEFS if item.key == resolved_category),
        None,
    )
    if base is None:
        digest = int(hashlib.md5(tag.encode()).hexdigest()[:8], 16)
        return _hex_from_hsl(digest % 360, 0.22, 0.52)

    digest = int(hashlib.md5(tag.encode()).hexdigest()[:8], 16)
    hue_offset = ((digest % 2801) / 2800.0 - 0.5) * 28.0
    sat = 0.57 + ((digest >> 11) % 10) / 100.0
    light = 0.49 + ((digest >> 19) % 8) / 100.0
    return _hex_from_hsl(base.hue + hue_offset, sat, light)


def category_defs() -> dict[str, dict[str, str | int]]:
    return {
        category.key: {
            "name": category.name,
            "order": idx,
            "hue": category.hue,
            "accent": category_accent(category.key),
        }
        for idx, category in enumerate(CATEGORY_DEFS)
    }


def tag_defs() -> dict[str, dict[str, str]]:
    defs: dict[str, dict[str, str]] = {}
    for category, tags in CATEGORY_TAGS.items():
        for tag in tags:
            defs[tag] = {"name": _display_name(tag), "category": category}
    return defs


def canonical_tag(tag: str) -> str:
    clean = tag.strip()
    return ALIASES.get(clean, clean)


def normalize_tags(raw_tags: list[str]) -> tuple[list[str], list[str]]:
    known = tag_defs()
    normalized: list[str] = []
    unknown: list[str] = []
    seen: set[str] = set()
    for raw in raw_tags:
        tag = canonical_tag(raw)
        if tag in seen:
            continue
        seen.add(tag)
        if tag in known:
            normalized.append(tag)
        else:
            normalized.append(tag)
            unknown.append(tag)
    return normalized, unknown
