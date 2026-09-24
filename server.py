#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Coda — local, ad-free audio jukebox.

Paste any video URL (YouTube, Instagram, TikTok, X, Facebook, 1000+ sites)
-> audio is extracted (mp3) -> added to your playlist -> played with full
control (repeat off / repeat all / repeat one).

100% local: no accounts, no API keys, no paid services.

LEGAL: personal use only. Extract audio only from content you own,
have permission to use, or that is freely licensed (e.g. Creative Commons).
See the Legal section in README.md.
"""

import datetime
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import uuid

from flask import Flask, Response, abort, jsonify, request, send_file, send_from_directory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
TRACKS_DIR = os.path.join(DATA_DIR, "tracks")
THUMB_DIR = os.path.join(DATA_DIR, "thumbs")
PLAYLIST_FILE = os.path.join(DATA_DIR, "playlist.json")
COOKIES_FILE = os.path.join(DATA_DIR, "cookies.txt")

for _d in (DATA_DIR, TRACKS_DIR, THUMB_DIR):
    os.makedirs(_d, exist_ok=True)

app = Flask(__name__, static_folder=os.path.join(BASE_DIR, "static"), static_url_path="")

JOBS = {}
JOBS_LOCK = threading.Lock()
PLAYLIST_LOCK = threading.Lock()

MP3_QUALITY = "192"  # kbps. Use "320" for max quality.


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def load_playlist():
    default = {"name": "My Coda Playlist", "tracks": []}
    if not os.path.exists(PLAYLIST_FILE):
        return default
    try:
        with open(PLAYLIST_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict) or not isinstance(data.get("tracks"), list):
            return default
        return data
    except Exception:
        return default


def save_playlist(pl):
    tmp = PLAYLIST_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(pl, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, PLAYLIST_FILE)


def job_set(job_id, **kw):
    with JOBS_LOCK:
        job = JOBS.setdefault(job_id, {"status": "pending", "stage": "queued", "progress": 0.0})
        job.update(kw)
        return dict(job)


def job_get(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        return dict(job) if job else None


def cleanup_partial(track_id):
    """Remove files of a failed extraction (best effort)."""
    for d in (TRACKS_DIR, THUMB_DIR):
        for fn in os.listdir(d):
            if fn.startswith(track_id):
                try:
                    os.remove(os.path.join(d, fn))
                except OSError:
                    pass


def probe(url, timeout=6):
    """Cheap reachability probe used by /api/health."""
    try:
        host = url
        if ":" in host:
            host = host.split(":")[0]
        socket.create_connection((host, 443), timeout=timeout).close()
        return True
    except Exception:
        return False


def ffprobe_duration(path):
    """Get audio duration in seconds using ffmpeg/ffprobe (best effort)."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        # try to use ffmpeg's own dir if ffmpeg is a static build
        ffmpeg_path = shutil.which("ffmpeg")
        if ffmpeg_path:
            cand = os.path.join(os.path.dirname(ffmpeg_path), "ffprobe")
            if os.path.exists(cand):
                ffprobe = cand
    if not ffprobe:
        return None
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30,
        )
        return round(float(out.stdout.strip()), 1)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# extraction job (runs in background thread)
