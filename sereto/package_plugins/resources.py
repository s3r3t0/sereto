import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Self

from pydantic import ValidationError

from sereto.exceptions import SeretoValueError
from sereto.package_plugins.protocol_v1 import Resource, ResourceReference
from sereto.target import Target


def _new_target_id() -> str:
    return f"target_{uuid.uuid4().hex}"


@dataclass(frozen=True)
class TargetResources:
    """Invocation-scoped target resources and their private host bindings."""

    resources: tuple[Resource, ...]
    _targets: Mapping[str, Target] = field(repr=False, compare=False)

    @classmethod
    def from_targets(
        cls,
        targets: Iterable[Target],
        id_factory: Callable[[], str] = _new_target_id,
    ) -> Self:
        resources: list[Resource] = []
        target_map: dict[str, Target] = {}
        for target in targets:
            resource_id = id_factory()
            if resource_id in target_map:
                raise SeretoValueError(f"duplicate package-plugin resource ID: {resource_id!r}")
            try:
                resource = Resource(
                    kind="sereto.target.v1",
                    id=resource_id,
                    attributes={
                        "category": target.data.category,
                        "name": target.data.name,
                        "version": str(target.version),
                        "locators": [
                            locator.model_dump(mode="json", exclude_none=True) for locator in target.data.locators
                        ],
                    },
                )
            except ValidationError as error:
                raise SeretoValueError(f"invalid package-plugin target resource: {error}") from error
            resources.append(resource)
            target_map[resource_id] = target
        return cls(resources=tuple(resources), _targets=MappingProxyType(target_map))

    def resolve(self, reference: ResourceReference) -> Target:
        """Resolve a plugin-echoed target reference within this invocation."""
        try:
            return self._targets[reference.id]
        except KeyError:
            raise SeretoValueError(f"unknown package-plugin target resource: {reference.id!r}") from None
