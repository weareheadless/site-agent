"""The owner's note on a picture is its own fact, and it survives analysis.

A note like "Susi, March launch shoot" is the owner's context about a file. Ada
must be able to read it, and the analysis pass must never erase it. Every text
field media already had (description, alt, tags) is rewritten by that pass, so a
note put there would silently disappear on the next analysis: it needs its own
field, in its own column, with its own migration.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "packages/helloada-payload-core/src/schema/index.ts"
MIGRATIONS = ROOT / "src/site_agent/templates/next-payload/src/migrations"
GATEWAY = ROOT / "src/site_agent/hands/payload_gateway.py"
ROUTE = ROOT / "src/site_agent/templates/next-payload/src/app/api/helloada/[...path]/route.ts"


def test_media_has_an_owner_note_field_of_its_own():
    source = SCHEMA.read_text()
    media = source[source.index("export const Media: CollectionConfig"):]
    media = media[:media.index("hooks:")]

    assert re.search(r"name: 'ownerNote', type: 'textarea'", media), "media has no owner-note field"
    # Not localized: it is internal context about the file, not published copy.
    note = [line for line in media.splitlines() if "name: 'ownerNote'" in line][0]
    assert "localized" not in note


def test_the_note_is_not_stored_in_a_field_analysis_rewrites():
    """Analysis writes description, alt and tags; the note must be none of them."""
    workspace = (ROOT / "src/site_agent/application/workspace.py").read_text()
    analysis_write = workspace[workspace.index("updated = payload.update_media(media_id, {"):]
    analysis_write = analysis_write[:analysis_write.index("}, expected_hash=")]

    assert "ownerNote" not in analysis_write, (
        "the analysis pass writes ownerNote, so it would overwrite the owner's own words"
    )


def test_a_migration_adds_the_column_and_is_registered():
    migration = MIGRATIONS / "20261127_090000_media_owner_note.ts"
    assert migration.is_file(), "no migration adds media.owner_note"
    source = migration.read_text()
    assert "ALTER TABLE `media` ADD COLUMN `owner_note` text" in source
    # Additive only: never a table rebuild, which would risk the file itself.
    assert "DROP TABLE" not in source
    assert "CREATE TABLE" not in source

    index = (MIGRATIONS / "index.ts").read_text()
    assert "migration_20261127_090000_media_owner_note" in index
    assert "name: '20261127_090000_media_owner_note'" in index
    # It must be last: the chain is applied in order.
    assert index.rindex("20261127_090000_media_owner_note") > index.rindex("20261123_090000_locale_parent_indexes")


def test_the_media_table_in_the_initial_chain_is_not_edited():
    """A shipped migration is history; the column belongs in a new migration."""
    initial = (MIGRATIONS / "20261004_021536_helloada_initial.ts").read_text()
    start = initial.index("CREATE TABLE \\`media\\` (")
    media_table = initial[start:start + 2_000]
    assert "owner_note" not in media_table


def test_ada_can_read_the_note_and_it_is_named_for_her():
    gateway = GATEWAY.read_text()
    assert 'owner_note=str(document.get("ownerNote") or "").strip()' in gateway
    assert '"owner_note": asset.owner_note' in gateway
    assert '"owner_note": asset.owner_note,' in gateway

    jobs = (ROOT / "src/site_agent/core/chat_jobs.py").read_text()
    assert "the owner's own note about this file" in jobs, (
        "an attached file's note never reaches the model"
    )


def test_the_owner_can_read_and_save_a_note_over_the_bridge():
    route = ROUTE.read_text()
    library = route[route.index("if (path === '/media-library')"):]
    library = library[:library.index("if (path === '/content/history')")]
    assert "ownerNote: text(document.ownerNote)" in library, "the gallery response hides the note"
    assert "documentHash: await hashJson(withoutPayloadMetadata(document))" in library, \
        "the gallery response carries no revision, so a note could only be saved blind"

    note_route = route[route.index("if (path === '/media/note')"):]
    note_route = note_route[:note_route.index("if (path === '/media/upload')")]
    # Exact revision before writing, and only the note field.
    assert "expectedHash" in note_route
    assert "409" in note_route
    # Strip the explanatory comment so this checks the write, not the prose.
    write = "\n".join(line for line in note_route.splitlines() if not line.strip().startswith("//"))
    for forbidden in ("description", "alt:", "analysisStatus", "tags"):
        assert forbidden not in write, f"the note route also writes {forbidden}"


def test_analysis_reads_the_note_as_context_and_never_restates_it():
    """The note informs the reading, and is not written back as an observation."""
    source = (ROOT / "src/site_agent/application/workspace.py").read_text()

    prompt = source[source.index("The owner's own note about this file"):]
    prompt = prompt[:prompt.index(")", 400)]
    assert "context, not a visible observation" in prompt
    assert "not " in prompt and "instructions" in prompt

    # The analysis write must not carry the note back into the document.
    write = source[source.index("updated = payload.update_media(media_id, {"):]
    write = write[:write.index("}, expected_hash=")]
    assert "ownerNote" not in write
