/* Coda — frontend logic.
   Core playback rule: there is exactly ONE <audio> element, so the next
   song can ONLY start after the current one has fully ended (no overlap,
   no "background video keeps playing" behaviour). */

"use strict";

const state = {
  playlist: { name: "My Coda Playlist", tracks: [] },
  currentIndex: -1,
  repeat: "off", // off | all | one
  isPlaying: false,
  dragIndex: null,
};

// ---- library code: each browser has its own library unless linked ---------
const LIB_KEY = "coda.library";
function newLibraryCode() {
  const abc = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"; // no 0/O/1/I confusion
  const buf = new Uint32Array(8);
  crypto.getRandomValues(buf);
  return [...buf].map((n) => abc[n % abc.length]).join("");
}
let libraryCode = localStorage.getItem(LIB_KEY);
if (!/^[A-Z0-9]{4,32}$/.test(libraryCode || "")) {
  libraryCode = newLibraryCode();
  localStorage.setItem(LIB_KEY, libraryCode);
}
// every API call carries the library code
function api(path, opts = {}) {
  const headers = Object.assign({}, opts.headers || {}, { "X-Coda-Library": libraryCode });
  return fetch(path, Object.assign({}, opts, { headers }));
}

// ---- on-device storage ---------------------------------------------------------
// Render free wipes the server disk on every restart, so each browser keeps
// (1) a copy of its library in localStorage and (2) the audio + cover files in
// IndexedDB. Songs play from the device first; the server is only a helper.
const idb = (() => {
  let dbp = null;
  const open = () => dbp || (dbp = new Promise((res, rej) => {
    const r = indexedDB.open("coda", 1);
    r.onupgradeneeded = () => r.result.createObjectStore("files");
    r.onsuccess = () => res(r.result);
    r.onerror = () => rej(r.error);
  }));
  const run = async (mode, fn) => {
    const db = await open();
    return new Promise((res, rej) => {
      const tx = db.transaction("files", mode);
      const req = fn(tx.objectStore("files"));
      tx.oncomplete = () => res(req && req.result);
      tx.onerror = () => rej(tx.error);
    });
  };
  return {
    get: (k) => run("readonly", (s) => s.get(k)).catch(() => undefined),
    put: (k, v) => run("readwrite", (s) => s.put(v, k)).catch(() => undefined),
    del: (k) => run("readwrite", (s) => s.delete(k)).catch(() => undefined),
  };
})();
if (navigator.storage && navigator.storage.persist) navigator.storage.persist().catch(() => {});

const localKey = () => "coda.pl." + libraryCode;
function saveLocal() {
  try { localStorage.setItem(localKey(), JSON.stringify({ name: state.playlist.name, tracks: state.playlist.tracks })); } catch {}
}
function loadLocal() {
  try { return JSON.parse(localStorage.getItem(localKey()) || "null"); } catch { return null; }
}

const caching = new Set();
async function cacheTrack(t) {
  if (!t || !t.id || caching.has(t.id)) return;
  caching.add(t.id);
  try {
    if (!(await idb.get("a:" + t.id))) {
      const r = await fetch(`/audio/${t.file || t.id + ".mp3"}`);
      if (r.ok) await idb.put("a:" + t.id, await r.blob());
    }
    if (t.thumbnail && !(await idb.get("t:" + t.id))) {
      const r = await fetch(t.thumbnail);
      if (r.ok) await idb.put("t:" + t.id, await r.blob());
    }
  } catch {} finally { caching.delete(t.id); }
  markCached();
}
async function markCached() {
  for (const li of els.trackList.querySelectorAll(".track")) {
    const has = !!(await idb.get("a:" + li.dataset.id));
    li.classList.toggle("on-device", has);
  }
}
// cover image fell back (server lost it) -> use the device copy
async function thumbFallback(img, id) {
  img.onerror = null;
  const b = await idb.get("t:" + id);
  if (b) img.src = URL.createObjectURL(b);
  else img.replaceWith(Object.assign(document.createElement("div"), { className: "t-thumb t-thumb-fallback", innerHTML: ICONS.note }));
}
window.thumbFallback = thumbFallback;

