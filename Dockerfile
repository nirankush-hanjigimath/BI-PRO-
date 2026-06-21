# syntax=docker/dockerfile:1
FROM python:3.11-slim

LABEL maintainer="you"
LABEL description="Binance Futures Market Monitor with AI-assisted Discord alerts"

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first (layer-cached)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Create log directory (will also be created by the app at runtime)
RUN mkdir -p logs

# The .env file is NOT copied — supply secrets via Docker environment variables:
#   docker run -e ANTHROPIC_API_KEY=... -e DISCORD_WEBHOOK_URL=... ...
# Or use a Docker secrets / docker-compose env_file approach.

CMD ["python", "main.py"]
