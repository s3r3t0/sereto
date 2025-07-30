import re

from jinja2.nodes import Block, Node, Output, Template, TemplateData


def extract_block_from_jinja(content: str, name: str) -> tuple[str, int, int]:
    """Extracts the full content of a Jinja block by name, including the tags.

    Returns:
        The full block content, start index and end index.
    """
    pattern = re.compile(
        r"""
        \{%-?\s*block\s+(\w+)\s*-?%\}
        (.*?)                            # content
        \{%-?\s*endblock\s*(\w+)?\s*-?%\}
    """,
        re.DOTALL | re.VERBOSE,
    )

    match = pattern.search(content)
    if match and match.group(1) == name:
        return match.group(2), match.start(2), match.end(2)

    return "", 0, 0


def extract_text_from_jinja(ast: Template) -> dict[str, str]:
    """Extracts static text content from all blocks in a Jinja2 template."""
    blocks_text = {}

    for node in ast.body:
        if isinstance(node, Block):
            block_name = node.name
            block_text = extract_blocks(node.body)
            if block_text:
                blocks_text[block_name] = block_text
    return blocks_text


def extract_blocks(node_list: list[Node]) -> str:
    """Extracts static text from a list of nodes inside a block."""
    result = []
    for node in node_list:
        if isinstance(node, Output):
            for subnode in node.nodes:
                if isinstance(subnode, TemplateData):
                    result.append(subnode.data)
    return " ".join(result).strip().replace("\n", "")
