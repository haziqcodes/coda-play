"""API tests for Coda — run with: pytest tests/ -q"""

import io

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
    monkeypatch.setattr(server, "COOKIES_FILE", str(data / "cookies.txt"))
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


NETSCAPE = ("# Netscape HTTP Cookie File\n"
            ".youtube.com\tTRUE\t/\tTRUE\t0\tSID\tabc123\n"
            ".youtube.com\tTRUE\t/\tTRUE\t0\tHSID\txyz789\n")


def test_cookies_absent_by_default(client):
    assert client.get("/api/cookies").get_json() == {"present": False, "cookies": 0}


def test_cookies_upload_status_delete(client):
    r = client.post("/api/cookies",
                    data={"cookies": (io.BytesIO(NETSCAPE.encode()), "cookies.txt")},
                    content_type="multipart/form-data")
    assert r.status_code == 200
    assert r.get_json()["cookies"] == 2
    assert client.get("/api/cookies").get_json() == {"present": True, "cookies": 2}

    # empty / comment-only upload is rejected
    r = client.post("/api/cookies",
                    data={"cookies": (io.BytesIO(b"# only a comment\n"), "cookies.txt")},
                    content_type="multipart/form-data")
    assert r.status_code == 400

    # raw-text body also works
    r = client.post("/api/cookies", data=NETSCAPE.encode(),
                    content_type="text/plain")
    assert r.status_code == 200

    # delete
    assert client.delete("/api/cookies").status_code == 200
    assert client.get("/api/cookies").get_json() == {"present": False, "cookies": 0}


def test_libraries_are_isolated(client):
    a = {"X-Coda-Library": "AAAA1111"}
    b = {"X-Coda-Library": "BBBB2222"}
    client.post("/api/playlist", json={"name": "Phone A"}, headers=a)
    assert client.get("/api/playlist", headers=a).get_json()["name"] == "Phone A"
    assert client.get("/api/playlist", headers=b).get_json()["name"] == "My Coda Playlist"


def test_playlist_url_detection():
    assert server.is_playlist_url("https://www.youtube.com/playlist?list=PL123abc")
    assert server.is_playlist_url("https://youtube.com/watch?v=x&list=PLxyz")
    assert not server.is_playlist_url("https://www.youtube.com/watch?v=IltsOcCj1Ak")
    assert not server.is_playlist_url("https://www.youtube.com/watch?v=x&list=RDx")  # endless mix