const audio = new Audio(); // single player — guarantees one song at a time
audio.preload = "auto";

// ---- element refs -------------------------------------------------------
const $ = (id) => document.getElementById(id);
const els = {
  urlInput: $("urlInput"),
  addBtn: $("addBtn"),
  progressWrap: $("progressWrap"),
  progressStage: $("progressStage"),
  progressErr: $("progressErr"),
  progressFill: $("progressFill"),
  playlistName: $("playlistName"),
  playlistStats: $("playlistStats"),
  trackList: $("trackList"),
  emptyState: $("emptyState"),
  pbThumb: $("pbThumb"),
  pbThumbImg: $("pbThumbImg"),
  pbThumbFallback: $("pbThumbFallback"),
  pbTitle: $("pbTitle"),
  pbArtist: $("pbArtist"),
  playBtn: $("playBtn"),
  prevBtn: $("prevBtn"),
  nextBtn: $("nextBtn"),
  curTime: $("curTime"),
  durTime: $("durTime"),
  seekBar: $("seekBar"),
  seekFill: $("seekFill"),
  volSlider: $("volSlider"),
  repeatBtn: $("repeatBtn"),
  repeatBadge: $("repeatBadge"),
  toast: $("toast"),
  healthDot: $("healthDot"),
  playerBar: $("playerBar"),
  cookieFile: $("cookieFile"),
  cookieUploadBtn: $("cookieUploadBtn"),
  cookieClearBtn: $("cookieClearBtn"),
  cookieStatus: $("cookieStatus"),
};

audio.volume = parseFloat(els.volSlider.value);

// ---- small utils ---------------------------------------------------------
function fmtTime(s) {
  if (s === null || s === undefined || isNaN(s)) return "-:--";
  s = Math.max(0, Math.floor(s));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const mm = h ? String(m).padStart(2, "0") : String(m);
  return (h ? h + ":" : "") + mm + ":" + String(sec).padStart(2, "0");
}

let toastTimer = null;
function toast(msg, isErr) {
  els.toast.textContent = msg;
  els.toast.classList.remove("hidden");
  els.toast.classList.toggle("err", !!isErr);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => els.toast.classList.add("hidden"), 4500);
}

const ICONS = {
  play: '<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>',
  pause: '<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" aria-hidden="true"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>',
  note: '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" aria-hidden="true"><path d="M12 3v10.55A3.5 3.5 0 1 0 14 17.5V7h4V3h-6z"/></svg>',
  grip: '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" aria-hidden="true"><path d="M9 5h2v2H9zM9 11h2v2H9zm0 6h2v2H9zm5-12h2v2h-2zm0 6h2v2h-2zm0 6h2v2h-2z"/></svg>',
  ext: '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" aria-hidden="true"><path d="M14 3h7v7h-2V6.4l-9.3 9.3-1.4-1.4L17.6 5H14V3zM5 5h6v2H7v10h10v-4h2v6H5V5z"/></svg>',
  del: '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" aria-hidden="true"><path d="M19 6.4 17.6 5 12 10.6 6.4 5 5 6.4 10.6 12 5 17.6 6.4 19 12 13.4 17.6 19 19 17.6 13.4 12z"/></svg>',
};

