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
      ? `<img class="t-thumb" src="${t.thumbnail}" alt="" loading="lazy" />`
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
  fetch("/api/playlist", {
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
function playIndex(i) {
  const tracks = state.playlist.tracks;
  if (!tracks.length || i < 0 || i >= tracks.length) return;
  state.currentIndex = i;
  const t = tracks[i];
  audio.src = `/audio/${t.id}.mp3`;
  audio.play().catch((e) => toast("Play failed: " + e.message, true));
  updatePlayerUi();
  renderPlaylist();
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
  els.pbThumbImg.src = hasThumb ? t.thumbnail : "";
  els.pbThumbImg.style.display = hasThumb ? "" : "none";
  els.pbThumbFallback.style.display = hasThumb ? "none" : "";
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
  toast("Could not play this track (file missing?).", true);
  state.isPlaying = false;
  updatePlayerUi();
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
async function addTrack() {
  const url = els.urlInput.value.trim();
  if (!url) { toast("Paste a video URL first.", true); return; }
  if (!/^https?:\/\//i.test(url)) { toast("URL must start with http:// or https://", true); return; }

  setBusy(true, "contacting server…");
  try {
    const res = await fetch("/api/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "server rejected the URL");
    els.urlInput.value = "";
    pollJob(data.job_id);
  } catch (e) {
    setBusy(false);
    toast(e.message, true);
  }
}

function pollJob(jobId) {
  clearTimeout(pollTimer);
  const tick = async () => {
    try {
      const res = await fetch("/api/job/" + jobId);
      const job = await res.json();
      if (job.status === "done") {
        setBusy(false);
        toast(`Added: ${job.track.title}`);
        await refreshPlaylist();
      } else if (job.status === "error") {
        setBusy(false);
        toast(job.error || "Extraction failed.", true);
      } else {
        setBusy(true, job.stage || job.status);
        if (typeof job.progress === "number") els.progressFill.style.width = job.progress * 100 + "%";
        pollTimer = setTimeout(tick, 1200);
      }
    } catch {
      pollTimer = setTimeout(tick, 2500);
    }
  };
  tick();
}

function setBusy(on, stage) {
  els.progressWrap.classList.toggle("hidden", !on);
  els.addBtn.disabled = on;
  els.addBtn.querySelector("span").textContent = on ? "Working…" : "Add";
  if (stage) els.progressStage.textContent = stage;
  if (!on) {
    els.progressErr.textContent = "";
    setTimeout(() => (els.progressFill.style.width = "0%"), 400);
  }
}

// ---- playlist data -------------------------------------------------------------
async function refreshPlaylist() {
  try {
    const res = await fetch("/api/playlist");
    state.playlist = await res.json();
    renderPlaylist();
  } catch (e) {
    console.error(e);
  }
}

els.addBtn.addEventListener("click", addTrack);
els.urlInput.addEventListener("keydown", (e) => { if (e.key === "Enter") addTrack(); });
let nameTimer = null;
els.playlistName.addEventListener("change", async () => {
  clearTimeout(nameTimer);
  nameTimer = setTimeout(async () => {
    try {
      const res = await fetch("/api/playlist", {
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
    const res = await fetch("/api/playlist/tracks/remove", {
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

// ---- init ------------------------------------------------------------------------
refreshPlaylist();
checkHealth();
updateRepeatUi();
