FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv

RUN pip install --no-cache-dir fastapi uvicorn pymupdf openai

COPY app /srv/app
COPY engine /srv/engine

EXPOSE 8080

CMD ["uvicorn", "engine.main:app", "--host", "0.0.0.0", "--port", "8080"]
