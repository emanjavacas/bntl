
import os
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
    VECTORIZER_HOST: str = Field(help="Hostname where the vectorizer is running", default="localhost")
    VECTORIZER_PORT: str = Field(help="Port on which the vectorization server is running")

    MONGODB_PORT: int = Field(help="MongoDB port", default=27017)
    MONGODB_HOST: str = Field(help='MongoDB host', default="localhost")
    LOCAL_DB: str = Field(help="Local MongoDB BNTL database name", default="bntl")
    BNTL_COLL: str = Field(help="MongoDB BNTL collection name", default="bntl")
    AUTOCOMPLETE_COLL: str = Field(help="MongoDB autocomplete collection name", default="autocomplete")
    QUERY_COLL: str = Field(help="MongoDB query collection name", default="queries")
    UPLOAD_COLL: str = Field(help="MongoDB collection name for handling file uploads", default="upload")
    UPLOAD_SECRET: str = Field(help="Secret to run the upload logic", default="pass")
    VECTORIZATION_COLL: str = Field(help="MongoDB collection name for handling file uploads", default="vectorization")

    WITHIN_MAX_RESULTS: int = Field(help="Restrict results of original query to this number when doing recursive query", default=300_000)
    MAX_EXPORT_RESULTS: int = Field(help="Maximum number of documents to be exported", default=100)

    QDRANT_HOST: str = Field(help="Host for qdrant", default="localhost")
    QDRANT_HTTP_PORT: int = Field(help="Port used by QDrant (usually 6333)", default=6333)
    QDRANT_GRPC_PORT: int = Field(help="Port used by QDrant (usually 6334)", default=6334)
    QDRANT_COLL: str = Field(default="bntl")

    UPLOAD_LOG_DIR: str = Field(default="logs/upload", help="Directory to store the upload log files")
    VECTORIZE_LOG_DIR: str = Field(default="logs/vectorize", help="Directory to store the vectorization log files")
    TRANSLATIONS_DIR: str = Field(default="static/translations")
    DEFAULT_LOCALE: str = Field(default="nl")

    WORKERS: int = Field(help="Number of workers for the uvicorn server", default=1)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

if not os.path.isdir(settings.UPLOAD_LOG_DIR):
    os.makedirs(settings.UPLOAD_LOG_DIR)
if not os.path.isdir(settings.VECTORIZE_LOG_DIR):
    os.makedirs(settings.VECTORIZE_LOG_DIR)
