FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN useradd --create-home --uid 10001 moneybee

COPY pyproject.toml .

RUN pip install --no-cache-dir .

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini .
COPY scripts ./scripts

USER moneybee

EXPOSE 8000

CMD [
  "uvicorn",
  "app.main:app",
  "--host",
  "0.0.0.0",
  "--port",
  "8000"
]
