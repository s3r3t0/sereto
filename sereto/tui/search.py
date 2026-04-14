from dataclasses import dataclass, field

from rapidfuzz import fuzz
from rich.text import Text
from textual.fuzzy import Matcher

from sereto.logging import LogLevel, get_log_config

_FREE_TEXT_REASON_WEIGHT = 1.0
_CLAUSE_REASON_WEIGHT = 1.35
_MATCH_THRESHOLD = 70.0
_TERM_MATCH_THRESHOLD = 50.0


def is_search_debug_visible() -> bool:
    """Return whether inline search diagnostics should be shown in the TUI."""

    return get_log_config().level in {LogLevel.DEBUG, LogLevel.TRACE}


@dataclass(frozen=True)
class SearchField:
    """Description of one searchable field in the finding index.

    Attributes:
        name: Canonical field name used internally and in the query syntax.
        label: Human-readable label used in the UI and explanations.
        aliases: Alternative operator names accepted in the query, such as
            short forms like `n` for `name`.
        default_weight: Relative importance of this field for free-text terms
            that do not explicitly target a field.

            Free-text search evaluates the term against every field and then
            multiplies the field score by `default_weight`. A larger value
            makes the field more likely to win for that term. These values are
            not probabilities and do not need to add up to `1`.
        clause_weight: Relative importance of this field when the user writes
            an explicit field clause such as `impact:rce`.

            Clause scores are combined using a weighted average, so this value
            only needs to express importance relative to the other fields. It
            also does not need to add up to `1` with the other weights.
        previewable: Whether matches in this field should also be highlighted
            in the finding preview screen.
    """

    name: str
    label: str
    aliases: tuple[str, ...]
    default_weight: float = 0.0
    clause_weight: float = 1.0
    previewable: bool = False

    def all_names(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)


@dataclass(frozen=True)
class ParsedSearchQuery:
    """Structured representation of the raw search bar input."""

    raw: str
    free_terms: list[str] = field(default_factory=list)
    field_terms: dict[str, list[str]] = field(default_factory=dict)

    @property
    def has_terms(self) -> bool:
        return bool(self.free_terms or any(self.field_terms.values()))


@dataclass(frozen=True)
class SearchDocument[T]:
    """Searchable representation of one indexed finding template."""

    payload: T
    fields: dict[str, list[str]]


@dataclass(frozen=True)
class SearchReason:
    """Explanation of why a document matched a query."""

    field_name: str
    label: str
    score: float


@dataclass(frozen=True)
class SearchResult[T]:
    """Ranked search result together with its scoring metadata."""

    document: SearchDocument[T]
    score: float
    reasons: list[SearchReason]
    diagnostics: "SearchDiagnostics"


@dataclass(frozen=True)
class SearchDiagnostics:
    """Structured scoring details for one ranked result.

    Attributes:
        free_text_score: Aggregate contribution from untagged free-text terms.
        clause_score: Aggregate contribution from explicit field clauses.
        phrase_bonus: Extra score added when the full free-text phrase appears
            in a high-value field such as name or keyword.
        final_score: Final score after combining weighted contributions and
            bonuses.
        passed_threshold: Whether the final score passed the display cutoff.
        field_scores: Weighted field contributions keyed by field name.
    """

    free_text_score: float = 0.0
    clause_score: float = 0.0
    phrase_bonus: float = 0.0
    final_score: float = 0.0
    passed_threshold: bool = False
    field_scores: dict[str, float] = field(default_factory=dict)


class FuzzyMatcher:
    def __init__(self, query: list[str]) -> None:
        self.query = [q.lower() for q in query if q.strip()]

    def highlight(self, text: list[str]) -> Text:
        """Highlight fuzzy matches in the given text."""
        combined = "; ".join(text)
        combined_lower = combined.lower()
        result_text = Text(combined)

        for q in self.query:
            if q in combined_lower:
                start = 0
                while True:
                    idx = combined_lower.find(q, start)
                    if idx == -1:
                        break
                    end = idx + len(q)
                    result_text.stylize("bold yellow", idx, end)
                    start = end
                continue

            for span in Matcher(q).highlight(combined).spans:
                span_text = combined[span.start : span.end]
                if len(span_text) <= len(q) + 2:
                    result_text.stylize("bold yellow", span.start, span.end)

        return result_text


