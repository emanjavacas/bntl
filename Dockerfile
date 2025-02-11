FROM python:3.12

RUN apt-get update \
&& apt-get install --no-install-recommends -y \
bibutils

WORKDIR /app

RUN pip3 install --no-cache-dir poetry

COPY pyproject.toml ./

RUN poetry config virtualenvs.create false \
    && poetry install --no-root --no-interaction --no-ansi --with vectorizer

COPY . .
