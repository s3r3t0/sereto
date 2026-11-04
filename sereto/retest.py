import shutil

from pydantic import validate_call

from sereto.exceptions import SeretoPathError
from sereto.project import Project


@validate_call
def add_retest(project: Project) -> None:
    last_version = project.config.last_version
    retest_version = last_version.next_major_version()

    old_suffix = last_version.path_suffix
    new_suffix = retest_version.path_suffix

    last_model = project.config.last_config.to_model().model_copy(deep=True)
    last_model.version_description = "Retest"

    target_paths = [
        (target.path, target.path.parent / (target.path.name.removesuffix(old_suffix) + new_suffix))
        for target in project.config.last_config.targets
    ]
    for _, destination in target_paths:
        if destination.exists() or destination.is_symlink():
            raise SeretoPathError(f"Target directory already exists: '{destination}'")

    for source, destination in target_paths:
        shutil.copytree(src=source, dst=destination)

    project.config.add_version_config(
        version=retest_version, config=last_model, templates=project.settings.templates_path
    ).save()