class SearchFieldRegistry:
    """Registry of supported search fields and their query operators."""

    def __init__(self, fields: list[SearchField]) -> None:
        self.fields = fields
        self.by_name = {field.name: field for field in fields}

    def resolve(self, value: str, allow_prefix: bool = False) -> SearchField | None:
        """Resolve a query operator to a registered search field."""
        normalized = _normalize(value)
        if not normalized:
            return None

        for search_field in self.fields:
            if normalized in (_normalize(alias) for alias in search_field.all_names()):
                return search_field

        if not allow_prefix:
            return None

        matches = [search_field for search_field in self.fields if self._matches_prefix(search_field, normalized)]
        return matches[0] if len(matches) == 1 else None

    def previewable_fields(self) -> list[SearchField]:
        return [search_field for search_field in self.fields if search_field.previewable]

    @staticmethod
    def _matches_prefix(search_field: SearchField, prefix: str) -> bool:
        return any(_normalize(value).startswith(prefix) for value in search_field.all_names() + (search_field.label,))


FINDING_SEARCH_FIELDS = SearchFieldRegistry(
    [
        SearchField(name="name", label="Name", aliases=("n",), default_weight=1.0, clause_weight=1.2),
        SearchField(name="keyword", label="Keyword", aliases=("k", "keywords"), default_weight=0.8),
        SearchField(
            name="description",
            label="Description",
            aliases=("d", "desc"),
            default_weight=0.32,
            clause_weight=0.72,
            previewable=True,
        ),
        SearchField(
            name="likelihood",
            label="Likelihood",
            aliases=("l",),
            default_weight=0.28,
            clause_weight=0.68,
            previewable=True,
        ),
        SearchField(
            name="impact",
            label="Impact",
            aliases=("i",),
            default_weight=0.28,
            clause_weight=0.68,
            previewable=True,
        ),
        SearchField(
            name="recommendation",
            label="Recommendation",
            aliases=("r", "rec"),
            default_weight=0.32,
            clause_weight=0.72,
            previewable=True,
        ),
    ]
)


def parse_search_query(query: str, fields: SearchFieldRegistry) -> ParsedSearchQuery:
    """Parse the raw search string into free-text terms and field clauses.

    Free-text terms are used for the default search mode, which primarily
    targets finding names and keywords. Tokens in the form `field:value` are
    parsed as explicit field clauses when `field` matches a registered
    field name or alias.
    """
    tokens = _split_query(query)
    free_terms: list[str] = []
    field_terms: dict[str, list[str]] = {search_field.name: [] for search_field in fields.fields}

    for token in tokens:
        if ":" not in token:
            if token.strip():
                free_terms.append(token)
            continue

        raw_field, raw_value = token.split(":", 1)
        resolved = fields.resolve(raw_field)
        if resolved is None:
            free_terms.append(token)
            continue

        value = raw_value.strip()
        if not value:
            continue

        field_terms[resolved.name].append(value)

    return ParsedSearchQuery(
        raw=query,
        free_terms=free_terms,
        field_terms={key: values for key, values in field_terms.items() if values},
    )


def build_matchers(query: ParsedSearchQuery, fields: SearchFieldRegistry) -> dict[str, FuzzyMatcher]:
    """Create field-specific matchers for highlighting query terms."""
    matchers: dict[str, FuzzyMatcher] = {}

    for search_field in fields.fields:
        values = [*query.field_terms.get(search_field.name, [])]
        values.extend(query.free_terms)
        if values:
            matchers[search_field.name] = FuzzyMatcher(values)

    return matchers


def rank_documents[T](
    documents: list[SearchDocument[T]],
    query: ParsedSearchQuery,
    fields: SearchFieldRegistry,
) -> list[SearchResult[T]]:
    """Rank documents by combining free-text and field-specific matches.

    The ranking pipeline has two main inputs:

    - free-text terms, weighted using `SearchField.default_weight`
    - explicit field clauses, weighted using `SearchField.clause_weight`

    The returned score is a relative ranking value in the `0` to `100`
    range. The weighting values are tuning multipliers and are not expected to
    form a normalized distribution.
    """
    if not query.has_terms:
        return []

    results: list[SearchResult[T]] = []
    for document in documents:
        result = _rank_document(document, query, fields)
        if result is not None:
            results.append(result)

    return sorted(results, key=lambda result: result.score, reverse=True)


