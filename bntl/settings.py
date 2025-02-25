
import os
import logging.config
from typing import Literal, Optional, List

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, EmailStr, model_validator

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
    VECTORIZATION_COLL: str = Field(help="MongoDB collection name for handling file uploads", default="vectorization")

    WITHIN_MAX_RESULTS: int = Field(help="Restrict results of original query to this number when doing recursive query", default=300_000)
    MAX_EXPORT_RESULTS: int = Field(help="Maximum number of documents to be exported", default=100)

    QDRANT_HOST: str = Field(help="Host for qdrant", default="localhost")
    QDRANT_HTTP_PORT: int = Field(help="Port used by QDrant (usually 6333)", default=6333)
    QDRANT_GRPC_PORT: int = Field(help="Port used by QDrant (usually 6334)", default=6334)
    QDRANT_COLL: str = Field(default="bntl")

    REDIS_HOST: str = Field(help="Redis hostname", default="localhost")
    REDIS_PORT: int = Field(help="Redis port", default=6379)

    UPLOAD_LOG_DIR: str = Field(default="logs/upload", help="Directory to store the upload log files")
    VECTORIZE_LOG_DIR: str = Field(default="logs/vectorize", help="Directory to store the vectorization log files")
    TRANSLATIONS_DIR: str = Field(default="static/translations")
    DEFAULT_LOCALE: str = Field(default="nl")

    SESSION_TIME: int = Field(help="Expiration time for validated session (secs)", default=60 * 60 * 1) # one hour
    AUTH: Literal["mail", "password"] = Field(default="password")
    # password-based authentication
    AUTH_SECRET: str = Field(help="Secret to run the upload logic", default="pass")
    # mail-based authentication
    VERIFICATION_TOKEN_TIME: int = Field(help="Expiration time for token (secs)", default=60 * 5) # 5 minutes
    MAIL_SERVER: Optional[str] = Field(help="Mail server", default=None)
    MAIL_FROM: Optional[str] = Field(help="Sender for mail server", default=None)
    MAIL_PORT: Optional[int] = Field(help="Port for mail server", default=None)
    ADMIN_MAILS: List[EmailStr] = Field(help="List of emails", default=[])

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def check_mail_auth(self):
        if self.AUTH == "mail":
            for setting in ["MAIL_SERVER", "MAIL_FROM", "MAIL_PORT", "ADMIN_MAILS"]:
                if not getattr(self, setting): # empty or None
                    raise ValueError(f"mail AUTH needs MAIL config. Missing '{setting}'")
        return self


settings = Settings()

if not os.path.isdir(settings.UPLOAD_LOG_DIR):
    os.makedirs(settings.UPLOAD_LOG_DIR)
if not os.path.isdir(settings.VECTORIZE_LOG_DIR):
    os.makedirs(settings.VECTORIZE_LOG_DIR)