// ---- playlist rendering ---------------------------------------------------
function renderPlaylist() {
  saveLocal();
  setTimeout(markCached, 0);
  const tracks = state.playlist.tracks;
  els.playlistName.value = state.playlist.name;
  const total = tracks.reduce((a, t) => a + (Number(t.duration) || 0), 0);
  els.playlistStats.textContent = `${tracks.length} track${tracks.length === 1 ? "" : "s"} · ${fmtTime(total)}`;
  els.emptyState.style.display = tracks.length ? "none" : "";

  els.trackList.innerHTML = "";
  tracks.forEach((t, i) => {
    const li = document.createElement("li");
    li.className = "track";
    li.draggable = true;
    li.dataset.id = t.id;
    li.dataset.index = i;
    if (i === state.currentIndex) li.classList.add("now-playing");

    const thumb = t.thumbnail
      ? `<img class="t-thumb" src="${t.thumbnail}" alt="" loading="lazy" onerror="thumbFallback(this, '${t.id}')" />`
      : `<div class="t-thumb t-thumb-fallback">${ICONS.note}</div>`;

    const dur = fmtTime(t.duration);
    const artist = t.artist ? `<div class="t-artist">${escapeHtml(t.artist)}</div>` : "";

    li.innerHTML = `
      <div class="t-drag" title="Drag to reorder">${ICONS.grip}</div>
      ${thumb}
      <div class="t-main">
        <div class="t-title-row">
          <span class="eq" aria-hidden="true"><i></i><i></i><i></i></span>
          <span class="t-title">${escapeHtml(t.title)}</span>
        </div>
        ${artist}
      </div>
      <div class="t-dur">${dur}</div>
      <a class="t-src" href="${escapeHtml(t.source_url || "")}" target="_blank" rel="noopener" title="Open source video">${ICONS.ext}</a>
      <button class="t-del" title="Remove from playlist">${ICONS.del}</button>`;

    li.addEventListener("click", (e) => {
      if (e.target.closest(".t-del") || e.target.closest(".t-src") || e.target.closest(".t-drag")) return;
      playIndex(i);
    });
    li.querySelector(".t-del").addEventListener("click", (e) => {
      e.stopPropagation();
      removeTrack(t.id, i);
    });

    // drag & drop reorder
    li.addEventListener("dragstart", () => { state.dragIndex = i; li.classList.add("dragging"); });
    li.addEventListener("dragend", () => { li.classList.remove("dragging"); state.dragIndex = null; });
    li.addEventListener("dragover", (e) => { e.preventDefault(); });
    li.addEventListener("drop", (e) => { e.preventDefault(); });
    els.trackList.addEventListener("dragover", (e) => {
      e.preventDefault();
      const after = getDragAfterElement(els.trackList, e.clientY);
      const moving = els.trackList.querySelector(".dragging");
      if (!moving) return;
      if (after == null) els.trackList.appendChild(moving);
      else els.trackList.insertBefore(moving, after);
    });
    els.trackList.addEventListener("drop", () => persistOrder());

    els.trackList.appendChild(li);
  });
}

function getDragAfterElement(container, y) {
  const items = [...container.querySelectorAll(".track:not(.dragging)")];
  return items.reduce((closest, child) => {
    const box = child.getBoundingClientRect();
    const offset = y - box.top - box.height / 2;
    if (offset < 0 && offset > closest.offset) return { offset, element: child };
    return closest;
  }, { offset: -Infinity, element: null }).element;
}

function persistOrder() {
  const ids = [...els.trackList.querySelectorAll(".track")].map((li) => li.dataset.id);
  state.playlist.tracks = ids
    .map((id) => state.playlist.tracks.find((t) => t.id === id))
    .filter(Boolean);
  api("/api/playlist", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids }),
  }).catch(() => toast("Could not save order.", true));
  renderPlaylist();
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ---- player ----------------------------------------------------------------
let blobUrl = null;
let playToken = 0;
async function playIndex(i) {
  const tracks = state.playlist.tracks;
  if (!tracks.length || i < 0 || i >= tracks.length) return;
  state.currentIndex = i;
  const t = tracks[i];
  const token = ++playToken;
  updatePlayerUi();
  renderPlaylist();
  const blob = await idb.get("a:" + t.id);
  if (token !== playToken) return; // user tapped another song meanwhile
  if (blobUrl) { URL.revokeObjectURL(blobUrl); blobUrl = null; }
  if (blob) {
    blobUrl = URL.createObjectURL(blob);
    audio.src = blobUrl;
  } else {
    audio.src = `/audio/${t.file || t.id + ".mp3"}`;
    cacheTrack(t);
  }
  audio.play().catch((e) => { if (e.name !== "AbortError" && e.name !== "NotSupportedError") toast("Play failed: " + e.message, true); });
}

