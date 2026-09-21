"""Deterministic claim-evidence grounding checks."""

from __future__ import annotations

import re

from .models import (
    Claim,
    ClaimType,
    DocumentEvidence,
    EvidenceType,
    GroundingIssue,
    GroundingReport,
)
from .store import EvidenceStore


def validate_claims(claims: list[Claim], store: EvidenceStore) -> GroundingReport:
    issues: list[GroundingIssue] = []
    known_citations = {
        record.citation_id
        for record in store.by_type(EvidenceType.DOCUMENT)
        if isinstance(record, DocumentEvidence)
    }
    for index, claim in enumerate(claims):
        records = []
        for evidence_id in claim.evidence_ids:
            record = store.get(evidence_id)
            if record is None:
                issues.append(
                    GroundingIssue(code="MISSING_EVIDENCE", claim_index=index, detail=evidence_id)
                )
            else:
                records.append(record)
        for citation_id in claim.citation_ids:
            if citation_id not in known_citations:
                issues.append(
                    GroundingIssue(code="INVALID_CITATION", claim_index=index, detail=citation_id)
                )
        if claim.claim_type == ClaimType.FACT and not records:
            issues.append(GroundingIssue(code="UNSUPPORTED_CLAIM", claim_index=index))
        if claim.claim_type == ClaimType.CORRELATION and not any(
            record.source_type in {EvidenceType.SQL, EvidenceType.COMPUTED} for record in records
        ):
            issues.append(GroundingIssue(code="MISSING_QUANTITATIVE_EVIDENCE", claim_index=index))
        quantitative_claim = re.search(
            r"(?:\d+(?:\.\d+)?\s*%|(?:率|金额|数量|销售额|count|revenue)[^\n]{0,24}\d)",
            claim.text,
            re.I,
        )
        if (
            claim.claim_type == ClaimType.FACT
            and quantitative_claim
            and not any(
                record.source_type in {EvidenceType.SQL, EvidenceType.API, EvidenceType.COMPUTED}
                for record in records
            )
        ):
            issues.append(GroundingIssue(code="UNSUPPORTED_NUMERIC_CLAIM", claim_index=index))
        if any(record.metadata.get("contradictory") for record in records):
            issues.append(GroundingIssue(code="CONTRADICTORY_EVIDENCE", claim_index=index))
    return GroundingReport(valid=not issues, issues=issues)


__all__ = ["validate_claims"]
