# Load the database

Install Python 3 and PostgreSQL 17+, start PostgreSQL, and put `pg_restore`, `psql`, `createdb` and `dropdb` on PATH. Your PostgreSQL role needs permission to create databases. From the repository root:

```sh
python3 scripts/restore_database.py
```

This creates `billbridge_shared` on localhost:5432 using your OS username. It checks the dump and row counts and never overwrites an existing database. No Docker, API key or additional download is needed.

For a password-based installation, add `--user postgres --password`. Other connection options are listed by `python3 scripts/restore_database.py --help`; use `--database another_name` to create another copy.

Connect with psql or a desktop SQL client. Two optional examples:

```sql
SELECT b.bill_id, b.current_title, v.package_id, v.title AS version_title
FROM intermediate.bills b
JOIN intermediate.bill_versions v USING (bill_id);

SELECT section_id, heading, text, citation, source_url
FROM intermediate.sections
WHERE package_id = 'BILLS-118hr1165ih'
ORDER BY record_ordinal;
```

See the [data contract](../docs/data-contract.md) for field meanings.

<details>
<summary>For the data maintainer: rebuild and verify</summary>

Requires Python 3.11–3.13, uv, a running PostgreSQL project database and native `pg_dump` on PATH.

```sh
uv sync --python 3.11 --no-editable
cp .env.example .env  # Only if .env does not already exist.
# Set DATABASE_URL and API_DATA_GOV_KEY locally.
uv run --no-editable billbridge-data run
uv run --no-editable billbridge-data validate
```

Selection: `config/first20.json`. Generated files: `data/raw/`, `data/staging/`, `data/curated/`. To rebuild offline, run `billbridge-data stage`, `model`, then `export` through `uv run --no-editable`. Commit the resulting `database/billbridge.dump` and `manifest.json` together.

Use one pipeline process at a time. Staging/modeling replace tables transactionally; rerun a failed step to recover. Ingestion reuses cached responses; move the raw folder aside to fetch current sources. Keep credentials out of Git. See [API notes](../docs/api-rate-limits.md).

Tests: `uv run --no-editable pytest -q`. Database tests need `BILLBRIDGE_TEST_DATABASE_URL` pointing to a local server allowing temporary database creation. Native restore tests need `BILLBRIDGE_TEST_LOCAL_RESTORE=1`; otherwise those tests are skipped.

</details>
