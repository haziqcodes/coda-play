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

# --- YouTube anti-bot configuration (all optional, via env vars) -----------
# YTDLP_PROXY        e.g. socks5://user:pass@host:1080 — residential proxy for
#                    server IPs YouTube has flagged (the only 100% fix there).
# YT_COOKIES_B64     base64 of a Netscape cookies.txt. Written to data/ on
#                    boot so cookies survive Render redeploys (ephemeral disk).
# BGUTIL_SERVER_HOME path of the bgutil PO-token server (Dockerfile installs
#                    it at /opt/bgutil/server). Needs Deno on PATH.
YTDLP_PROXY = os.environ.get("YTDLP_PROXY", "").strip() or None
BGUTIL_SERVER_HOME = os.environ.get("BGUTIL_SERVER_HOME", "/opt/bgutil/server")


def _bootstrap_env_cookies():
    b64 = os.environ.get("YT_COOKIES_B64", "").strip()
    if not b64 or os.path.exists(COOKIES_FILE):
        return
    try:
        import base64
        text = base64.b64decode(b64).decode("utf-8", errors="ignore")
        if text.strip():
            with open(COOKIES_FILE, "w", encoding="utf-8") as fh:
                fh.write(text.rstrip() + "\n")
            print("[coda] cookies loaded from YT_COOKIES_B64", flush=True)
    except Exception as e:  # never block startup on bad env
        print("[coda] YT_COOKIES_B64 invalid:", e, flush=True)


_bootstrap_env_cookies()


def _start_pot_server():
    """Run the bgutil PO-token HTTP server (port 4416) in the background.
    yt-dlp's bgutil plugin tries HTTP first: one warm process with a token
    cache is far faster than spawning Deno per token (script mode), which
    costs ~20-30 s per attempt on Render's small free CPU."""
    deno = shutil.which("deno")
    main_ts = os.path.join(BGUTIL_SERVER_HOME, "src", "main.ts")
    if not deno or not os.path.exists(main_ts) or os.environ.get("CODA_NO_POT_SERVER"):
        return
    try:
        subprocess.Popen([deno, "run", "-A", main_ts], cwd=BGUTIL_SERVER_HOME,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        print("[coda] PO-token server starting on :4416", flush=True)
    except Exception as e:
        print("[coda] PO-token server failed to start:", e, flush=True)


app = Flask(__name__, static_folder=os.path.join(BASE_DIR, "static"), static_url_path="")

JOBS = {}
JOBS_LOCK = threading.Lock()
PLAYLIST_LOCK = threading.Lock()

MP3_QUALITY = "192"  # kbps (only used when re-encoding). Use "320" for max quality.
AUDIO_CODEC = os.environ.get("AUDIO_CODEC", "m4a")  # "mp3" = old behaviour (slower)
AUDIO_EXTS = (".m4a", ".mp3", ".opus", ".webm", ".flac")
MIME = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".opus": "audio/ogg",
        ".webm": "audio/webm", ".flac": "audio/flac"}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


LIB_RE = re.compile(r"^[A-Z0-9]{4,32}$")


def current_library():
    """Library code sent by the browser (X-Coda-Library). Each code has its
    own playlist, so every device/browser keeps its own library unless the
    user links them by entering the same code."""
    try:
        code = (request.headers.get("X-Coda-Library") or "").strip().upper()
    except RuntimeError:  # outside a request
        return None
    return code if LIB_RE.match(code) else None


def playlist_path(lib=None):
    if not lib:
        return PLAYLIST_FILE
    d = os.path.join(DATA_DIR, "libraries")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, lib + ".json")


def load_playlist(lib=None):
    default = {"name": "My Coda Playlist", "tracks": []}
    path = playlist_path(lib)
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict) or not isinstance(data.get("tracks"), list):
            return default
        return data
    except Exception:
        return default


