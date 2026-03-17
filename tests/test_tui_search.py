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
    documents = [
        _doc("SQL Injection", keywords=["sqli"]),
        _doc("Generic Web Finding", description="This issue leads to SQL injection in a login form."),
    ]

    results = rank_documents(
        documents, parse_search_query("sql injection", FINDING_SEARCH_FIELDS), FINDING_SEARCH_FIELDS
    )

    assert [result.document.payload for result in results] == ["SQL Injection", "Generic Web Finding"]
    assert results[0].score > results[1].score


def test_explicit_field_clause_prefers_requested_field():
    documents = [
        _doc("Remote Code Execution", keywords=["rce"]),
        _doc("Generic Finding", impact="Remote code execution through unsafe deserialization."),
    ]

    results = rank_documents(documents, parse_search_query("impact:rce", FINDING_SEARCH_FIELDS), FINDING_SEARCH_FIELDS)

    assert [result.document.payload for result in results] == ["Generic Finding"]


def test_keyword_match_can_rescue_untagged_search():
    documents = [
        _doc("Weak TLS Configuration", keywords=["sweet32", "cbc"]),
        _doc("Generic Network Finding", description="The server accepts legacy CBC ciphers."),
    ]

    results = rank_documents(documents, parse_search_query("sweet32", FINDING_SEARCH_FIELDS), FINDING_SEARCH_FIELDS)

    assert results[0].document.payload == "Weak TLS Configuration"
