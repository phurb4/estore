FROM python:3.13.18-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /srv
COPY requirements.txt .
# Security fix for zlib1g (Debian), only that package.
RUN apt-get update \
 && apt-get install -y --no-install-recommends --only-upgrade zlib1g \
 && rm -rf /var/lib/apt/lists/*
# pip is removed after installing: its bundled copies of msgpack, urllib3 and
# setuptools carried HIGH vulnerabilities, and the running service never needs pip.
RUN pip install --require-hashes -r requirements.txt \
 && pip uninstall -y pip
COPY app ./app

USER 10001:10001

CMD ["python", "-m", "uvicorn", "app.main:create_app", "--factory"]
