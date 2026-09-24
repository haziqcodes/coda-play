# CODA HANDOFF — single source of truth for any AI agent continuing this project.

RULE: after completing ANY task in this repo, update this file (state, log) before
finishing the session. Keep it factual and current.

## Meta
- updated: 2026-09-24
- repo: github.com/haziqcodes/coda-play (remote to be set once key is added)
- branch: main
- live: local http://127.0.0.1:8000 (this workspace); deploy target: Render free plan (not yet connected)
- stack: Python 3 + Flask + yt-dlp + ffmpeg (all free); single-page static frontend (no build step)

## How to work (Coda)
1. Read /home/user/SKILL.md FIRST — user's permanent rules live there (Hinglish replies, premium quality, zero emojis, English-only UI, light theme only, free-only).
2. Read this page (rendered at /ai, hidden, noindex) for project state.
3. After your task: update ai/handoff.md + SKILL.md log, run `make test` + `make lint`, curl-smoke key routes, commit, push.
4. Commit identity: Mohd Haziq <mohdhaziq-work@users.noreply.github.com>. SSH key /home/user/.ssh/id_ed25519 (see /home/user/.ssh/config).
5. ALWAYS check before pushing: remote exists, git identity set, `chmod 600 /home/user/.ssh/id_ed25519` (workspace snapshots can reset perms).

## User rules that apply here
- Replies to user in Hinglish; website content English only.
- NO emojis anywhere on the website — inline SVG icons only (static/index.html + ICONS in static/app.js).
- Light theme ONLY — monochrome + single blue #1a73e8, Inter + JetBrains Mono (static/style.css :root).
- Everything free (pip + Render free). No paid services, no Vercel for this project.
- Verify before claiming done: pytest + flake8 + curl smoke of /, /api/health, /api/playlist, /ai, /audio/<id>.mp3 (range 206), /thumbs/<id>.jpg.
- Personal-use legal policy: no redistribution features, ever.

## Architecture
- server.py — Flask app: POST /api/add (URL -> background job), GET /api/job/<id> (poll), GET/POST /api/playlist (rename/reorder), POST /api/playlist/tracks/remove, GET /audio/<id>.mp3 (range streaming), GET /thumbs/<id>.jpg, GET /ai (this handoff, noindex).
- static/index.html + static/app.js + static/style.css — single page: add-URL card, playlist list (drag & drop reorder), fixed player bar.
- Core playback rule: exactly ONE <audio> element; next track starts only on the `ended` event (no overlap possible). Repeat modes: off / all / one (R key or button).
- data/ (git-ignored): playlist.json, tracks/*.mp3 (192 kbps), thumbs/*.jpg.
- tests/test_api.py — 8 pytest tests against Flask test client (temp data dir via monkeypatch).
- .github/ — CI (flake8 + pytest on Python 3.11/3.12/3.13), Dependabot (pip + actions), issue/PR templates, CONTRIBUTING, CoC.
- Makefile (install/run/test/lint/docker), Dockerfile (python:3.12-slim + apt ffmpeg), docker-compose.yml.

## Current state
- V1 COMPLETE 2026-09-24: full pipeline verified end-to-end in this workspace (URL -> yt-dlp -> ffmpeg mp3 -> playlist -> range streaming 206). Test track: Big Buck Bunny (CC-BY, Blender, 635s), re-verified 2026-09-24 after snapshot reset (id 4c149133711a).
- GIT READY: repo initialized, initial commit 2dbb405 ("v1: Coda — ad-free audio playlist..."), 22 files tracked, remote origin = git@github.com:haziqcodes/coda-play.git. PUSH PENDING: user must (1) add the workspace SSH public key to github.com (fingerprint SHA256:Cd8jYimCr8zLZzaXfGiwk3SVLNfqqEla31mFwNI/Mok, comment coda-workspace-key) and (2) create the empty public repo `coda-play`. Then `git push -u origin main`.

## Log (newest first)
- 2026-09-24 — DEPLOYED: pushed to github.com/haziqcodes/coda-play (new account chosen by user from the suggested names; key "coda-workspace-key" added there, commit author email switched to haziqcodes@users.noreply.github.com). Initial commit d4d0a08 (22 files) live on main. Design polish same day per user order ("single blue not compulsory — labs.google inspiration, match the audio product"): animated 3-bar equalizer (blue, pauses with playback), gradient depth on logo + play button (#1a73e8 → #0b57d0/#1765cc), warm accent #e8710a for the repeat badge; EQ in now-playing rows and player bar (body.paused / playerBar.playing class logic). Verified: pytest 8/8, flake8 clean, emoji-scan clean, curl /, /api/health, /api/playlist, /ai all 200.
- 2026-09-24 — Git ready: git init (main), initial commit 2dbb405 with full v1 (22 files, structured commit message incl. User asked / Contents / Verified), remote origin set to git@github.com:haziqcodes/coda-play.git. Snapshot-reset recovery earlier same day: .github/ + data/tracks + ffmpeg binary were wiped by a workspace snapshot reset and were rebuilt/re-downloaded; pip packages reinstalled; E2E re-verified after recovery (mp3 206 range, thumb 200). LESSON (matches class10 note): ALWAYS re-check remote/identity/ssh-perms/binaries before pushing after any reset.
- 2026-09-24 — Premium restyle + handoff system: light Google-labs theme (#f6f8fa bg, white cards, #1a73e8 accent, Inter/JetBrains Mono), all emojis replaced by inline SVG (play/pause/prev/next/repeat/grip/ext/del/note), hidden /ai handoff endpoint (noindex), ai/handoff.md created, /home/user/SKILL.md rebuilt from class10-learning-hub lib/handoff.ts rules, git identity Mohd Haziq <mohdhaziq-work@users.noreply.github.com> + /home/user/.ssh/config set, SSH key generated (ED25519, fingerprint SHA256:Cd8jYimCr8zLZzaXfGiwk3SVLNfqqEla31mFwNI/Mok). Verified: pytest 8/8, flake8 clean, emoji-scan of static/ empty, curl smoke all green.
- 2026-09-24 — Professional setup: MIT LICENSE, Makefile, Dockerfile + docker-compose, .editorconfig, tests/test_api.py (8 tests), .github CI (3 Python versions), Dependabot, issue/PR templates, CONTRIBUTING, CoC, README with badges.
- 2026-09-24 — v1 core: Flask + yt-dlp + ffmpeg pipeline, playlist API (rename/reorder/remove), single-audio player with repeat off/all/one, drag & drop, range streaming, thumbnails, progress jobs, dark-theme UI (later restyled). End-to-end verified with CC-BY Big Buck Bunny.