def save_playlist(pl, lib=None):
    path = playlist_path(lib)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(pl, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


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
class ExtractError(Exception):
    pass


def download_one(job_id, url, lib=None, prefix=""):
    """Download + convert ONE video, append it to the library, return the track.
    Raises ExtractError with a user-facing message on failure."""
    import yt_dlp

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
                    stage="%sdownloading audio %d%%%s" % (prefix, int(min(frac, 1.0) * 100), speed_s),
                    track_progress=min(frac, 0.95))
        elif d.get("status") == "finished":
            job_set(job_id, stage="%sfinishing audio..." % prefix, track_progress=0.95)

    def make_opts(cookiefile, player_client):
        opts = {
            "format": "bestaudio[ext=m4a]/bestaudio/best[acodec!=none]/best",
            "outtmpl": template,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [progress_hook],
            "writethumbnail": True,
            "thumbnail_format": "jpg",
            "postprocessors": [
                # m4a source -> stream copy (no re-encode, seconds instead of
                # minutes on a small CPU); other sources -> AAC.
                {"key": "FFmpegExtractAudio", "preferredcodec": AUDIO_CODEC,
                 "preferredquality": MP3_QUALITY},
                {"key": "FFmpegMetadata"},
            ],
            "postprocessor_args": [],
        }
        if cookiefile:
            opts["cookiefile"] = cookiefile
        if YTDLP_PROXY:
            opts["proxy"] = YTDLP_PROXY
        # JS challenge solving (Deno) + remote EJS scripts: required by
        # current YouTube, otherwise only degraded/no formats come back.
        if shutil.which("deno"):
            opts["js_runtimes"] = {"deno": {}}
            opts["remote_components"] = ["ejs:github"]
        ex = {}
        if player_client:
            ex["youtube"] = {"player_client": player_client}
        # PO tokens via bgutil (script mode, no sidecar process needed).
        if os.path.isdir(BGUTIL_SERVER_HOME):
            ex["youtubepot-bgutilscript"] = {"server_home": [BGUTIL_SERVER_HOME]}
        if ex:
            opts["extractor_args"] = ex
        return opts

    # Ladder of extraction configs. Local IPs usually work with the default
    # client (best quality, tried first); datacenter IPs (Render, VPS) get
    # through with cookies and/or non-web clients. The first config that
    # produces a file wins.
    # Each config may list several player clients; yt-dlp falls through the
    # list when a client raises (e.g. the bot-check error). With cookies the
    # cookie configs come first: they work everywhere AND anonymous attempts
    # from datacenter IPs get those IPs flagged by YouTube, which would then
    # break even the cookie path.
    # mweb / web_safari use PO tokens (bgutil) and pass the bot check from
    # most server IPs; tv / android_vr are PO-token-free fallbacks.
    has_cookies = os.path.exists(COOKIES_FILE)
    if has_cookies:
        configs = [
            ("cookies+mweb", COOKIES_FILE, ["mweb", "web_safari"]),
            ("cookies+tv", COOKIES_FILE, ["tv", "web"]),
            ("mweb", None, ["mweb", "web_safari"]),
        ]
    else:
        configs = [
            ("mweb", None, ["mweb", "web_safari"]),
            ("default", None, None),
            ("android_vr", None, ["android_vr", "tv"]),
        ]

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
            job_set(job_id, stage="%s%s failed, retrying…" % (prefix, label))
            continue
        produced = None
        for ext in AUDIO_EXTS:
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
        job_set(job_id, stage="%s%s produced no file, retrying…" % (prefix, label))

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
            msg += (" | YouTube is blocking this server's IP even with PO tokens. "
                    "Fix: set YTDLP_PROXY to a residential proxy, and/or upload a fresh "
                    "cookies.txt in Settings (export it from a PRIVATE/incognito window, "
                    "then close that window so YouTube does not rotate the cookies).")
        print("[coda] extract failed:", msg[:300], flush=True)
        raise ExtractError(msg[:1600])

    # final mp3 name
    ext = os.path.splitext(produced)[1].lower()
    if ext not in AUDIO_EXTS:
        ext = ".m4a"
    final_name = track_id + ext
    final_path = os.path.join(TRACKS_DIR, final_name)
    if os.path.abspath(produced) != os.path.abspath(final_path):
        os.replace(produced, final_path)

    thumb_url = None
    for fn in os.listdir(TRACKS_DIR):
        if fn.startswith(track_id) and fn != final_name:
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
        pl = load_playlist(lib)
        track = {
            "id": track_id,
            "title": title,
            "artist": artist,
            "duration": duration,
            "source_url": info.get("webpage_url") or url,
            "file": final_name,
            "thumbnail": thumb_url,
            "added_at": now_iso(),
        }
        pl["tracks"].append(track)
        save_playlist(pl, lib)

    print("[coda] added: %s (%s, %ss)" % (title, artist, duration), flush=True)
    return track


