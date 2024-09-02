
from typing import Type, Tuple
import logging.config

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings import PydanticBaseSettingsSource, TomlConfigSettingsSource
from pydantic import Field

import toml


def setup_logger(path='settings_vectorizer_logger.toml'):
    with open(path) as f:
        config = toml.load(f)
        logging.config.dictConfig(config)


class Settings(BaseSettings):
    PORT: int = Field(help="Server port", default=6666)

    VECTORIZER_DB: str = Field(default="vectorizer")
    TASKS_COLL: str = Field(default="tasks")
    VECTORS_COLL: str = Field(default="vectors")

    BATCH_SIZE: int = Field(default=48)
    RETRY_DELAY: int = Field(default=3600 * 10)
    MAX_RETRIES: int = Field(default=5)

    WORKERS: int = Field(help="Number of workers for the uvicorn server", default=1)

    model_config = SettingsConfigDict(toml_file=["settings_vectorizer.toml"])

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        return (TomlConfigSettingsSource(settings_cls),)


settings = Settings()