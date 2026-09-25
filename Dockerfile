FROM python:3.12-slim

# ffmpeg: audio conversion. git/unzip/curl: fetch Deno + bgutil.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg git curl unzip ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Deno: yt-dlp needs a JS runtime to solve YouTube's challenges, and the
# bgutil PO-token script runs on it (beats "Sign in to confirm you're not a bot").
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno

# bgutil PO-token provider (script mode — no extra process to run).
ARG BGUTIL_VERSION=2.0.0
RUN git clone --depth 1 --branch ${BGUTIL_VERSION} \
        https://github.com/Brainicism/bgutil-ytdlp-pot-provider /opt/bgutil \
    && cd /opt/bgutil/server && (deno install --allow-scripts=npm:canvas || deno install) \
    && rm -rf /opt/bgutil/.git
ENV BGUTIL_SERVER_HOME=/opt/bgutil/server

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# your library (mp3s + playlist.json) lives here — mount a volume
VOLUME ["/app/data"]

EXPOSE 8000

ENV PORT=8000
CMD ["python", "server.py"]
