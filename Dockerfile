# Pinned by digest, not by tag: "python:3.11-slim" is a moving target, so two builds of
# the SAME commit could use different base images and only one of them be the one that was
# reviewed. The digest is an OCI image index covering 8 platforms, so arm64 and amd64 both
# still resolve. Dependabot (.github/dependabot.yml, docker ecosystem) proposes the bumps;
# a pin nobody updates is its own problem.
FROM python:3.11-slim@sha256:0dd364ba7e10242f07755449e3a3d0e35f9efd987952737b90def6709ab0c5ce

ARG GIT_SHA=unknown
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_GIT_SHA=${GIT_SHA}

WORKDIR /app
# The lock, not requirements.txt: every transitive dependency pinned with its hash, so a
# compromised or re-uploaded package on the index cannot change what lands in the image.
# tests/unit/test_dependency_lock.py fails if the lock drifts from requirements.txt.
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

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
