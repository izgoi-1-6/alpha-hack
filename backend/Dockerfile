FROM python:3.12.11-alpine
WORKDIR /app/backend
COPY backend/requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY backend .
COPY data /app/data
CMD ["sh", "-c", "alembic upgrade head && if [ \"$DEMO_MODE\" = true ]; then python -m app.seed; fi && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
