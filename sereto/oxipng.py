import shutil
import subprocess

from pydantic import DirectoryPath, validate_call

from sereto.exceptions import SeretoPathError


@validate_call
def run_oxipng(project_path: DirectoryPath) -> None:
    """Compresses PNG images in the 'pictures' directory using oxipng."""
    # Check presence of oxipng utility
    oxipng_path = shutil.which("oxipng")
    if oxipng_path is None:
        raise SeretoPathError("Program oxipng not found. Please install it first on the system.")

    # Run oxipng
    pictures_path = project_path / "pictures"
    subprocess.run(["oxipng", "-o", "4", "-r", "--strip", "safe", pictures_path], check=True)