MAX_PLAYLIST = int(os.environ.get("MAX_PLAYLIST", "100"))


def is_playlist_url(url):
    """YouTube playlist links (…/playlist?list=… or watch?v=…&list=…).
    Auto-generated mixes (list=RD…) are endless, so they stay single-video."""
    m = re.search(r"[?&]list=([A-Za-z0-9_-]+)", url)
    return bool(m) and not m.group(1).startswith("RD")


def list_playlist(url):
    """Flat-list playlist entries without downloading anything (fast)."""
    import yt_dlp
    m = re.search(r"[?&]list=([A-Za-z0-9_-]+)", url)
    purl = "https://www.youtube.com/playlist?list=" + m.group(1)
    opts = {"extract_flat": "in_playlist", "quiet": True, "no_warnings": True,
            "playlistend": MAX_PLAYLIST}
    if os.path.exists(COOKIES_FILE):
        opts["cookiefile"] = COOKIES_FILE
    if YTDLP_PROXY:
        opts["proxy"] = YTDLP_PROXY
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(purl, download=False) or {}
    urls = []
    for e in info.get("entries") or []:
        if not e or e.get("title") in ("[Private video]", "[Deleted video]"):
            continue
        vid = e.get("id")
        if vid:
            urls.append("https://www.youtube.com/watch?v=" + vid)
    return info.get("title") or "Playlist", urls


def extract_audio(job_id, url, lib=None):
    try:
        import yt_dlp  # noqa: F401
    except Exception as e:
        job_set(job_id, status="error", stage="error",
                error="yt-dlp is not installed. Run: pip install -r requirements.txt (%s)" % e)
        return
    if shutil.which("ffmpeg") is None:
        job_set(job_id, status="error", stage="error",
                error="ffmpeg not found on PATH. Install ffmpeg (see README).")
        return

    if not is_playlist_url(url):
        try:
            track = download_one(job_id, url, lib)
        except ExtractError as e:
            job_set(job_id, status="error", stage="error", error=str(e))
            return
        except Exception as e:
            job_set(job_id, status="error", stage="error", error=str(e)[:600])
            return
        job_set(job_id, status="done", stage="done", progress=1.0, track=track, added=1, total=1)
        return

    # ---- playlist: list entries first, then download one by one --------------
    job_set(job_id, status="downloading", stage="reading playlist…", kind="playlist")
    try:
        ptitle, urls = list_playlist(url)
    except Exception as e:
        job_set(job_id, status="error", stage="error", error="Could not read playlist: %s" % str(e)[:400])
        return
    if not urls:
        job_set(job_id, status="error", stage="error", error="Playlist is empty or private.")
        return
    total, added, failed, last = len(urls), 0, [], None
    job_set(job_id, total=total, added=0, failed=0, playlist_title=ptitle)
    for i, vurl in enumerate(urls):
        if (job_get(job_id) or {}).get("cancel"):
            break
        prefix = "Track %d/%d · " % (i + 1, total)
        job_set(job_id, stage=prefix + "starting…", current=i + 1, track_progress=0.0)
        try:
            last = download_one(job_id, vurl, lib, prefix)
            added += 1
        except Exception as e:
            failed.append("%s: %s" % (vurl, str(e)[:300]))
        job_set(job_id, added=added, failed=len(failed), progress=(i + 1) / total,
                failures=failed[-10:])
    if added == 0:
        job_set(job_id, status="error", stage="error",
                error="No track from the playlist could be added. " + " | ".join(failed[:2]))
        return
    job_set(job_id, status="done", stage="done", progress=1.0, track=last,
            added=added, total=total, failures=failed[:10])


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
        "deno": bool(shutil.which("deno")),
        "po_token_provider": os.path.isdir(BGUTIL_SERVER_HOME),
        "proxy": bool(YTDLP_PROXY),
        "cookies": os.path.exists(COOKIES_FILE),
    })


