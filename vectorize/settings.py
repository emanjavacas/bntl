
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
    VECTORIZER_DB: str = Field(default="vectorizer")
    TASKS_COLL: str = Field(default="tasks")
    VECTORS_COLL: str = Field(default="vectors")

    BATCH_SIZE: int = Field(default=48)
    RETRY_DELAY: int = Field(default=3600 * 10)
    MAX_RETRIES: int = Field(default=5)

    model_config = SettingsConfigDict(env_file=".vectorizer.env", extra="ignore")


settings = Settings()