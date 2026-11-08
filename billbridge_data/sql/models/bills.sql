SELECT b.bill_id, b.congress, b.bill_type, b.bill_number,
       b.current_title, b.introduced_date, b.latest_action_date, b.latest_action_text,
       (SELECT count(*) FROM staging.congress_text_versions v
        WHERE v.bill_id = b.bill_id AND v.package_id IS NOT NULL) AS version_count
FROM staging.congress_bills b;