def summarize_query(query: ParsedSearchQuery, fields: SearchFieldRegistry) -> Text:
    """Render the parsed query back into a compact user-facing summary."""
    if not query.has_terms:
        return Text("Search name and keywords by default.", style="dim")

    parts: list[Text] = []
    if query.free_terms:
        parts.append(Text("Text: ", style="bold cyan"))
        parts.append(Text(", ".join(query.free_terms), style="white"))

    for field_name, values in query.field_terms.items():
        field = fields.by_name[field_name]
        if parts:
            parts.append(Text("  |  ", style="dim"))
        parts.append(Text(f"{field.label}: ", style="bold green"))
        parts.append(Text(", ".join(values), style="white"))

    return Text.assemble(*parts)


def supported_operator_text(fields: SearchFieldRegistry) -> Text:
    """Render the static help text listing the supported field operators."""
    field_list = ", ".join(f"{field.name}:" for field in fields.fields)
    return Text(f"Operators: {field_list}", style="dim")


def should_display_result(score: float) -> bool:
    """Return whether a ranked result is strong enough to display."""
    return score >= _MATCH_THRESHOLD


def _rank_document[T](
    document: SearchDocument[T],
    query: ParsedSearchQuery,
    fields: SearchFieldRegistry,
) -> SearchResult[T] | None:
    """Compute the final score for one document.

    Free-text and explicit field clauses are scored separately and then
    combined with a weighted average. Free-text weights come from
    `default_weight` indirectly through `_rank_free_terms()`, while
    explicit clauses use `clause_weight` directly here.
    """
    weighted_scores: list[tuple[float, float]] = []
    reasons: dict[str, SearchReason] = {}
    free_text_score = 0.0
    clause_score = 0.0
    field_scores: dict[str, float] = {}

    if query.free_terms:
        free_score, free_reasons, free_field_scores = _rank_free_terms(document, query.free_terms, fields)
        if free_score > 0:
            weighted_scores.append((free_score, _FREE_TEXT_REASON_WEIGHT))
            free_text_score = free_score
            field_scores.update(free_field_scores)
            for reason in free_reasons:
                _remember_reason(reasons, reason)

    for field_name, values in query.field_terms.items():
        search_field = fields.by_name[field_name]
        field_score = _score_terms(values, document.fields.get(search_field.name, []))
        if field_score <= 0:
            continue
        weighted_clause_score = field_score * search_field.clause_weight * _CLAUSE_REASON_WEIGHT
        weighted_scores.append((field_score, search_field.clause_weight * _CLAUSE_REASON_WEIGHT))
        clause_score += weighted_clause_score
        field_scores[search_field.name] = weighted_clause_score
        _remember_reason(reasons, SearchReason(search_field.name, search_field.label, field_score))

    if not weighted_scores:
        return None

    total_weight = sum(weight for _, weight in weighted_scores)
    score = sum(value * weight for value, weight in weighted_scores) / total_weight
    phrase_bonus = _phrase_bonus(document, query)
    score = min(score + phrase_bonus, 100.0)
    passed_threshold = should_display_result(score)
    diagnostics = SearchDiagnostics(
        free_text_score=round(free_text_score, 2),
        clause_score=round(clause_score, 2),
        phrase_bonus=round(phrase_bonus, 2),
        final_score=round(score, 2),
        passed_threshold=passed_threshold,
        field_scores={field_name: round(value, 2) for field_name, value in field_scores.items()},
    )
    if not passed_threshold:
        return None

    sorted_reasons = sorted(reasons.values(), key=lambda reason: reason.score, reverse=True)[:3]
    return SearchResult(document=document, score=round(score, 2), reasons=sorted_reasons, diagnostics=diagnostics)


