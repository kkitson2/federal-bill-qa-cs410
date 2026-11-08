"""Independent check that canonicalization retains legislative character data."""

import re

from lxml import etree

from staging.parser import NAVIGATION


def verify_text(xml, records):
    root = etree.fromstring(xml, etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=True))
    tree = root.getroottree()

    def text_fragments(node, exclude_sections=False):
        if node.tag in NAVIGATION or (exclude_sections and node.tag == "section"):
            return
        if node.text:
            yield node.text
        for child in node:
            yield from text_fragments(child, exclude_sections)
            if child.tail:
                yield child.tail

    checked = 0
    for record in records:
        nodes = tree.xpath(record.source_path)
        if len(nodes) != 1:
            raise ValueError("Source path does not resolve uniquely")
        expected = "".join(text_fragments(nodes[0], record.record_type == "document_context"))
        markers = {"[TABLE]", "[/TABLE]"}
        for annotation in record.annotations:
            if annotation.kind == "editorial_change":
                markers.update({f"[{annotation.value.upper()}]", f"[/{annotation.value.upper()}]"})
        actual = record.text
        for marker in markers:
            actual = actual.replace(marker, "")
        expected, actual = re.sub(r"\s+", "", expected), re.sub(r"\s+", "", actual)
        if expected != actual:
            raise ValueError(f"Canonical text differs from source character data: {record.source_path}")
        checked += len(expected)
    return {"verified_records": len(records), "verified_nonwhitespace_characters": checked}
