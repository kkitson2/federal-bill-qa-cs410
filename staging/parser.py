"""Faithful canonical text with explicit editorial change markers.

Offsets refer to the normalized, marked canonical text. XML source paths and the
archived source hash allow inspection of the original representation.
"""

import re

from lxml import etree

from billbridge_data.contracts import Annotation, Block, SourceSpec, XmlSection
from billbridge_data.files import digest


PARSER_VERSION = "legacy-marked-2"
NAVIGATION = {"toc", "toc-entry", "table-of-contents"}
HIERARCHY = {"division", "title", "subtitle", "chapter", "subchapter", "part", "subpart"}
INLINE = {"text", "enum", "header", "amendment-instruction", "instruction", "title-amends"}


def normalized(text):
    return " ".join((text or "").split())


def element_text(node):
    return normalized("".join(node.itertext())) if node is not None else ""


class Renderer:
    def __init__(self, tree, excluded=()):
        self.tree = tree
        self.excluded = set(excluded)
        self.parts = []
        self.blocks = []
        self.annotations = []
        self.position = 0

    def emit(self, text, node):
        if not text:
            return
        self.parts.append(text)
        self.blocks.append(Block(source_path=self.tree.getpath(node), start=self.position,
                                 end=self.position + len(text), text=text))
        self.position += len(text)

    def inline(self, node):
        if node in self.excluded or node.tag in NAVIGATION:
            return
        change = node.get("changed")
        start = self.position
        if change:
            self.emit(f" [{change.upper()}] ", node)
        # Preserve inline whitespace/punctuation before normalizing each source
        # fragment. A literal inter-element space must not disappear.
        if node.text:
            self.emit(re.sub(r"\s+", " ", node.text), node)
        for child in node:
            self.inline(child)
            if child.tail:
                self.emit(re.sub(r"\s+", " ", child.tail), child)
        if change:
            self.emit(f" [/{change.upper()}] ", node)
            self.annotations.append(Annotation(kind="editorial_change", value=change,
                                               source_path=self.tree.getpath(node), start=start, end=self.position))
        if node.tag in {"external-xref", "internal-xref"} and self.position > start:
            reference = node.get("legal-doc") or node.get("ref-type") or node.get("idref") or "reference"
            self.annotations.append(Annotation(kind="reference", value=reference,
                                               source_path=self.tree.getpath(node), start=start, end=self.position))

    def render(self, node):
        if node in self.excluded or node.tag in NAVIGATION:
            return
        if node.tag in INLINE or len(node) == 0:
            if element_text(node):
                self.inline(node)
                self.emit("\n", node)
            return
        start = self.position
        change = node.get("changed")
        table = node.tag == "table"
        if change:
            self.emit(f"[{change.upper()}]\n", node)
        if table:
            self.emit("[TABLE]\n", node)
        if node.text and node.text.strip():
            self.emit(normalized(node.text) + "\n", node)
        if node.tag in {"row", "tr"}:
            for index, child in enumerate(node):
                if index:
                    self.emit("\t", node)
                self.inline(child)
            self.emit("\n", node)
        else:
            for child in node:
                self.render(child)
                if child.tail and child.tail.strip():
                    self.emit(normalized(child.tail) + "\n", child)
        if table:
            self.emit("[/TABLE]\n", node)
        if change:
            self.emit(f"[/{change.upper()}]\n", node)
            self.annotations.append(Annotation(kind="editorial_change", value=change,
                                               source_path=self.tree.getpath(node), start=start, end=self.position))
        if table and self.position > start:
            self.annotations.append(Annotation(kind="table", value="rows separated by newlines; cells by tabs",
                                               source_path=self.tree.getpath(node), start=start, end=self.position))

    @property
    def text(self):
        return "".join(self.parts)


def parse_xml(xml: bytes, spec: SourceSpec) -> list[XmlSection]:
    root = etree.fromstring(xml, etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=True))
    if root.tag not in {"bill", "amendment-doc"}:
        raise ValueError(f"Unsupported document root: {root.tag}")
    if any(isinstance(node, etree._Entity) for node in root.iter()):
        raise ValueError("Entity references are unsupported")
    tree = root.getroottree()
    source_hash = digest(xml)
    body_tags = {"legis-body", "engrossed-amendment-body", "amendment-body"}
    bodies = [node for node in root if node.tag in body_tags]
    if not bodies:
        raise ValueError("Document has no recognized legislative body")
    outer_sections = []
    for body in bodies:
        for node in body.iter("section"):
            if not any(parent.tag == "section" for parent in node.iterancestors()):
                outer_sections.append(node)
    context_parts = []
    # Title-change instructions can sit after the body in engrossed amendments.
    context_nodes = bodies + [node for node in root if node.tag == "title-amends"]
    for body in context_nodes:
        renderer = Renderer(tree, outer_sections)
        renderer.render(body)
        # Excluding the section trees retains document-level instructions and
        # hierarchy headings. They remain available to consumers explicitly.
        if renderer.text.strip():
            context_parts.append((body, renderer))
    amendment_context = "".join(renderer.text for _, renderer in context_parts) if root.tag == "amendment-doc" else ""
    source_title = root.findtext(".//{http://purl.org/dc/elements/1.1/}title") or ""
    records = []

    def make_record(node, renderer, record_type):
        hierarchy = []
        for parent in reversed(list(node.iterancestors())):
            if parent.tag in HIERARCHY:
                hierarchy.append(" ".join(filter(None, [parent.tag, element_text(parent.find("enum")), element_text(parent.find("header"))])))
        number = element_text(node.find("enum")) or "unnumbered"
        heading = element_text(node.find("header"))
        label = f"section {number}" if record_type == "section" else "document context"
        hierarchy.append(label)
        path = tree.getpath(node)
        source_id = f"{spec.package_id}:{source_hash[:16]}:{digest((PARSER_VERSION + ':' + path).encode())[:16]}"
        return XmlSection(
            section_id=source_id, package_id=spec.package_id, congress=spec.congress,
            bill_type=spec.bill_type, bill_number=spec.number, version=spec.version,
            number=number, heading=heading, hierarchy=hierarchy,
            source_path=path, source_hash=source_hash, text=renderer.text, blocks=renderer.blocks,
            parser_version=PARSER_VERSION, document_type=root.tag, record_type=record_type,
            annotations=renderer.annotations, amendment_context=amendment_context, source_document_title=source_title,
        )

    for node in outer_sections:
        renderer = Renderer(tree)
        # Change markings on a wrapper also apply to its section descendants.
        inherited = [parent.get("changed") for parent in node.iterancestors() if parent.get("changed")]
        for change in reversed(inherited):
            renderer.emit(f"[{change.upper()}]\n", node)
        renderer.render(node)
        for change in inherited:
            renderer.emit(f"[/{change.upper()}]\n", node)
            renderer.annotations.append(Annotation(kind="editorial_change", value=change,
                                                   source_path=tree.getpath(node), start=0, end=renderer.position))
        if renderer.text.strip():
            records.append(make_record(node, renderer, "section"))
    for node, renderer in context_parts:
        records.append(make_record(node, renderer, "document_context"))
    # Some amendment documents have instructions and no numbered sections.
    if not records:
        raise ValueError("No legislative text extracted")
    return records
