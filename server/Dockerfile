FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY app /app/app
COPY static /app/static

ENV OPSLENS_DB_PATH=/data/opslens.db
ENV OPSLENS_MAX_UPLOAD_MB=20

EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

