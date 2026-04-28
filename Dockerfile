# syntax=docker/dockerfile:1

FROM node:22-bookworm-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim-bookworm
WORKDIR /app

COPY pyproject.toml ./
COPY backend ./backend
COPY alembic ./alembic
COPY alembic.ini ./

COPY --from=frontend /app/frontend/dist ./frontend/dist

RUN pip install --no-cache-dir pip setuptools wheel \
    && pip install --no-cache-dir -e .

ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
