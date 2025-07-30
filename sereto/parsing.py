import pyparsing as pp


def search_parser(keys: dict[str, str]) -> pp.ParserElement:
    """Builds and returns a search query parser for simple key-value syntax."""
    value = pp.Word(pp.alphanums + "-_.") | pp.QuotedString('"') | pp.QuotedString("'")
    key = pp.oneOf(list(keys.keys()) + list(keys.values()))

    complete = pp.Group(key + pp.Suppress(":") + value)
    partial = pp.Group(key + pp.Suppress(":"))
    free_value = pp.Group(value)

    return pp.ZeroOrMore(complete | partial | free_value)


def parse_query(query: str, keys: dict[str, str]) -> dict[str, list[str]]:
    """Parse a search query string into a structured dictionary."""
    parser = search_parser(keys)
    reverse_keys = {v: k for k, v in keys.items()}

    result: dict[str, list[str]] = {key: [] for key in keys}

    try:
        for token in parser.parseString(query):
            if len(token) == 2:
                key, value = token

                if isinstance(value, str) and not value.strip():
                    continue

                full_key = reverse_keys.get(key, key)
                result[full_key].append(value)
            else:
                value = token[0]

                if isinstance(value, str) and not value.strip():
                    continue

                first_key = next(iter(keys))
                result[first_key].append(value)

    except pp.ParseException:
        pass

    return result
