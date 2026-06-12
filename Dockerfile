# Application web de classement (FastAPI) — build Coolify
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UPLOAD_DIR=/data/uploads

WORKDIR /app

COPY pyproject.toml README.md ./
COPY classement ./classement
COPY webapp ./webapp
COPY data ./data

# Installation editable : le paquet `classement` résout data/ relativement au
# code source (classement/../data) — une installation classique casserait ce chemin.
RUN pip install --no-cache-dir -e .[webapp]

RUN useradd --create-home appuser \
    && mkdir -p /data/uploads \
    && chown -R appuser:appuser /data /app
USER appuser

VOLUME /data/uploads
EXPOSE 8000

# Migrations puis serveur (un seul worker : SQLAlchemy sync, charge faible).
CMD ["sh", "-c", "python -m alembic -c webapp/alembic.ini upgrade head && python -m uvicorn webapp.main:app --host 0.0.0.0 --port 8000"]
