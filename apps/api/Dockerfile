FROM python:3.13-slim
WORKDIR /srv
RUN pip install uv
COPY pyproject.toml ./
RUN uv pip install --system -e . || uv pip install --system fastapi "uvicorn[standard]" \
    "sqlalchemy[asyncio]" asyncpg alembic pydantic pydantic-settings arq redis boto3 jinja2 \
    pymupdf python-docx httpx structlog
COPY . .
EXPOSE 8000
