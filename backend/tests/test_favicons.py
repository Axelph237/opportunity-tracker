"""Site icons: domain handling, caching, and who the server is willing to call.

No test here reaches the network. `favicons.fetch` is the single point that
does, and it is stubbed everywhere below.
"""

from __future__ import annotations

import pytest

import database
import favicons

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40


@pytest.fixture(autouse=True)
def _never_fetch_for_real(monkeypatch):
    """A test that reached a real site would be slow, flaky and rude."""
    def _forbidden(domain):
        raise RuntimeError(f"A test tried to fetch a real favicon for {domain}.")

    monkeypatch.setattr(favicons, "fetch", _forbidden)


def track(url="https://jobs.example.com/role"):
    with database.get_db() as conn:
        conn.execute(
            "INSERT INTO opportunities (title, organization, type, url) VALUES ('R', 'A', 'job', ?)",
            (url,),
        )


# ---------------------------------------------------------------- domain_of

@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://jobs.example.com/role/1", "jobs.example.com"),
        ("http://Example.COM/x", "example.com"),
        ("https://www.example.com/x", "example.com"),
        ("https://example.com:8443/x", "example.com"),
        ("not a url", None),
        ("", None),
        (None, None),
        ("https:///nohost", None),
    ],
)
def test_domain_of(url, expected):
    assert favicons.domain_of(url) == expected


def test_www_is_stripped_so_one_site_is_one_icon():
    assert favicons.domain_of("https://www.ibm.com/a") == favicons.domain_of("https://ibm.com/b")


# ------------------------------------------------------------------ caching

def test_a_fetched_icon_is_stored_and_reused(db_path, monkeypatch):
    calls = []
    monkeypatch.setattr(favicons, "fetch", lambda d: calls.append(d) or (PNG, "image/png"))

    first = favicons.get_or_fetch("example.com")
    second = favicons.get_or_fetch("example.com")

    assert first["data"] == PNG
    assert second["data"] == PNG
    # Cached, not re-downloaded on the next row that happens to share the site.
    assert calls == ["example.com"]


def test_a_site_with_no_icon_is_remembered_as_such(db_path, monkeypatch):
    """Otherwise every page of the table re-requests an icon that is not there."""
    calls = []
    monkeypatch.setattr(favicons, "fetch", lambda d: calls.append(d) or None)

    assert favicons.get_or_fetch("example.com") is None
    assert favicons.get_or_fetch("example.com") is None
    assert calls == ["example.com"]


def test_a_remembered_miss_is_retried_after_a_while(db_path, monkeypatch):
    monkeypatch.setattr(favicons, "fetch", lambda d: None)
    favicons.get_or_fetch("example.com")
    with database.get_db() as conn:
        conn.execute(
            "UPDATE favicons SET fetched_at = ? WHERE domain = 'example.com'",
            ("2000-01-01T00:00:00+00:00",),
        )

    monkeypatch.setattr(favicons, "fetch", lambda d: (PNG, "image/png"))
    assert favicons.get_or_fetch("example.com")["data"] == PNG


def test_an_unparseable_stored_timestamp_just_means_refetch(db_path, monkeypatch):
    monkeypatch.setattr(favicons, "fetch", lambda d: None)
    favicons.get_or_fetch("example.com")
    with database.get_db() as conn:
        conn.execute("UPDATE favicons SET fetched_at = 'nonsense'")
    monkeypatch.setattr(favicons, "fetch", lambda d: (PNG, "image/png"))
    assert favicons.get_or_fetch("example.com") is not None


# ------------------------------------------------------- what may be fetched

def test_known_domains_covers_listings_and_sources(app_client):
    track("https://jobs.acme.test/1")
    with database.get_db() as conn:
        conn.execute(
            "INSERT INTO sources (name, url, type) VALUES ('B', 'https://board.test/x', 'job_board')"
        )
    domains = favicons.known_domains()
    assert "jobs.acme.test" in domains
    assert "board.test" in domains


def test_the_endpoint_serves_a_tracked_domain(app_client, monkeypatch):
    track("https://jobs.example.com/role")
    monkeypatch.setattr(favicons, "fetch", lambda d: (PNG, "image/png"))

    response = app_client.get("/api/favicons/jobs.example.com")

    assert response.status_code == 200
    assert response.content == PNG
    assert response.headers["content-type"] == "image/png"
    assert "max-age" in response.headers["cache-control"]


