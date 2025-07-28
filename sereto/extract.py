from jinja2.nodes import Block, Node, Output, Template, TemplateData


def extract_block_from_jinja(content: str, name: str) -> tuple[str, int, int]:
    """
    Extracts the full content of a Jinja block by name, including the tags.

    Returns:
        The full block content, start index and end index.
    """
    start_tags = [f"{{% block {name} -%}}", f"{{% block {name} %}}"]
    end_tags = [f"{{%- endblock {name} %}}", f"{{% endblock {name} %}}"]

    start_idx = None
    for tag in start_tags:
        idx = content.find(tag)
        if idx != -1:
            start_idx = idx + len(tag)
            break

    if start_idx is None:
        return "", 0, 0

    end_idx = None
    for tag in end_tags:
        idx = content.find(tag, start_idx)
        if idx != -1:
            end_idx = idx
            break

    if end_idx is None:
        return "", 0, 0

    block = content[start_idx:end_idx]
    return block, start_idx, end_idx


def extract_text_from_jinja(ast: Template) -> dict[str, str]:
    """
    Extracts static text content from all blocks in a Jinja2 template.
    """
    blocks_text = {}

    for node in ast.body:
        if isinstance(node, Block):
            block_name = node.name
            block_text = extract_blocks(node.body)
            if block_text:
                blocks_text[block_name] = block_text
    return blocks_text


def extract_blocks(node_list: list[Node]) -> str:
    """
    Extracts static text from a list of nodes inside a block
    """
    result = []
    for node in node_list:
        if isinstance(node, Output):
            for subnode in node.nodes:
                if isinstance(subnode, TemplateData):
                    result.append(subnode.data)
    return " ".join(result).strip().replace("\n", "")
