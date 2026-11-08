# BillBridge data handoff

Prepared federal bill data from Congress.gov and GovInfo for the CS410 project: **20 bills, 39 bill-text versions, and 408 records** (396 sections and 12 document-context records).

## Load your copy

Install Python 3 and PostgreSQL 17+, start PostgreSQL, and put its command-line tools on PATH. From the cloned repository:

```sh
python3 scripts/restore_database.py
```

This creates a local `billbridge_shared` database from the included dump. No Docker, API key or separate data download is required. Existing databases are not overwritten. See [database setup](database/README.md) for connection options.

## What's included

| Prepared table | Contents |
| --- | --- |
| `intermediate.bills` | Bill identifiers, current titles and latest actions |
| `intermediate.bill_versions` | Version identifiers, version-specific titles, dates and source links |
| `intermediate.sections` | Section/context text, headings, citations, source links and annotations |

Four source-specific staging tables are also included for inspecting the underlying data. See the [data contract](docs/data-contract.md) for relationships and field meanings.

## Interpretation notes

- Versions remain separate even when their text is identical.
- Bill text is not necessarily enacted law. Titles and topics can differ between versions.
- Some records provide document context rather than numbered sections; headings and dates can be missing.
- Text preserves added/deleted markings and amendment instructions.

This handoff provides the data and its documentation. Group 2 owns its retrieval implementation, tools and architecture.