def _rank_free_terms[T](
    document: SearchDocument[T],
    terms: list[str],
    fields: SearchFieldRegistry,
) -> tuple[float, list[SearchReason], dict[str, float]]:
    """Score free-text terms across all fields using `default_weight`.

    Each free-text term is evaluated against every indexed field. The raw field
    score is multiplied by `SearchField.default_weight`, and the best weighted
    field wins for that term. This is what makes untagged search prefer finding
    names and keywords over longer body sections.
    """

    per_term_scores: list[float] = []
    reason_scores: dict[str, SearchReason] = {}
    field_scores: dict[str, float] = {}
    matched_terms = 0

    for term in terms:
        best_score = 0.0
        best_field: SearchField | None = None
        for search_field in fields.fields:
            if search_field.default_weight <= 0:
                continue
            score = _score_terms([term], document.fields.get(search_field.name, []))
            weighted_score = score * search_field.default_weight
            if weighted_score > best_score:
                best_score = weighted_score
                best_field = search_field

        per_term_scores.append(best_score)
        if best_score >= _TERM_MATCH_THRESHOLD:
            matched_terms += 1
            if best_field is not None:
                field_scores[best_field.name] = max(field_scores.get(best_field.name, 0.0), round(best_score, 2))
                _remember_reason(
                    reason_scores,
                    SearchReason(best_field.name, best_field.label, round(best_score, 2)),
                )

    if not per_term_scores:
        return 0.0, [], {}

    score = sum(per_term_scores) / len(per_term_scores)
    if matched_terms:
        score += 8 * (matched_terms / len(per_term_scores))

    return min(score, 100.0), list(reason_scores.values()), field_scores


def _score_terms(terms: list[str], values: list[str]) -> float:
    """Aggregate fuzzy scores for one or more terms against one field."""
    cleaned_values = [value for value in values if value.strip()]
    if not terms or not cleaned_values:
        return 0.0

    term_scores = [_score_single_term(term, cleaned_values) for term in terms]
    matched = sum(score >= _TERM_MATCH_THRESHOLD for score in term_scores)
    score = sum(term_scores) / len(term_scores)
    if matched:
        score += 5 * (matched / len(term_scores))
    return min(score, 100.0)


def _score_single_term(term: str, values: list[str]) -> float:
    """Return the best fuzzy score for a single term within one field."""
    normalized_term = _normalize(term)
    if not normalized_term:
        return 0.0

    best = 0.0
    for value in values:
        normalized_value = _normalize(value)
        if not normalized_value:
            continue

        score = fuzz.WRatio(normalized_term, normalized_value)

        starts = normalized_value.startswith(normalized_term)
        token_prefix = any(word.startswith(normalized_term) for word in normalized_value.split())
        word_contains = f" {normalized_term} " in f" {normalized_value} "

        if normalized_value == normalized_term:
            score = max(score, 100.0)
        elif starts:
            score += 10
        elif token_prefix:
            score += 5
        elif word_contains:
            score += 4

        best = max(best, min(score, 100.0))

    return best


def _phrase_bonus[T](document: SearchDocument[T], query: ParsedSearchQuery) -> float:
    """Apply a bonus when the full free-text phrase appears in name or keywords."""
    phrase = _normalize(" ".join(query.free_terms))
    if not phrase:
        return 0.0

    bonus = 0.0
    for field_name in ("name", "keyword"):
        haystack = " ".join(document.fields.get(field_name, []))
        normalized_haystack = _normalize(haystack)
        if not normalized_haystack:
            continue
        if phrase == normalized_haystack:
            bonus = max(bonus, 9.0)
        elif phrase in normalized_haystack:
            bonus = max(bonus, 5.0)

    return bonus


def _remember_reason(reasons: dict[str, SearchReason], reason: SearchReason) -> None:
    """Store the strongest explanation for a field match."""
    current = reasons.get(reason.field_name)
    if current is None or reason.score > current.score:
        reasons[reason.field_name] = reason


def _split_query(query: str) -> list[str]:
    """Split a query into whitespace-separated tokens while preserving quotes."""
    tokens: list[str] = []
    current: list[str] = []
    quote: str | None = None

    for char in query:
        if quote is not None:
            if char == quote:
                quote = None
            else:
                current.append(char)
            continue

        if char in {'"', "'"}:
            quote = char
            continue

        if char.isspace():
            if current:
                tokens.append("".join(current))
                current = []
            continue

        current.append(char)

    if current:
        tokens.append("".join(current))

    return tokens


def _normalize(value: str) -> str:
    """Normalize text for fuzzy comparison and operator resolution."""
    return " ".join(value.lower().split())
