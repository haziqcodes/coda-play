"""API tests for Coda — run with: pytest tests/ -q"""

import pytest

import server


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Isolate the app: point all data paths at a temp dir."""
    data = tmp_path / "data"
    (data / "tracks").mkdir(parents=True)
    (data / "thumbs").mkdir(parents=True)
    monkeypatch.setattr(server, "DATA_DIR", str(data))
    monkeypatch.setattr(server, "TRACKS_DIR", str(data / "tracks"))
    monkeypatch.setattr(server, "THUMB_DIR", str(data / "thumbs"))
    monkeypatch.setattr(server, "PLAYLIST_FILE", str(data / "playlist.json"))
    server.app.config["TESTING"] = True
    with server.app.test_client() as c:
        yield c


def _seed_tracks(client, ids):
    with server.PLAYLIST_LOCK:
        pl = server.load_playlist()
        for tid in ids:
            pl["tracks"].append({
                "id": tid, "title": "T-" + tid, "artist": "A", "duration": 10,
                "source_url": "http://x", "file": tid + ".mp3",
                "thumbnail": None, "added_at": "now",
            })
        server.save_playlist(pl)


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.get_json()
    assert "ffmpeg_ok" in body
    assert "yt_dlp_ok" in body


def test_playlist_starts_empty(client):
    body = client.get("/api/playlist").get_json()
    assert body["tracks"] == []
    assert isinstance(body["name"], str)


def test_rename_playlist(client):
    r = client.post("/api/playlist", json={"name": "My Test List"})
    assert r.status_code == 200
    assert client.get("/api/playlist").get_json()["name"] == "My Test List"


def test_remove_track(client):
    _seed_tracks(client, ["abc123def456"])
    r = client.post("/api/playlist/tracks/remove", json={"id": "abc123def456"})
    assert r.status_code == 200
    assert client.get("/api/playlist").get_json()["tracks"] == []


def test_remove_unknown_track_404(client):
    r = client.post("/api/playlist/tracks/remove", json={"id": "doesnotexist"})
    assert r.status_code == 404


def test_reorder_tracks(client):
    _seed_tracks(client, ["aaa111bbb222", "ccc333ddd444"])
    r = client.post("/api/playlist", json={"ids": ["ccc333ddd444", "aaa111bbb222"]})
    assert r.status_code == 200
    ids = [t["id"] for t in client.get("/api/playlist").get_json()["tracks"]]
    assert ids == ["ccc333ddd444", "aaa111bbb222"]


def test_add_rejects_invalid_url(client):
    r = client.post("/api/add", json={"url": "not-a-url"})
    assert r.status_code == 400
    r = client.post("/api/add", json={"url": "ftp://nope"})
    assert r.status_code == 400


def test_unknown_job_404(client):
    assert client.get("/api/job/nonexistent").status_code == 404
