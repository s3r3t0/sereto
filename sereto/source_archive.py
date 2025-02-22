import tarfile
from os.path import commonpath
from pathlib import Path
from tempfile import NamedTemporaryFile

from pathspec.gitignore import GitIgnoreSpec
from pydantic import DirectoryPath, FilePath, TypeAdapter, ValidationError, validate_call
from pypdf import PdfReader, PdfWriter

from sereto.cli.utils import Console
from sereto.config import Config
from sereto.crypto import encrypt_file
from sereto.exceptions import SeretoEncryptionError, SeretoPathError, SeretoValueError
from sereto.types import TypeProjectId
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
def create_source_archive(project_path: DirectoryPath, config: Config) -> Path:
    """Create a source archive for the project.

    This function creates a source archive for the project by copying all the files not matching any ignore pattern in
    the project directory to a compressed archive file. The archive is encrypted if the password is set in the system's
    keyring.

    Args:
        project_path: The path to the project directory.
        config: The configuration object..

    Returns:
        The path to the created source archive.
    """
    # Read the ignore patterns from the '.seretoignore' file
    if (seretoignore_path := project_path / ".seretoignore").is_file():
        assert_file_size_within_range(file=seretoignore_path, max_bytes=10_485_760, interactive=True)

        with seretoignore_path.open("r") as seretoignore:
            ignore_lines = seretoignore.readlines()
    else:
        Console().log(f"File '{seretoignore_path}' does not exist'")
        ignore_lines = []

    # Create a temporary file to store the source archive
    with NamedTemporaryFile(suffix=".tgz", delete=False) as tmp:
        archive_path = Path(tmp.name)

        Console().log(f"Creating source archive: '{archive_path}'")

        # Determine the original project ID (store the project always with the original ID)
        original_id = config.first_config.id

        # Create the source archive
        with tarfile.open(archive_path, "w:gz") as tar:
            for item in project_path.rglob("*"):
                relative_path = item.relative_to(project_path)

                if not item.is_file() or item.is_symlink():
                    Console().log(f"[yellow]-[/yellow] Skipping directory or symlink: '{relative_path}'")
                    continue

                if _is_ignored(str(relative_path), ignore_lines):
                    Console().log(f"[yellow]-[/yellow] Skipping item: '{relative_path}'")
                    continue

                Console().log(f"[green]+[/green] Adding item: '{relative_path}'")
                tar.add(item, arcname=str(Path(original_id) / item.relative_to(project_path)))

    try:
        return encrypt_file(archive_path)
    except SeretoEncryptionError:
        return archive_path


@validate_call
def embed_attachment_to_pdf(
    pdf: FilePath, attachment: FilePath, name: str | None = None, keep_original: bool = True
) -> None:
    """Embed the attachment to the PDF.

    Args:
        pdf: The path to the PDF file where the attachment will be embedded.
        attachment: The path to the attahcment.
        name: The name of the attachment in the PDF. If None, the attachment's name is used. Defaults to None.
        keep_original: If True, the original source archive is kept. Defaults to True.
    """
    # Initialize PDF reader and writer
    reader = PdfReader(pdf, strict=True)
    writer = PdfWriter()

    # Copy content from the reader to the writer
    writer.append(reader)

    # Embed the source archive
    attachment_name = name if name is not None else attachment.name
    writer.add_attachment(filename=attachment_name, data=attachment.read_bytes())

    # Write the output PDF
    with pdf.open("wb") as output_pdf:
        writer.write(output_pdf)
        Console().log(f"[green]+[/green] Embedded attachment '{attachment.name}' into '{pdf}'")

    # Delete the source archive if `keep_original=False`
    if not keep_original:
        attachment.unlink()
        Console().log(f"[red]-[/red] Deleted original file: '{attachment}'")


@validate_call
def retrieve_source_archive(pdf: FilePath, name: str) -> Path:
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
        Console().log(f"No '{name}' attachment found in '{pdf}'")
        Console().log(f"[blue]Manually inspect the file to make sure the attachment '{name}' is present")
        raise SeretoValueError(f"no '{name}' attachment found in '{pdf}'")

    # PDF attachment names are not unique; check if there is only one attachment with the expected name
    if len(reader.attachments[name]) != 1:
        Console().log(f"[yellow]Only single '{name}' attachment should be present")
        Console().log("[blue]Manually extract the correct file and use `sereto decrypt` command instead")
        raise SeretoValueError(f"multiple '{name}' attachments found")

    # Extract the attachment's content
    content: bytes = reader.attachments[name][0]

    # Write the content to a temporary file
    with NamedTemporaryFile(suffix=Path(name).suffix if "." in name else None, delete=False) as tmp:
        output_file = Path(tmp.name)
        output_file.write_bytes(content)

    Console().log(f"[green]+[/green] Extracted attachment '{name}' from '{pdf}' to '{output_file}'")

    return output_file


@validate_call
def extract_source_archive(file: FilePath, output_dir: DirectoryPath, keep_original: bool = True) -> None:
    """Extracts the project sources from a given tarball file.

    Expects the tarball file to be Gzip-compressed.

    Args:
        file: The path to the .tgz file.
        output_dir: The directory where the sources will be extracted.
        keep_original: If True, the original tarball file is kept. Defaults to True.
    """
    Console().log("Extracting archive ...")

    with tarfile.open(file, "r:gz") as tar:
        # Check for empty source archive
        if len(tar.getmembers()) == 0:
            Console().log(f"[yellow]![/yellow] Empty source archive: '{file}'")
            return

        # Get the common directory in the tar archive
        common_dir = Path(commonpath(tar.getnames()))

        # There should always be a top level directory with the project ID
        if len(common_dir.parts) == 0:
            raise SeretoValueError("corrupted source archive (multiple top-level directories found)") from None

        # Validate project ID
        try:
            ta_id: TypeAdapter[TypeProjectId] = TypeAdapter(TypeProjectId)  # hack for mypy
            project_id = ta_id.validate_python(common_dir.parts[0])
        except ValidationError as e:
            raise SeretoValueError("corrupted source archive (invalid project ID)") from e

        # Check that this is a valid sereto project
        try:
            tar.getmember(f"{project_id}/.sereto")
            tar.getmember(f"{project_id}/config.json")
        except KeyError:
            raise SeretoValueError("corrupted source archive (missing core project files)") from None

        Console().log(f"[blue]i[/blue] Detected project with ID: {project_id}")

        # Make sure the project directory does not already exist
        if (output_dir / project_id).exists():
            raise SeretoPathError(f"project directory already exists: '{output_dir / project_id}'")

        # Extract the source archive
        tar.extractall(path=output_dir, filter="data")
        Console().log(f"[green]+[/green] Extracted sources from '{file}' to '{output_dir / project_id}'")

    # Delete the original tarball
    if not keep_original:
        file.unlink()
        Console().log(f"[red]-[/red] Deleted tarball: '{file}'")
