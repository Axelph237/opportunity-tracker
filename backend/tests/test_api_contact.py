"""The contact record printed at the top of every resume."""

from __future__ import annotations

import contact
import database
import resume_render

FULL = {
    "name": "Aiden King",
    "location": "Chicago, IL",
    "email": "aidenk@uchicago.edu",
    "phone": "(312) 555-0100",
    "links": [{"label": "github.com/me", "url": "https://github.com/me"}],
}


def test_an_install_that_has_never_filled_it_in_reads_blank(app_client):
    response = app_client.get("/api/resume-contact")

    assert response.status_code == 200
    assert response.json() == {"name": "", "location": "", "email": "", "phone": "", "links": []}


def test_what_was_saved_is_what_comes_back(app_client):
    saved = app_client.put("/api/resume-contact", json=FULL)

    assert saved.status_code == 200, saved.text
    assert app_client.get("/api/resume-contact").json() == saved.json()
    assert saved.json()["name"] == "Aiden King"


def test_a_link_with_no_address_is_dropped_rather_than_printed_empty(app_client):
    response = app_client.put("/api/resume-contact", json={
        **FULL,
        "links": [{"label": "Nowhere", "url": ""}, {"label": "", "url": "https://x.example"}],
    })

    links = response.json()["links"]
    assert [link["url"] for link in links] == ["https://x.example"]
    # A link with no label prints as its own address, the way a bare repo url does.
    assert links[0]["label"] == "https://x.example"


def test_a_stored_record_that_will_not_parse_reads_blank_rather_than_raising(app_client):
    """Nobody can fix this row from the interface, so it must not be the thing
    that stops the page loading."""
    database.set_setting(contact.SETTING_KEY, "{not json")

    assert app_client.get("/api/resume-contact").status_code == 200
    assert contact.get_contact()["name"] == ""


def test_the_contact_reaches_the_document_a_push_writes(app_client):
    app_client.put("/api/resume-contact", json=FULL)
    draft_id = app_client.post("/api/drafts", json={"name": "Tailored"}).json()["id"]

    latex = app_client.get(f"/api/drafts/{draft_id}/latex").json()["latex"]

    assert "Aiden King" in latex
    assert r"\href{https://github.com/me}{github.com/me}" in latex
    assert "%%RESUME-CONTACT%%" not in latex
    assert "Your Name" not in latex


def test_a_template_that_writes_its_own_heading_is_left_alone():
    """The marker is optional. Someone who brought their own template keeps
    the heading they wrote in it."""
    template = r"\begin{document}\textbf{Hand written}%%RESUME-BODY%%\end{document}"

    out = resume_render.render_document(template, {"sections": []}, FULL)

    assert "Hand written" in out
    assert "Aiden King" not in out
