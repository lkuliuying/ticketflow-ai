FROM ghcr.io/astral-sh/uv:0.11.26 AS uv
FROM python:3.14.7-slim AS build

COPY --from=uv /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

FROM python:3.14.7-slim
RUN groupadd --system app && useradd --system --gid app app
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY app ./app
USER app
EXPOSE 8897
CMD ["/app/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8897"]