def test_the_endpoint_refuses_a_domain_the_app_does_not_track(app_client):
    """The domain is client-supplied, so without this the route is an open
    proxy: name any host and the server fetches it."""
    response = app_client.get("/api/favicons/evil.example.org")
    assert response.status_code == 404
    assert "tracked" in response.json()["detail"]


@pytest.mark.parametrize(
    "target",
    ["192.168.1.1", "localhost", "169.254.169.254", "10.0.0.1"],
)
def test_internal_addresses_are_not_reachable_through_it(app_client, target):
    assert app_client.get(f"/api/favicons/{target}").status_code == 404


def test_a_domain_that_is_not_a_domain_is_rejected(app_client):
    assert app_client.get("/api/favicons/not%20a%20domain").status_code == 400


def test_a_tracked_domain_with_no_icon_is_a_404(app_client, monkeypatch):
    track("https://jobs.example.com/role")
    monkeypatch.setattr(favicons, "fetch", lambda d: None)
    response = app_client.get("/api/favicons/jobs.example.com")
    assert response.status_code == 404
    assert "No icon" in response.json()["detail"]


def test_www_and_bare_forms_resolve_to_the_same_cached_icon(app_client, monkeypatch):
    track("https://www.example.com/role")
    monkeypatch.setattr(favicons, "fetch", lambda d: (PNG, "image/png"))
    assert app_client.get("/api/favicons/www.example.com").status_code == 200
    assert app_client.get("/api/favicons/example.com").status_code == 200
    with database.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) AS c FROM favicons").fetchone()["c"] == 1


# ------------------------------------------------ picking an icon from a page

def test_the_pages_own_declaration_is_preferred_over_the_conventional_path():
    html = '<html><head><link rel="shortcut icon" href="/static/brand.png"></head>'
    urls = favicons._icon_urls("example.com", html)
    assert urls[0] == "https://example.com/static/brand.png"
    assert urls[-1] == "https://example.com/favicon.ico"


def test_a_relative_declaration_is_resolved_against_the_site():
    urls = favicons._icon_urls("example.com", '<link rel="icon" href="img/i.png">')
    assert "https://example.com/img/i.png" in urls


def test_an_absolute_declaration_on_another_host_is_kept():
    """Plenty of sites serve their icon from a CDN."""
    html = '<link rel="icon" href="https://cdn.example.net/i.png">'
    assert "https://cdn.example.net/i.png" in favicons._icon_urls("example.com", html)


def test_the_conventional_path_is_tried_when_the_page_says_nothing():
    assert favicons._icon_urls("example.com", "") == ["https://example.com/favicon.ico"]


def test_only_a_few_candidates_are_ever_tried():
    """A page listing a dozen icon sizes should not mean a dozen requests."""
    html = "".join(f'<link rel="icon" href="/i{n}.png">' for n in range(20))
    assert len(favicons._icon_urls("example.com", html)) <= 4


# ---------------------------------------------------- not swamping the server

def test_only_a_few_sites_are_contacted_at_once(db_path, monkeypatch):
    """A page of 25 unknown domains is 25 blocking HTTP calls on the same
    threadpool the rest of the API uses. Past the limit the icon is skipped."""
    monkeypatch.setattr(favicons, "fetch", lambda d: (PNG, "image/png"))
    # Take every slot, as concurrent requests would.
    held = []
    while favicons._FETCH_SLOTS.acquire(blocking=False):
        held.append(True)
    try:
        assert favicons.get_or_fetch("example.com") is None
    finally:
        for _ in held:
            favicons._FETCH_SLOTS.release()


def test_being_busy_is_not_remembered_as_a_missing_icon(db_path, monkeypatch):
    """Nothing was learned about the site, so the next visit must try again."""
    monkeypatch.setattr(favicons, "fetch", lambda d: (PNG, "image/png"))
    held = []
    while favicons._FETCH_SLOTS.acquire(blocking=False):
        held.append(True)
    try:
        favicons.get_or_fetch("example.com")
    finally:
        for _ in held:
            favicons._FETCH_SLOTS.release()

    assert favicons.lookup("example.com") is None
    assert favicons.get_or_fetch("example.com")["data"] == PNG


def test_the_slots_are_returned_even_when_a_fetch_blows_up(db_path, monkeypatch):
    def _explode(domain):
        raise RuntimeError("network on fire")

    monkeypatch.setattr(favicons, "fetch", _explode)
    with pytest.raises(RuntimeError):
        favicons.get_or_fetch("example.com")

    # Not leaked: a later fetch still gets a slot.
    monkeypatch.setattr(favicons, "fetch", lambda d: (PNG, "image/png"))
    assert favicons.get_or_fetch("example.com")["data"] == PNG
