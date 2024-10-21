from collections.abc import Callable
from functools import wraps
from typing import TypeVar

from click import get_current_context
from typing_extensions import ParamSpec

from sereto.models.project import Project

P = ParamSpec("P")
R = TypeVar("R")


def load_project(f: Callable[..., R]) -> Callable[..., R]:
    """Decorator which calls `load_project_function` and provides Report as the first argument"""

    @wraps(f)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        project = Project.load_from()
        return get_current_context().invoke(f, project, *args, **kwargs)

    return wrapper
