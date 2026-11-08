"""Pair boundaries: source-derived sections are independent of embedding models."""

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceSpec(StrictModel):
    congress: int
    bill_type: str
    number: int
    version: str

    @property
    def package_id(self) -> str:
        return f"BILLS-{self.congress}{self.bill_type}{self.number}{self.version}"


class Block(StrictModel):
    source_path: str
    start: int
    end: int
    text: str


class Annotation(StrictModel):
    kind: str
    value: str
    source_path: str
    start: int
    end: int


class XmlSection(StrictModel):
    """Fields derived from one XML document and its source package identity."""
    section_id: str
    package_id: str
    congress: int
    bill_type: str
    bill_number: int
    version: str
    number: str
    heading: str
    hierarchy: list[str]
    source_path: str
    source_hash: str
    text: str
    blocks: list[Block]
    parser_version: str
    document_type: str = "bill"
    record_type: str = "section"
    annotations: list[Annotation] = Field(default_factory=list)
    amendment_context: str = ""
    source_document_title: str = ""

    @model_validator(mode="after")
    def validate_spans(self):
        cursor = 0
        for b in self.blocks:
            if b.start != cursor or self.text[b.start:b.end] != b.text or b.end <= b.start:
                raise ValueError("Blocks must partition canonical section text exactly")
            cursor = b.end
        if cursor != len(self.text) or not self.text:
            raise ValueError("Incomplete or empty canonical section")
        for annotation in self.annotations:
            if not 0 <= annotation.start < annotation.end <= len(self.text):
                raise ValueError("Annotation outside canonical text")
        return self


class Section(XmlSection):
    """Published record after source reconciliation."""

    version_label: str
    version_date: str | None
    publication_date: str | None
    bill_latest_action: str
    title: str
    citation: str
    source_url: str
    source_xml_url: str
