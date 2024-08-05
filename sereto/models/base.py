from pydantic import BaseModel, ConfigDict
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)


class SeretoBaseModel(BaseModel):
    """Pydantic BaseModel with custom configuration.

    This class is a subclass of pydantic's BaseModel. It is used to define custom configuration for pydantic models.
    """

    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)


class SeretoBaseSettings(BaseSettings):
    """Pydantic's BaseSettings with custom configuration."""

    model_config = SettingsConfigDict(
        env_prefix="SERETO_",
        extra="forbid",
        # strict=True,
        validate_assignment=True,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Define the sources and their order for loading the settings values.

        Args:
            settings_cls: The Settings class.
            init_settings: The `InitSettingsSource` instance.
            env_settings: The `EnvSettingsSource` instance.
            dotenv_settings: The `DotEnvSettingsSource` instance.
            file_secret_settings: The `SecretsSettingsSource` instance.

        Returns:
            A tuple containing the sources and their order for loading the settings values.
        """
        return env_settings, init_settings, dotenv_settings, file_secret_settings
