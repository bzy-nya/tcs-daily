"""Canonical tag taxonomy for reports and frontend grouping."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CategoryDef:
    key: str
    name: str


CATEGORY_DEFS: tuple[CategoryDef, ...] = (
    CategoryDef("complexity-theory", "Complexity Theory"),
    CategoryDef("algorithms", "Algorithms"),
    CategoryDef("data-structures", "Data Structures"),
    CategoryDef("graph-theory", "Graph Theory"),
    CategoryDef("cryptography", "Cryptography"),
    CategoryDef("coding-theory", "Coding Theory"),
    CategoryDef("learning-theory", "Learning Theory"),
    CategoryDef("quantum-computing", "Quantum Computing"),
    CategoryDef("logic-and-formal-methods", "Logic & Formal Methods"),
    CategoryDef("automata-and-formal-languages", "Automata & Formal Languages"),
    CategoryDef("computational-geometry", "Computational Geometry"),
    CategoryDef("distributed-computing-theory", "Distributed Computing Theory"),
    CategoryDef("algorithmic-game-theory", "Algorithmic Game Theory"),
    CategoryDef("randomness-and-pseudorandomness", "Randomness & Pseudorandomness"),
    CategoryDef("combinatorics-in-tcs", "Combinatorics in TCS"),
    CategoryDef("property-testing", "Property Testing"),
    CategoryDef("computational-social-choice", "Computational Social Choice"),
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


def category_defs() -> dict[str, dict[str, str | int]]:
    return {
        category.key: {"name": category.name, "order": idx}
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
