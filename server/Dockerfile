FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# Install both the legacy app deps and the FastAPI server deps.
COPY requirements.txt /app/requirements.txt
COPY server/requirements.txt /app/server-requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt -r /app/server-requirements.txt

COPY . /app/

EXPOSE 8600
CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8600"]
