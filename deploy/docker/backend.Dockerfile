FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl default-mysql-client redis-tools tar gzip python3.12 python3.12-venv \
    && rm -rf /var/lib/apt/lists/*
RUN python3.12 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY pyproject.toml alembic.ini ./
COPY app ./app
COPY judge ./judge
COPY scripts ./scripts
COPY alembic ./alembic
COPY tests ./tests
COPY deploy ./deploy
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir '.[dev]'
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--workers", "2"]
