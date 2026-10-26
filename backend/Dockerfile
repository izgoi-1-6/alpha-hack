FROM python:3.12.11-alpine
WORKDIR /app/backend
COPY backend/requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY backend .
COPY data /app/data
# The seed runs where the app is in demo mode: DEMO_MODE read as app.config reads it (case-insensitive, unset is true).
CMD ["sh", "-c", "alembic upgrade head && if [ \"$(printf '%s' \"${DEMO_MODE-true}\" | tr '[:upper:]' '[:lower:]')\" = true ]; then python -m app.seed; fi && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
