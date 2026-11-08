# One image for every Python service (api, researcher, verifier, llm-gateway, llm-stub, ingest).
# Each service runs a different command; see docker-compose.yml.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PYTHONPATH=/app/src
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# Bake the embedding model into the image so containers start offline and identically.
ARG EMBED_MODEL
ENV EMBED_CACHE_DIR=/models
RUN test -n "$EMBED_MODEL" || (echo "EMBED_MODEL build arg is required (set it in .env)" && exit 1); \
    python -c "import os; from fastembed import TextEmbedding; TextEmbedding(model_name=os.environ['EMBED_MODEL'], cache_dir='/models'); print('model cached')"

COPY src ./src
COPY prompts ./prompts
COPY corpus ./corpus

RUN useradd --create-home --uid 10001 app && chown -R app /app /models
USER app

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "triage.api:app", "--host", "0.0.0.0", "--port", "8000"]
