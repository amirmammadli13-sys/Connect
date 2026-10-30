FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir fastapi "uvicorn[standard]"

COPY . .

EXPOSE 8001
CMD ["uvicorn", "recommendation_service:app", "--host", "0.0.0.0", "--port", "8001"]
