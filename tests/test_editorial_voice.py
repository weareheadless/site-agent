"""A brief that says which site it is for, derived once for every tenant.

The article that reached an owner carried six empty business fields and
`voice: "default"`: the writer was told it was writing for *a site* and never
which. These tests hold the replacement contract rather than one tenant's text:
a voice comes from the owner's own context when they gave one, from the site's
own published words otherwise, and is recorded as absent rather than invented
when neither exists.
"""

from __future__ import annotations

import pytest

from site_agent.application.editorial_brief import build_brief
from site_agent.application.editorial_voice import derive_voice
from site_agent.hands.web_read import Page

ACTION = {
    "id": "action_1",
    "revision": 4,
    "problem": "No coverage of bridal makeup for daytime",
    "recommendation": "Write about daytime bridal makeup",
    "expectedOutcome": "Readers find the site for this",
    "primaryQuery": "maquillaje novia día",
    "target": {"canonicalUrl": ""},
    "requiredCapabilities": ["article.create"],
}


def _page(url: str, text: str, links: tuple[tuple[str, str], ...] = ()) -> Page:
    return Page(url=url, title="", text=text, links=links)


HOME_TEXT = (
    "Soy Astrid. Te recibo en mi estudio privado en casa, un espacio tranquilo donde "
    "te atiendo personalmente, una clienta a la vez. Tu color. Tu corte. Tu estilista."
)
SERVICE_TEXT = (
    "Color y corte. Trabajamos tu color con calma, mirando cómo ha respondido tu pelo "
    "antes de tocar la raíz. Después de la cita te explico cómo mantenerlo en casa."
)
BRIDAL_TEXT = (
    "Novias. El día de la boda probamos el peinado antes, con tiempo, para que no haya "
    "sorpresas. Llegas con el pelo limpio y salimos con la forma que ya probaste."
)


def fake_reader(pages: dict[str, Page]):
    def read(url: str) -> Page:
        if url not in pages:
            raise AssertionError(f"unexpected fetch: {url}")
        return pages[url]

    return read


def test_a_link_label_split_across_nested_markup_keeps_its_words_apart():
    """A real nav label is "Freediving<span>AIDA 1 to AIDA 4</span>"."""
    from site_agent.hands.web_read import _Text

    parser = _Text()
    parser.feed(
        '<nav><a href="/freediving">Freediving<span>AIDA 1 to AIDA 4</span></a></nav>'
    )

    assert ("Freediving AIDA 1 to AIDA 4", "/freediving") in parser.links


def test_navigation_is_not_mistaken_for_the_site_voice():
    """A flattened header must not teach the model to write menus."""
    from site_agent.application.editorial_voice import _clean_lines

    page = (
        "Ir al contenido\n"
        "Inicio Color y corte Maquillaje y peinado Novias\n"
        "Color, balayage y corte en Playa del Carmen.\n"
        "Consulta disponibilidad ↗\n"
        "Tu color. Tu corte. Tu estilista.\n"
        "Tu color. Tu corte. Tu estilista.\n"
    )

    cleaned = _clean_lines(page)

    # Real sentences survive, including one that begins with a nav word.
    assert "Color, balayage y corte en Playa del Carmen." in cleaned
    assert cleaned.count("Tu color. Tu corte. Tu estilista.") == 1
    # Furniture does not.
    assert "Ir al contenido" not in cleaned
    assert "Inicio Color y corte" not in cleaned
    assert "↗" not in cleaned


def test_the_site_own_words_become_the_voice_and_its_own_navigation_the_services():
    reader = fake_reader(
        {
            "https://studio.example": _page(
                "https://studio.example",
                HOME_TEXT,
                links=(
                    ("Color y corte", "https://studio.example/color-y-corte"),
                    ("Novias", "https://studio.example/novias"),
                ),
            ),
            "https://studio.example/color-y-corte": _page(
                "https://studio.example/color-y-corte", SERVICE_TEXT
            ),
            "https://studio.example/novias": _page(
                "https://studio.example/novias", BRIDAL_TEXT
            ),
        }
    )

    facts = derive_voice(
        site={"public_url": "https://studio.example/"},
        display_name="Astrid Rincón",
        fetch=reader,
    )

    assert facts["voice_basis"] == "site_copy"
    assert facts["name"] == "Astrid Rincón"
    # The words are the site's own, not a summary of them.
    assert HOME_TEXT in facts["voice_sample"]
    assert SERVICE_TEXT in facts["voice_sample"]
    # The site's navigation is its own list of what it does.
    assert "Color y corte" in facts["services"]
    assert "Novias" in facts["services"]