// The server lost the file (restart wiped its disk) and this device has no copy:
// download it again under the same id, then play.
const refetching = new Set();
async function refetchAndPlay(i) {
  const t = state.playlist.tracks[i];
  if (!t || !t.source_url || refetching.has(t.id)) return;
  refetching.add(t.id);
  toast("Server lost this song — fetching it again (about 30 s)…");
  try {
    const job = await runJob({ url: t.source_url, track_id: t.id, single: true }, (st) => setBusy(true, st));
    setBusy(false);
    if (job.track) Object.assign(t, job.track);
    await cacheTrack(t);
    if (state.currentIndex === i) playIndex(i);
  } catch (e) {
    setBusy(false);
    toast("Could not fetch this song again: " + e.message, true);
  } finally { refetching.delete(t.id); }
}

function togglePlay() {
  if (!state.playlist.tracks.length) {
    toast("Playlist is empty — add a song first.");
    return;
  }
  if (state.currentIndex === -1) { playIndex(0); return; }
  if (audio.paused) audio.play().catch(() => {});
  else audio.pause();
  updatePlayerUi();
}

function nextFromEnded() {
  // called ONLY when the current song has fully ended
  const n = state.playlist.tracks.length;
  if (!n) return;
  if (state.repeat === "one") {
    audio.currentTime = 0;
    audio.play().catch(() => {});
    return;
  }
  const next = state.currentIndex + 1;
  if (next < n) { playIndex(next); return; }
  // reached the end
  if (state.repeat === "all") { playIndex(0); return; }
  // repeat off -> stop, playlist finished
  state.isPlaying = false;
  updatePlayerUi();
  renderPlaylist();
  toast("Playlist finished.");
}

function prevTrack() {
  const n = state.playlist.tracks.length;
  if (!n) return;
  if (audio.currentTime > 3 || state.currentIndex === 0) {
    audio.currentTime = 0;
  } else {
    playIndex(state.currentIndex - 1);
  }
  updatePlayerUi();
}

function cycleRepeat() {
  const order = ["off", "all", "one"];
  state.repeat = order[(order.indexOf(state.repeat) + 1) % 3];
  updateRepeatUi();
}

function updateRepeatUi() {
  const label = { off: "Repeat off — stops when playlist ends", all: "Repeat all — loops the whole playlist", one: "Repeat one — loops current song" };
  els.repeatBtn.title = label[state.repeat];
  els.repeatBtn.className = "pb-icon-btn repeat-" + state.repeat;
  els.repeatBadge.textContent = state.repeat === "one" ? "1" : state.repeat === "all" ? "" : "";
  els.repeatBadge.classList.toggle("show", state.repeat === "one");
}

function updatePlayerUi() {
  const t = state.playlist.tracks[state.currentIndex];
  els.pbTitle.textContent = t ? t.title : "Nothing playing";
  els.pbArtist.textContent = t ? (t.artist || "—") : "—";
  const hasThumb = !!(t && t.thumbnail);
  els.pbThumb.hidden = !t;
  if (hasThumb) {
    // device copy first (server may have lost the cover after a restart)
    const id = t.id;
    idb.get("t:" + id).then((blob) => {
      if (state.playlist.tracks[state.currentIndex] !== t) return;
      els.pbThumbImg.src = blob ? URL.createObjectURL(blob) : t.thumbnail;
    });
  } else {
    els.pbThumbImg.removeAttribute("src");
  }
  els.pbThumbImg.style.display = hasThumb ? "" : "none";
  if (els.pbThumbFallback) els.pbThumbFallback.style.display = hasThumb ? "none" : "";
  els.playBtn.innerHTML = !audio.paused ? ICONS.pause : ICONS.play;
  document.body.classList.toggle("paused", audio.paused);
  els.playerBar.classList.toggle("playing", !audio.paused && state.currentIndex >= 0);
}

