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
 AND v.bill_number = s.bill_number AND v.version = s.version;