def test_an_owner_statement_outranks_reading_the_site():
    reader = fake_reader({"https://studio.example": _page("https://studio.example", HOME_TEXT)})

    facts = derive_voice(
        customer_context={
            "business": {"name": "Astrid Rincón", "services": ["color"]},
            "brand": {"voice": "Cercana, en primera persona, nunca comercial."},
        },
        site={"public_url": "https://studio.example/"},
        display_name="ignored",
        fetch=reader,
    )

    assert facts["voice_basis"] == "customer_context"
    assert facts["identity"] == "Cercana, en primera persona, nunca comercial."
    # The site is not read at all once the owner has said it directly.
    assert facts["voice_sample"] == ""


def test_a_site_that_cannot_be_read_yields_an_honest_absence_not_a_failure():
    def broken(url: str) -> Page:
        raise OSError("connection refused")

    facts = derive_voice(
        site={"public_url": "https://studio.example/"}, display_name="Studio", fetch=broken
    )

    assert facts["voice_basis"] == "none"
    assert facts["voice_sample"] == ""
    # The name still travels: the writer knows it is writing as someone.
    assert facts["name"] == "Studio"


def test_a_tenant_with_no_site_at_all_is_not_an_error():
    facts = derive_voice(display_name="Studio")

    assert facts["voice_basis"] == "none"
    assert facts["name"] == "Studio"


def test_utility_pages_are_not_the_business_describing_itself():
    reader = fake_reader(
        {
            "https://studio.example": _page(
                "https://studio.example",
                HOME_TEXT,
                links=(
                    ("Aviso legal", "https://studio.example/privacidad"),
                    ("Blog", "https://studio.example/blog"),
                    ("Novias", "https://studio.example/novias"),
                ),
            ),
            "https://studio.example/novias": _page(
                "https://studio.example/novias", BRIDAL_TEXT
            ),
        }
    )

    facts = derive_voice(
        site={"public_url": "https://studio.example/"}, display_name="Studio", fetch=reader
    )

    # Only the bridal page is real copy; legal and blog pages are never fetched.
    assert facts["services"] == ["Novias"]
    assert BRIDAL_TEXT in facts["voice_sample"]


def test_a_site_linking_its_own_sections_relatively_is_still_read():
    """A real site writes "/novias/", so an unresolved href must be resolved."""
    reader = fake_reader(
        {
            "https://studio.example": _page(
                "https://studio.example",
                HOME_TEXT,
                links=(("Novias", "/novias/"), ("Color y corte", "/color-y-corte/")),
            ),
            "https://studio.example/novias/": _page(
                "https://studio.example/novias/", BRIDAL_TEXT
            ),
            "https://studio.example/color-y-corte/": _page(
                "https://studio.example/color-y-corte/", SERVICE_TEXT
            ),
        }
    )

    facts = derive_voice(
        site={"public_url": "https://studio.example/"}, display_name="Studio", fetch=reader
    )

    assert facts["voice_basis"] == "site_copy"
    assert facts["services"] == ["Novias", "Color y corte"]
    assert BRIDAL_TEXT in facts["voice_sample"]


def test_another_origin_is_never_read():
    reader = fake_reader(
        {
            "https://studio.example": _page(
                "https://studio.example",
                HOME_TEXT,
                links=(("Elsewhere", "https://other.example/services"),),
            )
        }
    )

    facts = derive_voice(
        site={"public_url": "https://studio.example/"}, display_name="Studio", fetch=reader
    )

    assert facts["voice_basis"] == "site_copy"
    assert facts["services"] == []


def test_the_brief_carries_the_voice_so_the_writer_is_not_left_guessing():
    brief = build_brief(
        tenant="site-x",
        remote=ACTION,
        business={
            "name": "Astrid Rincón",
            "services": ["color", "novias"],
            "voice_sample": HOME_TEXT,
            "voice_basis": "site_copy",
        },
    )

    assert brief["business"]["voice_basis"] == "site_copy"
    assert brief["business"]["voice_sample"] == " ".join(HOME_TEXT.split())
    assert brief["business"]["services"] == ["color", "novias"]


def test_an_unknown_voice_source_is_refused_rather_than_silently_dropped():
    """A misspelling would otherwise become "none" while a sample sat in the brief."""
    with pytest.raises(ValueError, match="unknown voice_basis"):
        build_brief(
            tenant="site-x",
            remote=ACTION,
            business={"name": "Studio", "voice_sample": HOME_TEXT, "voice_basis": "site-copy"},
        )


def test_a_brief_with_no_business_still_says_the_voice_is_unknown():
    brief = build_brief(tenant="site-x", remote=ACTION)

    assert brief["business"]["voice_basis"] == "none"
    assert brief["business"]["voice_sample"] == ""
