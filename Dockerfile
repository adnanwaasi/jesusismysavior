FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

RUN addgroup --gid 1000 app && adduser --uid 1000 --gid 1000 --disabled-password --gecos "" app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY migrations ./migrations

USER app

CMD ["python", "-m", "app.monitor"]