# ---------------------------------------------------------------------------
def extract_audio(job_id, url):
    try:
        import yt_dlp
    except Exception as e:
        job_set(job_id, status="error", stage="error",
                error="yt-dlp is not installed. Run: pip install -r requirements.txt (%s)" % e)
        return
    if shutil.which("ffmpeg") is None:
        job_set(job_id, status="error", stage="error",
                error="ffmpeg not found on PATH. Install ffmpeg (see README).")
        return

    track_id = uuid.uuid4().hex[:12]
    template = os.path.join(TRACKS_DIR, track_id)

    def progress_hook(d):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            frac = (done / total) if total else 0.0
            speed = d.get("speed")
            speed_s = " %.1f MB/s" % (speed / 1024 / 1024) if speed else ""
            job_set(job_id, status="downloading",
                    stage="downloading audio %d%%%s" % (int(min(frac, 1.0) * 100), speed_s),
                    progress=min(frac, 0.95))
        elif d.get("status") == "finished":
            job_set(job_id, stage="converting to mp3...", progress=0.95)

    def make_opts(cookiefile, player_client):
        opts = {
            "format": "bestaudio/best[acodec!=none]/best",
            "outtmpl": template,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [progress_hook],
            "writethumbnail": True,
            "thumbnail_format": "jpg",
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3",
                 "preferredquality": MP3_QUALITY},
                {"key": "FFmpegMetadata"},
            ],
            "postprocessor_args": [],
        }
        if cookiefile:
            opts["cookiefile"] = cookiefile
        if player_client:
            opts["extractor_args"] = {"youtube": {"player_client": player_client}}
        return opts

    # Ladder of extraction configs. Local IPs usually work with the default
    # client (best quality, tried first); datacenter IPs (Render, VPS) get
    # through with cookies and/or non-web clients. The first config that
    # produces a file wins.
    has_cookies = os.path.exists(COOKIES_FILE)
    # Each config may list several player clients; yt-dlp falls through the
    # list when a client raises (e.g. the bot-check error).
    configs = [("default", None, None)]
    if has_cookies:
        configs.append(("cookies+web", COOKIES_FILE, ["web", "android", "ios", "tv"]))
        configs.append(("cookies+android", COOKIES_FILE, ["android", "tv", "ios"]))
    configs.append(("android", None, ["android", "ios", "tv"]))
    configs.append(("tv", None, ["tv", "ios"]))

    info, produced, attempts = {}, None, []
    for label, ck, pc in configs:
        try:
            with yt_dlp.YoutubeDL(make_opts(ck, pc)) as ydl:
                info = ydl.extract_info(url, download=True) or {}
                if "entries" in info:  # playlist URL -> take first entry
                    info = (info["entries"] or [{}])[0]
        except Exception as e:
            attempts.append("%s: %s" % (label, str(e)[:180]))
            cleanup_partial(track_id)
            job_set(job_id, stage="%s failed, retrying…" % label)
            continue
        produced = None
        for ext in (".mp3", ".m4a", ".opus", ".webm", ".flac"):
            p = template + ext
            if os.path.exists(p):
                produced = p
                break
        if produced is None:
            for fn in os.listdir(TRACKS_DIR):
                if fn.startswith(track_id):
                    produced = os.path.join(TRACKS_DIR, fn)
                    break
        if produced is not None:
            break
        attempts.append("%s: no audio file produced" % label)
        cleanup_partial(track_id)
        job_set(job_id, stage="%s produced no file, retrying…" % label)

    if produced is None:
        # dedupe identical errors, keep at most 4 distinct attempts
        seen, brief = set(), []
        for a in attempts:
            key = a.split(":", 1)[-1].strip()[:60]
            if key not in seen:
                seen.add(key)
                brief.append(a[:200])
        msg = " | ".join(brief[:4]) or "extraction failed"
        if any("Sign in to confirm" in a or "not a bot" in a for a in attempts):
            msg += (" | YouTube is blocking this server's IP. Open Settings on the page, "
                    "upload the FULL cookies.txt exported from your own browser session "
                    "at youtube.com (keep all cookies, including __Secure-* and "
                    "ST-* tokens), and try again.")
        job_set(job_id, status="error", stage="error", error=msg[:1600])
        print("[coda] extract failed:", msg[:300], flush=True)
        return

    # final mp3 name
    final_path = os.path.join(TRACKS_DIR, track_id + ".mp3")
    if os.path.abspath(produced) != os.path.abspath(final_path):
        os.replace(produced, final_path)

    thumb_url = None
    for fn in os.listdir(TRACKS_DIR):
        if fn.startswith(track_id) and fn != track_id + ".mp3":
            final_thumb = os.path.join(THUMB_DIR, track_id + ".jpg")
            os.replace(os.path.join(TRACKS_DIR, fn), final_thumb)
            thumb_url = "/thumbs/%s.jpg" % track_id
            break

    duration = info.get("duration")
    if not duration:
        duration = ffprobe_duration(final_path)

    title = (info.get("title") or "Unknown title").strip()
    artist = (info.get("artist") or info.get("uploader") or info.get("channel") or "").strip()

    with PLAYLIST_LOCK:
        pl = load_playlist()
        track = {
            "id": track_id,
            "title": title,
            "artist": artist,
            "duration": duration,
            "source_url": info.get("webpage_url") or url,
            "file": track_id + ".mp3",
            "thumbnail": thumb_url,
            "added_at": now_iso(),
        }
        pl["tracks"].append(track)
        save_playlist(pl)

    job_set(job_id, status="done", stage="done", progress=1.0, track=track)
    print("[coda] added: %s (%s, %ss)" % (title, artist, duration), flush=True)


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------
@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.get("/api/health")
def health():
    yt_dlp_ok, yt_dlp_ver = False, None
    try:
        import yt_dlp
        yt_dlp_ok = True
        yt_dlp_ver = yt_dlp.version.__version__
    except Exception:
        pass
    ffmpeg_path = shutil.which("ffmpeg")
    ffmpeg_ok = bool(ffmpeg_path)
    ff_version = None
    if ffmpeg_ok:
        try:
            ff_version = subprocess.run(
                [ffmpeg_path, "-version"], capture_output=True, text=True, timeout=10
            ).stdout.splitlines()[0]
        except Exception:
            ff_version = "installed"
    return jsonify({
        "python": sys.version.split()[0],
        "yt_dlp": yt_dlp_ver,
        "yt_dlp_ok": yt_dlp_ok,
        "ffmpeg_ok": ffmpeg_ok,
        "ffmpeg": ff_version,
        "yt_reachable": probe("www.youtube.com", 5),
        "ig_reachable": probe("www.instagram.com", 5),
        "tracks_dir": TRACKS_DIR,
    })


