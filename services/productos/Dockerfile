FROM python:3.13.18-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app ./app

USER 10001:10001

CMD ["python", "-m", "uvicorn", "app.main:create_app", "--factory"]
