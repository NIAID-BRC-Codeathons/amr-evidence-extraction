"""Pydantic schemas for AMR extraction."""

from enum import Enum
from pydantic import BaseModel, Field


class SheetClassification(BaseModel):
    """LLM assessment of a single worksheet."""

    sheet_name: str
    contains_ast_data: bool
    has_mic_values: bool
    has_sir_calls: bool
    reasoning: str


class ColumnRole(str, Enum):
    """Semantic roles assigned to columns."""

    LOCAL_ID = "local_id"
    PUBLIC_ACCESSION = "public_accession"
    ORGANISM = "organism"
    DRUG_MIC = "drug_mic"
    DRUG_SIR = "drug_sir"
    DRUG_MIC_AND_SIR = "drug_mic_and_sir"
    METADATA = "metadata"
    SKIP = "skip"


class ColumnMapping(BaseModel):
    """Mapping of a single column to its semantic role."""

    column_name: str
    role: ColumnRole
    drug_name: str | None = None
    paired_with: str | None = None


class SheetColumnMap(BaseModel):
    """Complete column mapping for one sheet."""

    sheet_name: str
    columns: list[ColumnMapping]
    header_row_index: int | None = None
    reasoning: str


class ASTExtractionRecord(BaseModel):
    """Atomic unit of extraction: one isolate-drug AST measurement."""

    pubmed_id: str
    source_sheet: str
    isolate_name: str
    accession: str | None = None
    accession_type: str | None = None
    organism: str | None = None
    drug_raw: str
    mic_operator: str | None = None
    mic_value: str | None = None
    sir_call: str | None = None
