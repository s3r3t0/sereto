from collections.abc import Iterable

from pydantic import validate_call

from sereto.models.base import SeretoBaseModel


class DocumentModel(SeretoBaseModel):
    """Model representing a supporting document associated with a target.

    Attributes:
        type: Category of the document (e.g. "api", "clickpath"), used for filtering.
        description: Human-readable description of the document.
        value: The document reference, typically a file name.
    """

    type: str
    description: str | None = None
    value: str


@validate_call
def dump_documents_to_toml(documents: Iterable[DocumentModel]) -> str:
    """Dump documents to a TOML string.

    Args:
        documents: An iterable of DocumentModel instances.

    Returns:
        A TOML formatted string representing the documents.
    """
    if len(doc_list := list(documents)) == 0:
        return "[]"

    lines: list[str] = []
    for doc in doc_list:
        desc_part = f', description="{doc.description}"' if doc.description is not None else ""
        lines.append(f'{{type="{doc.type}", value="{doc.value}"{desc_part}}},')
    return "[\n    " + "\n    ".join(lines) + "\n]"