// audio events — 'ended' is the ONLY thing that starts the next song
audio.addEventListener("ended", nextFromEnded);
audio.addEventListener("play", () => { state.isPlaying = true; updatePlayerUi(); });
audio.addEventListener("pause", () => { state.isPlaying = false; updatePlayerUi(); });
audio.addEventListener("timeupdate", () => {
  if (audio.duration) {
    els.seekFill.style.width = (audio.currentTime / audio.duration) * 100 + "%";
    els.curTime.textContent = fmtTime(audio.currentTime);
    els.durTime.textContent = fmtTime(audio.duration);
  }
});
audio.addEventListener("loadedmetadata", () => {
  els.durTime.textContent = fmtTime(audio.duration);
  // if backend duration was missing, cache it
  const t = state.playlist.tracks[state.currentIndex];
  if (t && !t.duration && audio.duration) t.duration = Math.round(audio.duration);
});
audio.addEventListener("error", () => {
  if (!audio.src || state.currentIndex === -1) return;
  state.isPlaying = false;
  updatePlayerUi();
  if (!audio.src.startsWith("blob:")) refetchAndPlay(state.currentIndex);
  else toast("Could not play this track.", true);
});

// seek
let seeking = false;
els.seekBar.addEventListener("mousedown", () => (seeking = true));
window.addEventListener("mouseup", () => (seeking = false));
els.seekBar.addEventListener("click", (e) => {
  if (!audio.duration) return;
  const r = els.seekBar.getBoundingClientRect();
  audio.currentTime = ((e.clientX - r.left) / r.width) * audio.duration;
});
els.volSlider.addEventListener("input", () => (audio.volume = parseFloat(els.volSlider.value)));
els.playBtn.addEventListener("click", togglePlay);
els.nextBtn.addEventListener("click", () => {
  const n = state.playlist.tracks.length;
  if (state.currentIndex + 1 < n) playIndex(state.currentIndex + 1);
  else if (state.repeat === "all" && n) playIndex(0);
  else toast("Last track.");
});
els.prevBtn.addEventListener("click", prevTrack);
els.repeatBtn.addEventListener("click", cycleRepeat);

// keyboard shortcuts
window.addEventListener("keydown", (e) => {
  if (["INPUT", "TEXTAREA"].includes(document.activeElement.tagName)) return;
  if (e.code === "Space") { e.preventDefault(); togglePlay(); }
  if (e.code === "ArrowRight" && e.ctrlKey) { e.preventDefault(); els.nextBtn.click(); }
  if (e.code === "ArrowLeft" && e.ctrlKey) { e.preventDefault(); prevTrack(); }
  if (e.key === "r" || e.key === "R") cycleRepeat();
});

// ---- add track (url -> job -> poll) ------------------------------------------
let pollTimer = null;
let currentJob = null;
const stopBtn = $("stopBtn");

