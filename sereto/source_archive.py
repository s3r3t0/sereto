import tarfile
from pathlib import Path
from tempfile import gettempdir

from pathspec.gitignore import GitIgnoreSpec
from pydantic import validate_call
from pypdf import PdfReader, PdfWriter

from sereto.cli.utils import Console
from sereto.crypto import encrypt_file
from sereto.exceptions import SeretoPathError, SeretoValueError
from sereto.models.report import Report
from sereto.models.settings import Settings
from sereto.models.version import ReportVersion
from sereto.utils import assert_file_size_within_range


@validate_call
def _is_ignored(relative_path: str, patterns: list[str]) -> bool:
    """Check if a file path matches any of the ignore patterns.

    Args:
        relative_path: The file path to check.
        patterns: List of ignore patterns.

    Returns:
        True if the file is ignored, False otherwise.
    """
    spec = GitIgnoreSpec.from_lines(patterns)
    return spec.match_file(relative_path)


@validate_call
def create_source_archive(settings: Settings) -> None:
    """Create a source archive for the report.

    This function creates a source archive for the report by copying all the files not matching any
    ignore pattern in the report directory to a compressed archive file.

    Args:
        settings: Global settings.
    """
    report_path = Report.get_path(dir_subtree=settings.reports_path)
    archive_path = report_path / "source.tgz"

    # Read the ignore patterns from the '.seretoignore' file
    if (seretoignore_path := report_path / ".seretoignore").is_file():
        assert_file_size_within_range(file=seretoignore_path, max_bytes=10_485_760, interactive=True)

        with seretoignore_path.open("r") as seretoignore:
            ignore_lines = seretoignore.readlines()
    else:
        Console().log(f"no '.seretoignore' file found: '{seretoignore_path}'")
        ignore_lines = []

    Console().log(f"creating source archive: '{archive_path}'")

    # Create the source archive
    with tarfile.open(archive_path, "w:gz") as tar:
        for item in report_path.rglob("*"):
            relative_path = item.relative_to(report_path)

            if not item.is_file() or item.is_symlink():
                Console().log(f"- skipping directory or symlink: '{relative_path}'")
                continue

            if _is_ignored(str(relative_path), ignore_lines):
                Console().log(f"- skipping item: '{relative_path}'")
                continue

            Console().log(f"+ adding item: '{relative_path}'")
            tar.add(item, arcname=str(item.relative_to(report_path.parent)))

    encrypt_file(archive_path)


@validate_call
def delete_source_archive(settings: Settings) -> None:
    """Delete the source archive.

    Args:
        settings: Global settings.
    """
    report_path = Report.get_path(dir_subtree=settings.reports_path)

    for archive_path in [report_path / "source.tgz", report_path / "source.sereto"]:
        if archive_path.is_file():
            archive_path.unlink()
            Console().log(f"deleted source archive: '{archive_path}'")


@validate_call
def embed_source_archive(settings: Settings, version: ReportVersion) -> None:
    """Embed the source archive in the report PDF.

    Args:
        settings: Global settings.
        version: The version of the report.
    """
    report_path = Report.get_path(dir_subtree=settings.reports_path)
    encrypted_archive_path = report_path / "source.sereto"
    archive_path = encrypted_archive_path if encrypted_archive_path.is_file() else report_path / "source.tgz"
    report_pdf_path = report_path / f"report{version.path_suffix}.pdf"

    reader = PdfReader(report_pdf_path, strict=True)
    writer = PdfWriter()

    # Copy all pages from the reader to the writer
    for page in reader.pages:
        writer.add_page(page)

    # Embed the source archive
    with archive_path.open("rb") as f:
        writer.add_attachment(filename=archive_path.name, data=f.read())

    # Write the output PDF
    with report_pdf_path.open("wb") as output_pdf:
        writer.write(output_pdf)


@validate_call
def extract_attachment_from(pdf: Path, name: str) -> Path:
    """Extracts an attachment from a given PDF file and writes it to a temporary file.

    Args:
        pdf: The path to the PDF file from which to extract the attachment.
        name: The name of the attachment to extract.

    Returns:
        The path to the temporary file containing the extracted attachment.

    Raises:
        SeretoValueError: If no or multiple attachments with the same name are found in the PDF.
    """
    if not pdf.is_file():
        raise SeretoPathError(f"file not found: '{pdf}'")

    # Read the PDF file
    reader = PdfReader(pdf, strict=True)

    # Check if the attachment is present
    if name not in reader.attachments:
        Console().log(f"no '{name}' attachment found in '{pdf}'")
        Console().log(f"[blue]Manually inspect the file to make sure the attachment '{name}' is present")
        raise SeretoValueError(f"no '{name}' attachment found in '{pdf}'")

    # PDF attachment names are not unique; check if there is only one attachment with the expected name
    if len(reader.attachments[name]) != 1:
        Console().log(f"[yellow]only single '{name}' attachment should be present")
        Console().log("[blue]Manually extract the correct file and use `sereto decrypt` command instead")
        raise SeretoValueError(f"multiple '{name}' attachments found")

    # Extract the attachment's content
    content: bytes = reader.attachments[name][0]

    # Write the content to a temporary file
    output_file = Path(gettempdir()) / name
    output_file.write_bytes(content)

    return output_file
