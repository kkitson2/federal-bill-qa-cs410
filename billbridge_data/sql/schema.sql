CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS intermediate;

CREATE TABLE IF NOT EXISTS staging.congress_bills (
    bill_id text NOT NULL,
    congress integer NOT NULL,
    bill_type text NOT NULL,
    bill_number integer NOT NULL,
    current_title text NOT NULL,
    introduced_date date,
    latest_action_date date,
    latest_action_text text NOT NULL,
    source_resource text NOT NULL,
    source_hash text NOT NULL,
    source_payload jsonb NOT NULL,
    PRIMARY KEY (bill_id)
);

CREATE TABLE IF NOT EXISTS staging.congress_text_versions (
    source_resource text NOT NULL,
    source_ordinal integer NOT NULL,
    bill_id text NOT NULL,
    congress integer NOT NULL,
    bill_type text NOT NULL,
    bill_number integer NOT NULL,
    package_id text,
    version text,
    version_label text NOT NULL,
    version_date timestamptz,
    version_date_source text,
    source_xml_url text,
    formats jsonb NOT NULL,
    exclusion_reason text,
    source_hash text NOT NULL,
    source_payload jsonb NOT NULL,
    PRIMARY KEY (source_resource, source_ordinal)
);

CREATE TABLE IF NOT EXISTS staging.govinfo_packages (
    package_id text NOT NULL,
    congress integer NOT NULL,
    bill_type text NOT NULL,
    bill_number integer NOT NULL,
    version text NOT NULL,
    version_title text NOT NULL,
    publication_date date,
    short_titles jsonb NOT NULL,
    source_url text NOT NULL,
    download_url text NOT NULL,
    source_resource text NOT NULL,
    source_hash text NOT NULL,
    source_payload jsonb NOT NULL,
    PRIMARY KEY (package_id)
);

CREATE TABLE IF NOT EXISTS staging.govinfo_sections (
    section_id text NOT NULL,
    package_id text NOT NULL,
    record_ordinal integer NOT NULL,
    congress integer NOT NULL,
    bill_type text NOT NULL,
    bill_number integer NOT NULL,
    version text NOT NULL,
    number text NOT NULL,
    heading text NOT NULL,
    text text NOT NULL,
    hierarchy jsonb NOT NULL,
    blocks jsonb NOT NULL,
    annotations jsonb NOT NULL,
    parser_version text NOT NULL,
    document_type text NOT NULL,
    record_type text NOT NULL,
    amendment_context text NOT NULL,
    source_document_title text NOT NULL,
    source_path text NOT NULL,
    source_hash text NOT NULL,
    source_resource text NOT NULL,
    PRIMARY KEY (section_id),
    UNIQUE (package_id, record_ordinal)
);
CREATE INDEX IF NOT EXISTS congress_versions_package_idx ON staging.congress_text_versions(package_id);

CREATE TABLE IF NOT EXISTS intermediate.bills AS
SELECT b.bill_id, b.congress, b.bill_type, b.bill_number,
       b.current_title, b.introduced_date, b.latest_action_date, b.latest_action_text,
       (SELECT count(*) FROM staging.congress_text_versions v
        WHERE v.bill_id = b.bill_id AND v.package_id IS NOT NULL) AS version_count
FROM staging.congress_bills b
WITH NO DATA;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='intermediate.bills'::regclass AND contype='p') THEN
        ALTER TABLE intermediate.bills ADD PRIMARY KEY (bill_id);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS intermediate.bill_versions AS
SELECT c.bill_id, g.package_id, g.congress, g.bill_type, g.bill_number,
       g.version, g.version_title AS title, c.version_label, c.version_date,
       c.version_date_source, g.publication_date, g.short_titles,
       b.latest_action_text AS bill_latest_action, g.source_url, c.source_xml_url,
       g.source_resource AS govinfo_resource, c.source_resource AS congress_resource
FROM staging.govinfo_packages g
JOIN staging.congress_text_versions c
  ON c.package_id = g.package_id
 AND c.congress = g.congress AND c.bill_type = g.bill_type
 AND c.bill_number = g.bill_number AND c.version = g.version
JOIN staging.congress_bills b
  ON b.bill_id = c.bill_id
 AND b.congress = c.congress AND b.bill_type = c.bill_type AND b.bill_number = c.bill_number
WITH NO DATA;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='intermediate.bill_versions'::regclass AND contype='p') THEN
        ALTER TABLE intermediate.bill_versions ADD PRIMARY KEY (package_id);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS intermediate.sections AS
SELECT s.record_ordinal, s.section_id, s.package_id, s.congress,
       s.bill_type, s.bill_number, s.version, s.number, s.heading, s.text,
       s.hierarchy, s.blocks, s.annotations, s.parser_version, s.document_type,
       s.record_type, s.amendment_context, s.source_document_title, s.source_path, s.source_hash,
       v.version_label, v.version_date_source AS version_date,
       v.publication_date::text AS publication_date, v.bill_latest_action,
       v.title, v.source_url, v.source_xml_url,
       s.congress::text || 'th Congress, ' || upper(s.bill_type) || ' ' || s.bill_number::text ||
       ', ' || s.version || ', ' ||
       (SELECT string_agg(h.value, ' / ' ORDER BY h.ordinality)
        FROM jsonb_array_elements_text(s.hierarchy) WITH ORDINALITY AS h(value, ordinality)) AS citation
FROM staging.govinfo_sections s
JOIN intermediate.bill_versions v
  ON v.package_id = s.package_id
 AND v.congress = s.congress AND v.bill_type = s.bill_type
 AND v.bill_number = s.bill_number AND v.version = s.version
WITH NO DATA;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='intermediate.sections'::regclass AND contype='p') THEN
        ALTER TABLE intermediate.sections ADD PRIMARY KEY (section_id);
    END IF;
END $$;
