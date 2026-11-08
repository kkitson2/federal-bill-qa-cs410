# Data contract

Field reference for the supplied database. See [setup](../database/README.md) for loading it.

## Tables and relationships

| Table | One row represents | Primary key |
| --- | --- | --- |
| staging.congress_bills | A Congress.gov bill response | bill_id |
| staging.congress_text_versions | An entry on a text-version listing page | source_resource, source_ordinal |
| staging.govinfo_packages | A GovInfo package summary | package_id |
| staging.govinfo_sections | An XML section or document-context record | section_id |
| intermediate.bills | A reconciled bill | bill_id |
| intermediate.bill_versions | A reconciled bill-text version | package_id |
| intermediate.sections | An enriched section or document-context record | section_id |

Versions link to bills through `bill_id`; sections link to versions through `package_id`. `record_ordinal` orders records within a package. Staging retains source-local fields; intermediate contains the combined records. Lists, annotations and retained source JSON use JSONB.

Congress.gov supplies current bill titles, latest actions, version labels and dates. GovInfo supplies version-specific titles, publication dates and citation links. XML supplies text and structure.

## Section fields

- `section_id`: unique record ID, including when section numbers repeat. Stable for unchanged XML and parser versions; source or parser changes can change IDs.
- `package_id`: GovInfo bill-version identity such as `BILLS-118hr7521ih`.
- `congress`, `bill_type`, `bill_number`, `version`: bill and version identity.
- `record_type`: `section` for an outer bill section (nested statutory quotations remain inside it), or `document_context` for body instructions/headings outside sections or title-change instructions.
- `text`: complete canonical text. `blocks` partition it exactly. `start`/`end` are Python Unicode character offsets, not UTF-8 bytes; JavaScript UTF-16 indexing may require conversion.
- `hierarchy`, `number`, `heading`, `citation`: structural location and its citation. A missing source heading is the empty string; it does not remove the section.
- `annotations`: editorial changes, references and tables, with XML paths and canonical-text spans. Added/deleted text has visible markers; offsets address that marked text.
- `amendment_context`: surrounding instructions and title changes for amendment documents, repeated on records from the same document; this repetition is not additional source text.
- `document_type`: source root (`bill` or `amendment-doc`). Amendment documents are not necessarily consolidated replacements.
- `title`: GovInfo's title for this version. `source_document_title` separately retains the XML title, including occasional source inconsistencies.
- `version_label`, `version_date`: Congress.gov's version label and original date string. `publication_date`: GovInfo's publication date. Dates may be null and are distinct from fetch times.
- `bill_latest_action`: latest Congress.gov action in the archived response; not an action specific to an older version.
- `source_url`, `source_xml_url`, `source_path`, `source_hash`: government citation link, XML link, XML location, and archived XML body hash.
- `parser_version`: text renderer and section-ID version.

Identical-text versions retain separate IDs and provenance. Version-specific titles can differ from the current bill title. A bill or amendment is not necessarily enacted law or a consolidated statement of current law.

The handoff checks data integrity and text preservation, not retrieval or answer quality. Benchmark labels are separate. Group 2 owns its retrieval implementation and design.
