FROM python:3.11-slim

ARG GIT_SHA=unknown
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_GIT_SHA=${GIT_SHA}

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# .dockerignore keeps .env, databases, virtualenvs, tests and VCS data out of the image.
COPY app ./app
COPY migrations ./migrations
COPY pyproject.toml .

# Run as an unprivileged user.
RUN useradd --system --uid 10001 --no-create-home appuser
USER appuser

EXPOSE 8000
# Migrations are a separate, explicit step (docs/STAGING.md); the app never creates schema.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
