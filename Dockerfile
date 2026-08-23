FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

RUN addgroup --system moneybee && adduser --system --ingroup moneybee moneybee
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --no-cache-dir .

USER moneybee
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
