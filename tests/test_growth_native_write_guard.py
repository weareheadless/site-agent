"""Execute the exact D1 guard SQL against SQLite, not a status-only fixture."""
from pathlib import Path
import re
import sqlite3

ROOT = Path(__file__).resolve().parents[1]


def query():
    source = (ROOT / 'src/site_agent/templates/next-payload/src/lib/growth-contract.ts').read_text()
    function = source.split('export const activeOperation =', 1)[1].split('\nexport const ', 1)[0]
    return re.search(r'"(SELECT \* FROM helloada_growth_operations[^"\n]+)"', function).group(1)


def database():
    db = sqlite3.connect(':memory:')
    db.execute('CREATE TABLE helloada_growth_operations (operation_key TEXT, document_key TEXT, package_hash TEXT, state TEXT, updated_at TEXT)')
    return db


def test_owned_growth_write_does_not_conflict_with_itself():
    with database() as db:
        db.execute("INSERT INTO helloada_growth_operations VALUES ('draft:own', 'pages:1', 'sha256:package', 'writing', '2026-10-21')")
        assert db.execute(query(), ('pages:1', 'draft:own')).fetchone() is None


def test_native_owner_edit_is_blocked_by_an_unresolved_operation():
    with database() as db:
        for state in ('writing', 'uncertain'):
            db.execute('DELETE FROM helloada_growth_operations')
            db.execute("INSERT INTO helloada_growth_operations VALUES ('draft:other', 'pages:1', 'sha256:package', ?, '2026-10-21')", (state,))
            assert db.execute(query(), ('pages:1', '')).fetchone() is not None


def test_other_operation_with_same_package_still_conflicts_but_other_document_does_not():
    with database() as db:
        db.execute("INSERT INTO helloada_growth_operations VALUES ('publish:other', 'pages:1', 'sha256:package', 'writing', '2026-10-21')")
        assert db.execute(query(), ('pages:1', 'draft:own')).fetchone() is not None
        assert db.execute(query(), ('pages:2', 'draft:own')).fetchone() is None
