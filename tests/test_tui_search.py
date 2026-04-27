from sereto.tui.search import FINDING_SEARCH_FIELDS, SearchDocument, parse_search_query, rank_documents


def _doc(
    name: str,
    *,
    keywords: list[str] | None = None,
    description: str = "",
    impact: str = "",
    recommendation: str = "",
) -> SearchDocument[str]:
    fields: dict[str, list[str]] = {
        "name": [name],
        "keyword": keywords or [],
    }
    if description:
        fields["description"] = [description]
    if impact:
        fields["impact"] = [impact]
    if recommendation:
        fields["recommendation"] = [recommendation]
    return SearchDocument(payload=name, fields=fields)


def test_parse_search_query_splits_free_terms_and_field_clauses():
    parsed = parse_search_query('sql injection impact:"remote code execution"', FINDING_SEARCH_FIELDS)

    assert parsed.free_terms == ["sql", "injection"]
    assert parsed.field_terms == {"impact": ["remote code execution"]}


def test_parse_search_query_treats_unknown_operator_as_plain_text():
    parsed = parse_search_query("imp:test", FINDING_SEARCH_FIELDS)

    assert parsed.free_terms == ["imp:test"]
    assert parsed.field_terms == {}


def test_untagged_search_prioritizes_name_before_body_text():
    """Untagged search ranks name matches higher than description matches."""
    documents = [
        _doc("SQL Injection", keywords=["sqli"]),
        _doc("Another SQL Vuln", description="SQL injection in the login form."),
    ]

    results = rank_documents(
        documents, parse_search_query("sql injection", FINDING_SEARCH_FIELDS), FINDING_SEARCH_FIELDS
    )

    assert len(results) == 2
    assert [result.document.payload for result in results] == ["SQL Injection", "Another SQL Vuln"]
    assert results[0].score > results[1].score


def test_explicit_field_clause_prefers_requested_field():
    """Field clause search targets the specified field even when keywords match."""
    documents = [
        _doc("Remote Code Execution", keywords=["rce", "remote"]),
        _doc("Generic Finding", impact="Allows remote code execution via unsafe deserialization."),
    ]

    results = rank_documents(
        documents, parse_search_query("impact:remote", FINDING_SEARCH_FIELDS), FINDING_SEARCH_FIELDS
    )

    assert len(results) >= 1
    assert results[0].document.payload == "Generic Finding"
    assert "impact" in results[0].diagnostics.field_scores


def test_keyword_match_can_rescue_untagged_search():
    documents = [
        _doc("Weak TLS Configuration", keywords=["sweet32", "cbc"]),
        _doc("Generic Network Finding", description="The server accepts legacy CBC ciphers."),
    ]

    results = rank_documents(documents, parse_search_query("sweet32", FINDING_SEARCH_FIELDS), FINDING_SEARCH_FIELDS)

    assert results[0].document.payload == "Weak TLS Configuration"


def test_result_diagnostics_include_free_text_details():
    documents = [
        _doc("SQL Injection", keywords=["sqli"]),
    ]

    result = rank_documents(
        documents, parse_search_query("sql injection", FINDING_SEARCH_FIELDS), FINDING_SEARCH_FIELDS
    )[0]

    assert result.diagnostics.final_score == result.score
    assert result.diagnostics.passed_threshold is True
    assert result.diagnostics.free_text_score > 0
    assert result.diagnostics.clause_score == 0.0
    assert result.diagnostics.field_scores["name"] > 0


def test_result_diagnostics_include_clause_details():
    """Result diagnostics include clause-specific scoring details."""
    documents = [
        _doc("Generic Finding", impact="Unsafe deserialization allows remote code execution."),
    ]

    results = rank_documents(
        documents, parse_search_query("impact:remote", FINDING_SEARCH_FIELDS), FINDING_SEARCH_FIELDS
    )

    assert len(results) > 0
    result = results[0]

    assert result.diagnostics.final_score == result.score
    assert result.diagnostics.clause_score > 0
    assert result.diagnostics.field_scores["impact"] > 0