let stopRequested = false;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// POST /api/add then poll until done. Survives server cold starts; rejects
// with "restart" if the server rebooted mid-job (job id unknown).
async function runJob(body, onStage) {
  let res, data;
  for (let a = 0; ; a++) {
    try {
      res = await api("/api/add", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      data = await res.json();
      break;
    } catch (e) {
      if (a >= 5) throw new Error("server unreachable");
      onStage && onStage("server waking up…");
      await sleep(5000);
    }
  }
  if (!res.ok) throw new Error(data.error || "server rejected the URL");
  const jobId = data.job_id;
  currentJob = jobId;
  let misses = 0;
  for (;;) {
    await sleep(1200);
    let job;
    try {
      const r = await api("/api/job/" + jobId);
      if (r.status === 404) throw Object.assign(new Error("restart"), { restart: true });
      job = await r.json();
      misses = 0;
    } catch (e) {
      if (e.restart) throw e;
      if (++misses > 40) throw new Error("server unreachable");
      onStage && onStage("server busy, reconnecting…");
      await sleep(2000);
      continue;
    }
    if (job.status === "done") return job;
    if (job.status === "error") throw new Error(job.error || "Extraction failed.");
    onStage && onStage(job.stage || job.status, job.track_progress || 0);
  }
}

stopBtn.addEventListener("click", () => {
  stopRequested = true;
  stopBtn.disabled = true;
  els.progressStage.textContent = "stopping after this song…";
});

async function addTrack() {
  const url = els.urlInput.value.trim();
  if (!url) { toast("Paste a video URL first.", true); return; }
  if (!/^https?:\/\//i.test(url)) { toast("URL must start with http:// or https://", true); return; }

  setBusy(true, "contacting server…");
  let list = null;
  if (/[?&]list=/.test(url)) {
    try {
      const r = await api("/api/list?url=" + encodeURIComponent(url));
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || "could not read playlist");
      if (d.playlist) list = d;
    } catch (e) { setBusy(false); toast(e.message, true); return; }
  }
  els.urlInput.value = "";

  if (!list) {
    try {
      const job = await runJob({ url }, (st, p) => { setBusy(true, st); els.progressFill.style.width = (p || 0) * 100 + "%"; });
      setBusy(false);
      toast(`Added: ${job.track.title}`);
      await refreshPlaylist();
      cacheTrack(job.track);
    } catch (e) {
      setBusy(false);
      toast(e.restart ? "Server restarted during download — please add it again." : e.message, true);
    }
    return;
  }

  // playlist: the browser drives the import one song at a time
  const items = list.items, total = items.length;
  let added = 0, failed = 0;
  stopRequested = false;
  stopBtn.classList.remove("hidden");
  for (let i = 0; i < total && !stopRequested; i++) {
    const pre = `Song ${i + 1}/${total} · `;
    let ok = false;
    for (let attempt = 0; attempt < 3 && !ok; attempt++) {
      try {
        const job = await runJob({ url: items[i].url, single: true }, (st, p) => {
          setBusy(true, pre + String(st).replace(/^Track \d+\/\d+ · /, ""));
          els.progressFill.style.width = ((i + (p || 0)) / total) * 100 + "%";
          stopBtn.classList.remove("hidden");
        });
        ok = true;
        added++;
        await refreshPlaylist();
        await cacheTrack(job.track);
      } catch (e) {
        if (!e.restart && attempt >= 1) break; // real error (private/removed video) -> skip
        setBusy(true, pre + "server restarted, retrying…");
        await sleep(4000);
      }
    }
    if (!ok) failed++;
  }
  setBusy(false);
  toast(stopRequested
    ? `Stopped — ${added} of ${total} songs added`
    : `Playlist added: ${added} of ${total} songs` + (failed ? ` (${failed} unavailable)` : ""));
}

function setBusy(on, stage) {
  els.progressWrap.classList.toggle("hidden", !on);
  els.addBtn.disabled = on;
  els.addBtn.querySelector("span").textContent = on ? "Working…" : "Add";
  if (stage) els.progressStage.textContent = stage;
  if (!on) {
    stopBtn.classList.add("hidden");
    stopBtn.disabled = false;
    els.progressErr.textContent = "";
    setTimeout(() => (els.progressFill.style.width = "0%"), 400);
  }
}

// ---- playlist data -------------------------------------------------------------
async function refreshPlaylist() {
  const local = loadLocal();
  try {
    const res = await api("/api/playlist");
    let pl = await res.json();
    const bootKey = "coda.boot." + libraryCode;
    // server restarted since we last synced -> push our copy back (merge)
    if (local && local.tracks && local.tracks.length && pl.boot !== localStorage.getItem(bootKey)) {
      const have = new Set(pl.tracks.map((t) => t.id));
      if (local.tracks.some((t) => !have.has(t.id))) {
        const r = await api("/api/playlist/restore", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(local),
        });
        if (r.ok) pl = await r.json();
      }
    }
    if (pl.boot) localStorage.setItem(bootKey, pl.boot);
    state.playlist = { name: pl.name, tracks: pl.tracks };
  } catch (e) {
    if (local) state.playlist = local; // offline: play from the device
  }
  renderPlaylist();
}

els.addBtn.addEventListener("click", addTrack);
els.urlInput.addEventListener("keydown", (e) => { if (e.key === "Enter") addTrack(); });
let nameTimer = null;
els.playlistName.addEventListener("change", async () => {
  clearTimeout(nameTimer);
  nameTimer = setTimeout(async () => {
    try {
      const res = await api("/api/playlist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: els.playlistName.value }),
      });
      state.playlist = await res.json();
      renderPlaylist();
    } catch (e) { toast("Could not rename playlist.", true); }
  }, 300);
});

