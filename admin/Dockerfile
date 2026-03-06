FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 데이터 볼륨 (Railway에서 Persistent Volume 연결)
RUN mkdir -p /data
ENV DATABASE_PATH=/data/admin_data.db

EXPOSE 9090

CMD ["python", "admin_server.py"]
