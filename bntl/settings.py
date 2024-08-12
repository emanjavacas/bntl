
from typing import Type, Tuple, Dict, Union, List
import logging.config

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings import PydanticBaseSettingsSource, TomlConfigSettingsSource
from pydantic import BaseModel, Field

import toml


def setup_logger(path='settings_logger.toml'):
    with open(path) as f:
        config = toml.load(f)
        logging.config.dictConfig(config)


class Settings(BaseSettings):
    PORT: int = Field(help="Server port")
    BNTL_URI: str = Field(help="MongoDB URI used for connection")
    BNTL_COLL: str = Field(help="MongoDB BNTL collection name", default="bntl")
    BNTL_DB: str = Field(help="MongoDB BNTL database name", default="bntl")

    QUERY_URI: str = Field()
    QUERY_COLL: str = Field(help="MongoDB BNTL collection name", default="queries")
    QUERY_DB: str = Field(help="MongoDB BNTL database name", default="query")

    model_config = SettingsConfigDict(toml_file="settings.toml")

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