async function removeTrack(id, index) {
  try {
    const res = await api("/api/playlist/tracks/remove", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
    if (!res.ok) throw new Error();
  } catch {
    toast("Could not remove track.", true);
    return;
  }
  state.playlist.tracks.splice(index, 1);
  idb.del("a:" + id);
  idb.del("t:" + id);
  // fix current index
  if (index < state.currentIndex) state.currentIndex -= 1;
  if (index === state.currentIndex) {
    audio.pause();
    audio.removeAttribute("src");
    audio.load();
    state.currentIndex = -1;
    updatePlayerUi();
  }
  renderPlaylist();
}

// ---- YouTube cookies -------------------------------------------------------
async function refreshCookieStatus() {
  try {
    const res = await fetch("/api/cookies");
    const c = await res.json();
    els.cookieStatus.textContent = c.present
      ? "Active — " + c.cookies + " cookies uploaded."
      : "No cookies uploaded.";
  } catch {
    els.cookieStatus.textContent = "Status unavailable.";
  }
}

els.cookieUploadBtn.addEventListener("click", async () => {
  const f = els.cookieFile.files[0];
  if (!f) { toast("Choose a cookies.txt file first.", true); return; }
  const fd = new FormData();
  fd.append("cookies", f);
  try {
    const res = await fetch("/api/cookies", { method: "POST", body: fd });
    const d = await res.json();
    if (!res.ok) throw new Error(d.error || "Upload failed");
    toast("Cookies uploaded (" + d.cookies + ").");
    els.cookieFile.value = "";
    await refreshCookieStatus();
  } catch (e) {
    toast(e.message, true);
  }
});

els.cookieClearBtn.addEventListener("click", async () => {
  try {
    await fetch("/api/cookies", { method: "DELETE" });
    toast("Cookies removed.");
  } catch {
    toast("Could not remove cookies.", true);
  }
  await refreshCookieStatus();
});

// ---- health --------------------------------------------------------------------
async function checkHealth() {
  try {
    const res = await fetch("/api/health");
    const h = await res.json();
    const ok = h.yt_dlp_ok && h.ffmpeg_ok;
    els.healthDot.className = "health-dot " + (ok ? "ok" : "warn");
    els.healthDot.title = ok
      ? "All systems go (yt-dlp and ffmpeg ready)"
      : `Server check — yt-dlp: ${h.yt_dlp_ok ? "ok" : "missing"}, ffmpeg: ${h.ffmpeg_ok ? "ok" : "missing"}, YouTube: ${h.yt_reachable ? "reachable" : "unreachable"}`;
  } catch {
    els.healthDot.className = "health-dot err";
    els.healthDot.title = "Cannot reach server";
  }
}

// ---- library code UI -----------------------------------------------------------
const libEl = { code: $("libCode"), input: $("libInput"), use: $("libUseBtn"), fresh: $("libNewBtn"), copy: $("libCopyBtn") };
function switchLibrary(code) {
  libraryCode = code;
  localStorage.setItem(LIB_KEY, code);
  libEl.code.textContent = code;
  audio.pause();
  state.currentIndex = -1;
  updatePlayerUi();
  refreshPlaylist();
}
libEl.code.textContent = libraryCode;
libEl.use.addEventListener("click", () => {
  const code = libEl.input.value.trim().toUpperCase().replace(/[^A-Z0-9]/g, "");
  if (!/^[A-Z0-9]{4,32}$/.test(code)) { toast("Enter a valid library code (4-32 letters/numbers).", true); return; }
  libEl.input.value = "";
  switchLibrary(code);
  toast("Library switched.");
});
libEl.fresh.addEventListener("click", () => {
  if (!confirm("Start a new empty library? Keep your current code if you want to come back to it: " + libraryCode)) return;
  switchLibrary(newLibraryCode());
  toast("New library created.");
});
libEl.copy.addEventListener("click", async () => {
  try { await navigator.clipboard.writeText(libraryCode); toast("Code copied."); }
  catch { toast("Copy failed — note the code manually.", true); }
});

// ---- init ------------------------------------------------------------------------
refreshPlaylist();
checkHealth();
refreshCookieStatus();
updateRepeatUi();
