from collections.abc import Callable
from functools import total_ordering
from typing import Annotated, Any

from pydantic import (
    GetJsonSchemaHandler,
    RootModel,
    field_validator,
    model_serializer,
)
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema
from semver import Version

from sereto.exceptions import SeretoTypeError

__all__ = ["SeretoVersion", "ReportVersion"]


class _VersionPydanticAnnotation:
    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source_type: Any,
        _handler: Callable[[Any], core_schema.CoreSchema],
    ) -> core_schema.CoreSchema:
        def validate_from_str(value: str) -> Version:
            return Version.parse(value)

        from_str_schema = core_schema.chain_schema(
            [
                core_schema.str_schema(),
                core_schema.no_info_plain_validator_function(validate_from_str),
            ]
        )

        return core_schema.json_or_python_schema(
            json_schema=from_str_schema,
            python_schema=core_schema.union_schema(
                [
                    core_schema.is_instance_schema(Version),
                    from_str_schema,
                ]
            ),
            serialization=core_schema.to_string_ser_schema(),
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls, _core_schema: core_schema.CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        return handler(core_schema.str_schema())


VersionPydanticAnnotation = Annotated[Version, _VersionPydanticAnnotation]


@total_ordering
class SeretoVersion(RootModel[VersionPydanticAnnotation]):
    root: VersionPydanticAnnotation

    @field_validator("root", mode="after")
    @classmethod
    def prerelease_build_not_set(cls, v: Version) -> Version:
        if v.prerelease is not None or v.build is not None:
            raise ValueError("only major, minor, patch parts supported")
        return v

    @model_serializer()
    def serialize_model(self) -> str:
        return self.__str__()  # type: ignore[call-arg]

    def __str__(self) -> str:
        return self.root.__str__()

    def __lt__(self, other: Any) -> bool:
        if type(self) is not type(other):
            raise SeretoTypeError("incompatible types for comparison")
        return self.root < other.root

    def __eq__(self, other: Any) -> bool:
        if type(self) is not type(other):
            raise SeretoTypeError("incompatible types for comparison")
        return self.root == other.root

    def __hash__(self) -> int:
        return self.root.__hash__()

    @classmethod
    def from_str(cls, v: str) -> "SeretoVersion":
        """Create a SeretoVersion instance from a string.

        This method primarily exists to satisfy type checker.

        Args:
            v: The string representation of the version, e.g. "1.2.3".

        Returns:
            A SeretoVersion instance constructed from the string representation.
        """
        return SeretoVersion.model_construct(root=Version.parse(v))


class VersionVPrefix(Version):
    """A subclass of Version which allows a "v" prefix."""

    @classmethod
    def parse(cls, v: str) -> "Version":  # type: ignore[override]
        """
        Parse version string to a Version instance.

        Args:
            v: version string with "v" prefix

        Raises:
            ValueError: when version does not start with "v"

        Returns:
            A new Version instance
        """
        if len(v) == 0 or v[0] != "v" or len(v.split(".")) != 2:
            raise ValueError("invalid format: use vMAJOR.MINOR")
        return Version.parse(v[1:], optional_minor_and_patch=True)

    def __str__(self) -> str:
        return f"v{super().__str__()}"


class _VersionVPrefixPydanticAnnotation:
    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source_type: Any,
        _handler: Callable[[Any], core_schema.CoreSchema],
    ) -> core_schema.CoreSchema:
        def validate_from_str(value: str) -> Version:
            return VersionVPrefix.parse(value)

        from_str_schema = core_schema.chain_schema(
            [
                core_schema.str_schema(),
                core_schema.no_info_plain_validator_function(validate_from_str),
            ]
        )

        return core_schema.json_or_python_schema(
            json_schema=from_str_schema,
            python_schema=core_schema.union_schema(
                [
                    core_schema.is_instance_schema(Version),
                    from_str_schema,
                ]
            ),
            serialization=core_schema.to_string_ser_schema(),
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls, _core_schema: core_schema.CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        return handler(core_schema.str_schema())


VersionVPrefixPydanticAnnotation = Annotated[Version, _VersionVPrefixPydanticAnnotation]


@total_ordering
class ReportVersion(RootModel[VersionVPrefixPydanticAnnotation]):
    root: VersionVPrefixPydanticAnnotation

    @field_validator("root", mode="after")
    @classmethod
    def prerelease_build_not_set(cls, v: Version) -> Version:
        if v.prerelease is not None or v.build is not None or v.patch != 0:
            raise ValueError("only major, minor parts are supported")
        return v

    @model_serializer()
    def serialize_model(self) -> str:
        return self.__str__()  # type: ignore[call-arg]

    def __lt__(self, other: Any) -> bool:
        if type(self) is not type(other):
            raise SeretoTypeError("incompatible types for comparison")
        return self.root < other.root

    def __eq__(self, other: Any) -> bool:
        if type(self) is not type(other):
            raise SeretoTypeError("incompatible types for comparison")
        return self.root == other.root

    def __hash__(self) -> int:
        return self.root.__hash__()

    def __str__(self) -> str:
        return f"v{self.root.major}.{self.root.minor}"

    @classmethod
    def from_str(cls, v: str) -> "ReportVersion":
        """Create a ReportVersion instance from a string.

        This method primarily exists to satisfy type checker.

        Args:
            v: The string representation of the version, e.g. "v2.0".

        Returns:
            A ReportVersion instance constructed from the string representation.
        """
        if len(v) == 0 or v[0] != "v" or len(v.split(".")) != 2:
            raise ValueError("invalid format: use vMAJOR.MINOR")
        return ReportVersion.model_construct(root=Version.parse(v[1:], optional_minor_and_patch=True))

    def next_major_version(self) -> "ReportVersion":
        return ReportVersion(f"v{self.root.major + 1}.{self.root.minor}")  # type: ignore[arg-type]

    def next_minor_version(self) -> "ReportVersion":
        return ReportVersion(f"v{self.root.major}.{self.root.minor + 1}")  # type: ignore[arg-type]

    @property
    def path_suffix(self) -> str:
        return f"_{self.__str__()}" if self.root.major != 1 or self.root.minor != 0 else ""
