FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

ARG INSTALL_RAG_LOCAL=0

COPY pyproject.toml README.md /app/
COPY ecom_agent_matrix /app/ecom_agent_matrix

RUN if [ "$INSTALL_RAG_LOCAL" = "1" ]; then \
        pip install --no-cache-dir ".[rag-local]"; \
    else \
        pip install --no-cache-dir .; \
    fi \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /app --shell /usr/sbin/nologin appuser \
    && chown -R appuser:app /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()"]

CMD ["uvicorn", "ecom_agent_matrix.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