@app.get("/api/playlist")
def get_playlist():
    with PLAYLIST_LOCK:
        return jsonify(load_playlist())


@app.post("/api/playlist")
def update_playlist():
    """Body: {"name": "..."} to rename, and/or {"ids": [...]} to reorder."""
    data = request.get_json(silent=True) or {}
    with PLAYLIST_LOCK:
        pl = load_playlist()
        if isinstance(data.get("name"), str) and data["name"].strip():
            pl["name"] = data["name"].strip()[:120]
        if isinstance(data.get("ids"), list):
            order = {tid: i for i, tid in enumerate(data["ids"])}
            tracks = pl["tracks"]
            known = [t for t in tracks if t["id"] in order]
            known.sort(key=lambda t: order[t["id"]])
            dropped = [t for t in tracks if t["id"] not in order]
            pl["tracks"] = known + dropped
        save_playlist(pl)
        return jsonify(pl)


@app.post("/api/playlist/tracks/remove")
def remove_track():
    data = request.get_json(silent=True) or {}
    tid = re.sub(r"[^a-z0-9]", "", str(data.get("id", "")))
    if not tid:
        abort(400)
    with PLAYLIST_LOCK:
        pl = load_playlist()
        before = len(pl["tracks"])
        pl["tracks"] = [t for t in pl["tracks"] if t["id"] != tid]
        if len(pl["tracks"]) == before:
            save_playlist(pl)
            abort(404)
        save_playlist(pl)
    # delete files
    try:
        os.remove(os.path.join(TRACKS_DIR, tid + ".mp3"))
    except OSError:
        pass
    try:
        os.remove(os.path.join(THUMB_DIR, tid + ".jpg"))
    except OSError:
        pass
    return jsonify({"ok": True})


@app.post("/api/add")
def add_track():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not re.match(r"^https?://\S+$", url, re.I):
        return jsonify({"error": "Please paste a valid http(s) URL."}), 400
    job_id = uuid.uuid4().hex
    job_set(job_id, status="pending", stage="queued", progress=0.0)
    t = threading.Thread(target=extract_audio, args=(job_id, url), daemon=True)
    t.start()
    return jsonify({"job_id": job_id})


@app.get("/api/job/<job_id>")
def job_status(job_id):
    job = job_get(job_id)
    if job is None:
        abort(404)
    return jsonify(job)


@app.get("/audio/<path:track_id>.mp3")
def audio_file(track_id):
    safe = re.sub(r"[^a-z0-9]", "", track_id)
    path = os.path.join(TRACKS_DIR, safe + ".mp3")
    if not os.path.isfile(path):
        abort(404)
    file_size = os.path.getsize(path)
    range_header = request.headers.get("Range")
    if not range_header:
        return send_file(path, mimetype="audio/mpeg", conditional=True)
    m = re.match(r"bytes=(\d*)-(\d*)", range_header)
    start, end = 0, file_size - 1
    if m:
        if m.group(1):
            start = int(m.group(1))
        if m.group(2):
            end = min(int(m.group(2)), file_size - 1)
    if start > end or start >= file_size:
        resp = Response(status=416)
        resp.headers["Content-Range"] = "bytes */%d" % file_size
        return resp
    length = end - start + 1
    with open(path, "rb") as fh:
        fh.seek(start)
        data = fh.read(length)
    resp = Response(data, status=206, mimetype="audio/mpeg")
    resp.headers["Content-Range"] = "bytes %d-%d/%d" % (start, end, file_size)
    resp.headers["Accept-Ranges"] = "bytes"
    resp.headers["Content-Length"] = str(length)
    return resp


