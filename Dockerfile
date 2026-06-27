FROM python:3.12-slim

WORKDIR /app

# build deps for asyncpg/sqlite-vec wheels fall back; curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc curl \
    && rm -rf /var/lib/apt/lists/*

COPY . /app
RUN pip install --no-cache-dir -e ".[postgres]"

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD curl -fsS http://localhost:8000/health || exit 1

# migrations run on startup; --no-onboarding reads creds from the environment
CMD ["python", "-m", "recall", "--no-onboarding"]
