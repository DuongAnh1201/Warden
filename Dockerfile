FROM python:3.13-slim

WORKDIR /app

RUN pip install uv --no-cache-dir

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

# Set SERVICE=server in Railway env vars for the WebSocket server service.
# Leave unset (or set to anything else) for the Fetch.ai uAgent service.
CMD ["sh", "-c", "if [ \"$SERVICE\" = 'server' ]; then uv run python server.py; else uv run python -m ai.transport.fetch_wrapper; fi"]
