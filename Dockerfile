FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y libfbclient2 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

CMD ["python", "-u", "scripts/start_backend.py"]
