FROM python:3.12

RUN apt-get update && apt-get install -y \
    build-essential \
    bibutils \
    && rm -rf /var/lib/apt/lists/*

RUN curl -sSL https://install.python-poetry.org | python3 -

WORKDIR /app

COPY pyproject.toml poetry.lock ./

RUN poetry install

COPY . .