@app.get("/thumbs/<path:thumb_id>.jpg")
def thumb_file(thumb_id):
    safe = re.sub(r"[^a-z0-9]", "", thumb_id)
    return send_from_directory(THUMB_DIR, safe + ".jpg")


@app.get("/api/cookies")
def cookies_status():
    if not os.path.exists(COOKIES_FILE):
        return jsonify({"present": False, "cookies": 0})
    try:
        with open(COOKIES_FILE, "r", encoding="utf-8") as fh:
            lines = [line for line in fh.read().splitlines()
                     if line.strip() and not line.strip().startswith("#")]
        return jsonify({"present": True, "cookies": len(lines)})
    except OSError:
        return jsonify({"present": False, "cookies": 0})


@app.post("/api/cookies")
def cookies_upload():
    """Accepts multipart file 'cookies' or raw text body (Netscape cookies.txt).
    Stored only in data/ (git-ignored) — never in the repo."""
    raw = None
    f = request.files.get("cookies")
    if f is not None:
        raw = f.read()
    elif request.data:
        raw = request.data
    if not raw:
        return jsonify({"error": "No cookies.txt content received."}), 400
    text = raw.decode("utf-8", errors="ignore")
    lines = [line for line in text.splitlines()
             if line.strip() and not line.strip().startswith("#")]
    if not lines:
        return jsonify({"error": "cookies.txt is empty (no cookie lines found). "
                                 "Export from youtube.com while signed in."}), 400
    with open(COOKIES_FILE, "w", encoding="utf-8") as fh:
        fh.write(text.rstrip() + "\n")
    return jsonify({"ok": True, "cookies": len(lines)})


@app.delete("/api/cookies")
def cookies_delete():
    try:
        os.remove(COOKIES_FILE)
    except OSError:
        pass
    return jsonify({"ok": True})


@app.get("/ai")
def ai_handoff():
    """Hidden handoff page for AI agents (noindex). Renders ai/handoff.md."""
    handoff_path = os.path.join(BASE_DIR, "ai", "handoff.md")
    try:
        with open(handoff_path, "r", encoding="utf-8") as fh:
            content = fh.read()
    except OSError:
        content = "# Handoff file missing (ai/handoff.md)"
    # minimal markdown -> html (headings, bold, lists, code, hr)
    import html as _html
    import re as _re

    def md_to_html(md):
        lines = []
        in_list = False
        for raw in md.splitlines():
            line = raw.rstrip()
            if line.startswith("- ") and not in_list:
                lines.append("<ul>")
                in_list = True
            elif in_list and not line.startswith("- "):
                lines.append("</ul>")
                in_list = False
            if in_list and line.startswith("- "):
                text = _html.escape(line[2:])
                text = _re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
                text = _re.sub(r"`(.+?)`", r"<code>\1</code>", text)
                lines.append("<li>%s</li>" % text)
            elif line.startswith("# "):
                lines.append("<h1>%s</h1>" % _html.escape(line[2:]))
            elif line.startswith("## "):
                lines.append("<h2>%s</h2>" % _html.escape(line[3:]))
            elif line.strip() == "---":
                lines.append("<hr/>")
            elif line.strip():
                text = _html.escape(line)
                text = _re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
                text = _re.sub(r"`(.+?)`", r"<code>\1</code>", text)
                lines.append("<p>%s</p>" % text)
            else:
                if in_list:
                    lines.append("</ul>")
                    in_list = False
                lines.append("")
        if in_list:
            lines.append("</ul>")
        return "\n".join(lines)

    body = md_to_html(content)
    return Response(
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='robots' content='noindex, nofollow'>"
        "<title>Coda — agent handoff</title>"
        "<style>body{font:14px/1.55 Inter,-apple-system,'Segoe UI',Roboto,sans-serif;"
        "color:#202124;background:#f6f8fa;max-width:820px;margin:32px auto;padding:0 20px}"
        "h1{font-size:20px}h2{font-size:16px;margin-top:24px}code{background:#e8eaed;"
        "padding:1px 5px;border-radius:4px;font-family:ui-monospace,Menlo,Consolas,monospace;"
        "font-size:12.5px}ul{padding-left:20px}hr{border:none;border-top:1px solid #dadce0;margin:20px 0}"
        "</style></head><body>" + body + "</body></html>",
        mimetype="text/html",
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print("[coda] starting on http://0.0.0.0:%d" % port, flush=True)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
