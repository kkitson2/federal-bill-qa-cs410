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
 AND b.congress = c.congress AND b.bill_type = c.bill_type AND b.bill_number = c.bill_number;
