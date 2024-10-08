
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

    LOCAL_URI: str = Field(help='MongoDB URI for the local data. For example: "mongodb://localhost:27017"')
    LOCAL_DB: str = Field(help="Local MongoDB BNTL database name", default="bntl")
    BNTL_COLL: str = Field(help="MongoDB BNTL collection name", default="bntl")
    SOURCE_COLL: str = Field(help="Collection name for storing source data", default="source")
    AUTOCOMPLETE_COLL: str = Field(help="MongoDB autocomplete collection name", default="autocomplete")
    BNTL_DB: str = Field(help="MongoDB BNTL database name", default="bntl")
    QUERY_COLL: str = Field(help="MongoDB query collection name", default="queries")
    UPLOAD_COLL: str = Field(help="MongoDB collection name for handling file uploads", default="upload")
    UPLOAD_SECRET: str = Field(help="Secret to run the upload logic")

    WITHIN_MAX_RESULTS: int = Field(help="Restrict results of original query to this number when doing recursive query", default=300_000)
    MAX_EXPORT_RESULTS: int = Field(help="Maximum number of documents to be exported", default=100)

    QDRANT_PORT: int = Field(help="Port used by QDrant (usually 6333)")
    QDRANT_COLL: str = Field(default="bntl")

    UPLOAD_LOG_DIR: str = Field(default="./logs", help="Directory to store the upload log files")
    BABEL_TRANSLATIONS_DIR: str = Field(default="static/translations")

    RETRY_DELAY: int = Field(default=3600 * 10)
    MAX_RETRIES: int = Field(default=5)
    BATCH_SIZE: int = Field(default=48)

    WORKERS: int = Field(help="Number of workers for the uvicorn server", default=1)

    model_config = SettingsConfigDict(toml_file=["settings.toml", "settings_secret.toml"])

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