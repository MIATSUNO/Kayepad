FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
COPY app.py .
COPY feature_endpoints.py .
COPY exlibris_media.py .
COPY account_endpoints.py .
COPY auth_endpoints.py .
COPY social_delivery_endpoints.py .
COPY admin_endpoints.py .
EXPOSE 8000
CMD ["uvicorn","app:app","--host","0.0.0.0","--port","8000"]
