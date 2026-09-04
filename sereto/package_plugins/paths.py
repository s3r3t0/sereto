import re
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from platformdirs import user_data_path

from sereto.exceptions import SeretoValueError

_PATH_SEGMENT = re.compile(r"^[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?$")


@dataclass(frozen=True)
class PluginPaths:
    """Managed package-plugin paths without implicit filesystem creation."""

    root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", self.root.expanduser().resolve())

    @classmethod
    def default(cls) -> Self:
        return cls(root=user_data_path("sereto") / "plugins")

    @property
    def registry_file(self) -> Path:
        return self.root / "registry.json"

    @property
    def registry_lock(self) -> Path:
        return self.root / "registry.lock"

    def plugin_dir(self, plugin_id: str) -> Path:
        return self.root / self._segment(plugin_id, "plugin ID")

    def plugin_data_dir(self, plugin_id: str) -> Path:
        return self.plugin_dir(plugin_id) / "data"

    def generations_dir(self, plugin_id: str) -> Path:
        return self.plugin_dir(plugin_id) / "generations"

    def generation_dir(self, plugin_id: str, generation_id: str) -> Path:
        return self.generations_dir(plugin_id) / self._segment(generation_id, "generation ID")

    @staticmethod
    def _segment(value: str, label: str) -> str:
        if not _PATH_SEGMENT.fullmatch(value):
            raise SeretoValueError(f"invalid {label}: {value!r}")
        return value
