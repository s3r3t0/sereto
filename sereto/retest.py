import shutil
from copy import deepcopy

from pydantic import validate_call

from sereto.project import Project


@validate_call
def add_retest(project: Project) -> None:
    last_version = project.config.last_version
    retest_version = last_version.next_major_version()

    old_suffix = last_version.path_suffix
    new_suffix = retest_version.path_suffix

    # Copy target directories
    for target in project.config.at_version(last_version).targets:
        new_target_dir = target.path.parent / (target.path.name.removesuffix(old_suffix) + new_suffix)
        shutil.copytree(src=target.path, dst=new_target_dir)

    # Duplicate last version config
    last_config = deepcopy(project.config.last_config)
    last_config.version_description = "Retest"
    project.config.add_version_config(
        version=retest_version, config=last_config.to_model(), templates=project.settings.templates_path
    ).save()