@app.get("/api/playlist")
def get_playlist():
    with PLAYLIST_LOCK:
        return jsonify(load_playlist(current_library()))


@app.post("/api/playlist")
def update_playlist():
    """Body: {"name": "..."} to rename, and/or {"ids": [...]} to reorder."""
    data = request.get_json(silent=True) or {}
    lib = current_library()
    with PLAYLIST_LOCK:
        pl = load_playlist(lib)
        if isinstance(data.get("name"), str) and data["name"].strip():
            pl["name"] = data["name"].strip()[:120]
        if isinstance(data.get("ids"), list):
            order = {tid: i for i, tid in enumerate(data["ids"])}
            tracks = pl["tracks"]
            known = [t for t in tracks if t["id"] in order]
            known.sort(key=lambda t: order[t["id"]])
            dropped = [t for t in tracks if t["id"] not in order]
            pl["tracks"] = known + dropped
        save_playlist(pl, lib)
        return jsonify(pl)


@app.post("/api/playlist/tracks/remove")
def remove_track():
    data = request.get_json(silent=True) or {}
    tid = re.sub(r"[^a-z0-9]", "", str(data.get("id", "")))
    if not tid:
        abort(400)
    lib = current_library()
    with PLAYLIST_LOCK:
        pl = load_playlist(lib)
        before = len(pl["tracks"])
        pl["tracks"] = [t for t in pl["tracks"] if t["id"] != tid]
        if len(pl["tracks"]) == before:
            abort(404)
        save_playlist(pl, lib)
    # delete files
    for ext in AUDIO_EXTS:
        try:
            os.remove(os.path.join(TRACKS_DIR, tid + ext))
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
    t = threading.Thread(target=extract_audio, args=(job_id, url, current_library()), daemon=True)
    t.start()
    return jsonify({"job_id": job_id})


@app.post("/api/job/<job_id>/cancel")
def job_cancel(job_id):
    """Stop a playlist import after the current track finishes."""
    if job_get(job_id) is None:
        abort(404)
    job_set(job_id, cancel=True, stage="stopping after this track…")
    return jsonify({"ok": True})


@app.get("/api/job/<job_id>")
def job_status(job_id):
    job = job_get(job_id)
    if job is None:
        abort(404)
    return jsonify(job)


@app.get("/audio/<track_id>.<ext>")
def audio_file(track_id, ext):
    safe = re.sub(r"[^a-z0-9]", "", track_id)
    ext = "." + re.sub(r"[^a-z0-9]", "", ext.lower())
    if ext not in AUDIO_EXTS:
        abort(404)
    path = os.path.join(TRACKS_DIR, safe + ext)
    if not os.path.isfile(path):
        abort(404)
    mime = MIME.get(ext, "application/octet-stream")
    file_size = os.path.getsize(path)
    range_header = request.headers.get("Range")
    if not range_header:
        return send_file(path, mimetype=mime, conditional=True)
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
    resp = Response(data, status=206, mimetype=mime)
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
                     if line.strip() and (not line.strip().startswith("#") or line.startswith("#HttpOnly_"))]
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
             if line.strip() and (not line.strip().startswith("#") or line.startswith("#HttpOnly_"))]
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
    _start_pot_server()
    port = int(os.environ.get("PORT", "8000"))
    print("[coda] starting on http://0.0.0.0:%d" % port, flush=True)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
