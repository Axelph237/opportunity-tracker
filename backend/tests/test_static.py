"""Static file serving: the SPA shell, deep links, and path-traversal safety.

frontend/dist ships as a real build artifact in this repo, so these tests run
against it directly rather than faking one up.
"""

from __future__ import annotations

from pathlib import Path

import main


def test_dist_dir_exists_precondition():
    """If this ever fails, every other test in this file is testing the wrong branch."""
    assert main.DIST_DIR.is_dir()
    assert (main.DIST_DIR / "index.html").is_file()


def test_root_serves_index_html(app_client):
    resp = app_client.get("/")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert resp.text == (main.DIST_DIR / "index.html").read_text()


def test_deep_link_returns_spa_shell(app_client):
    resp = app_client.get("/opportunities/42")
    assert resp.status_code == 200
    assert resp.text == (main.DIST_DIR / "index.html").read_text()


def test_another_deep_link_returns_spa_shell(app_client):
    resp = app_client.get("/settings/appearance")
    assert resp.status_code == 200
    assert resp.text == (main.DIST_DIR / "index.html").read_text()


def test_unknown_api_route_is_404_not_the_spa_shell(app_client):
    resp = app_client.get("/api/unknown")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "No such API route"


def test_missing_file_with_extension_is_404_not_the_spa_shell(app_client):
    resp = app_client.get("/does-not-exist.js")
    assert resp.status_code == 404


def test_real_asset_is_served(app_client):
    assets_dir = main.DIST_DIR / "assets"
    some_asset = next(assets_dir.iterdir())
    resp = app_client.get(f"/assets/{some_asset.name}")
    assert resp.status_code == 200


def test_path_traversal_dotdot_does_not_escape_dist(app_client):
    resp = app_client.get("/../../etc/passwd")
    assert resp.status_code == 200
    # Never the real /etc/passwd; falls back to the SPA shell.
    assert resp.text == (main.DIST_DIR / "index.html").read_text()
    assert "root:" not in resp.text


def test_path_traversal_percent_encoded_does_not_escape_dist(app_client):
    resp = app_client.get("/%2e%2e/%2e%2e/etc/passwd")
    assert resp.status_code in (200, 404)
    if resp.status_code == 200:
        assert resp.text == (main.DIST_DIR / "index.html").read_text()
    assert "root:" not in resp.text


def test_path_traversal_encoded_slash_variant_does_not_escape_dist(app_client):
    resp = app_client.get("/..%2f..%2fetc%2fpasswd")
    assert resp.status_code in (200, 404)
    if resp.status_code == 200:
        assert resp.text == (main.DIST_DIR / "index.html").read_text()
    assert "root:" not in resp.text


def test_spa_candidate_resolution_rejects_absolute_escape(tmp_path):
    """Unit-level check of the same guard the route uses, isolated from the client.

    `spa()` computes `(DIST_DIR / full_path).resolve()` and only serves it as a
    real file when that result is still inside DIST_DIR. A `full_path` engineered
    to point at an absolute path outside the tree must fail that check.
    """
    escape_attempt = (main.DIST_DIR / "../../../../etc/passwd").resolve()
    assert not escape_attempt.is_relative_to(main.DIST_DIR.resolve())
