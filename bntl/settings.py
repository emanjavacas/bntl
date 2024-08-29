
from typing import Type, Tuple
import logging.config

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings import PydanticBaseSettingsSource, TomlConfigSettingsSource
from pydantic import Field

import toml


def setup_logger(path='settings_logger.toml'):
    with open(path) as f:
        config = toml.load(f)
        logging.config.dictConfig(config)


class Settings(BaseSettings):
    PORT: int = Field(help="Server port")
    BNTL_URI: str = Field(help='MongoDB URI used for the database logic. For example: "mongodb://localhost:27017"')
    BNTL_COLL: str = Field(help="MongoDB BNTL collection name", default="bntl")
    BNTL_DB: str = Field(help="MongoDB BNTL database name", default="bntl")

    LOCAL_URI: str = Field(help='MongoDB URI for the local logic. For example: "mongodb://localhost:27017"')
    QUERY_COLL: str = Field(help="MongoDB query collection name", default="queries")
    UPLOAD_COLL: str = Field(help="MongoDB collection name for handling file uploads", default="upload")
    LOCAL_DB: str = Field(help="Local MongoDB BNTL database name", default="bntl")
    UPLOAD_SECRET: str = Field(help="Secret to run the upload logic")

    QDRANT_PORT: int = Field(help="Port used by QDrant (usually 6333)")
    QDRANT_COLL: str = Field(default="bntl")

    WORKERS: int = Field(help="Number of workers for the uvicorn server", default=1)

    model_config = SettingsConfigDict(toml_file=["settings.toml", "secret_settings.toml"])

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