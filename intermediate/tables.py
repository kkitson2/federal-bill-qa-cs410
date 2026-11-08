"""Transactional SQL materialization and freshness checks for intermediate tables."""

from importlib.resources import files

from psycopg import sql

MODELS = {"bills": "bill_id", "bill_versions": "package_id", "sections": "package_id, record_ordinal"}


def query(name):
    return files("billbridge_data").joinpath(f"sql/models/{name}.sql").read_text().strip().rstrip(";")


def clear(connection):
    for name in reversed(MODELS):
        connection.execute(sql.SQL("DELETE FROM intermediate.{}").format(sql.Identifier(name)))


def materialize(connection):
    duplicates = connection.execute("""SELECT package_id FROM staging.congress_text_versions
        WHERE package_id IS NOT NULL GROUP BY package_id HAVING count(*) > 1""").fetchall()
    if duplicates:
        raise ValueError("Ambiguous Congress-to-GovInfo version match: duplicate package listing")
    clear(connection)
    for name in MODELS:
        connection.execute(sql.SQL("INSERT INTO intermediate.{} SELECT * FROM (").format(sql.Identifier(name)) +
                           sql.SQL(query(name) + ") source"))


def verify_materialized(connection):
    # Check upstream models first; the sections query uses the stored version table.
    for name, ordering in MODELS.items():
        expected = connection.execute("SELECT * FROM (" + query(name) +
            ") source ORDER BY " + ordering).fetchall()
        actual = connection.execute(sql.SQL("SELECT * FROM intermediate.{} ORDER BY " + ordering)
            .format(sql.Identifier(name))).fetchall()
        if actual != expected:
            raise ValueError(f"Intermediate {name} rows differ from staging-derived results; rerun model")
