FROM python:3.12-slim

# ffmpeg is required for audio conversion
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# your library (mp3s + playlist.json) lives here — mount a volume
VOLUME ["/app/data"]

EXPOSE 8000

ENV PORT=8000
CMD ["python", "server.py"]
