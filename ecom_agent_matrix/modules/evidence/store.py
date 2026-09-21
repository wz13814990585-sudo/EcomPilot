"""Bounded in-request evidence store."""

from __future__ import annotations

from .models import EvidenceRecord, EvidenceType


class EvidenceStore:
    def __init__(self, *, tenant_id: str, store_id: str, max_records: int = 50) -> None:
        self.tenant_id = tenant_id
        self.store_id = store_id
        self.max_records = max(1, max_records)
        self._records: dict[str, EvidenceRecord] = {}

    def add(self, record: EvidenceRecord) -> EvidenceRecord:
        if record.tenant_id != self.tenant_id or record.store_id != self.store_id:
            raise PermissionError("CROSS_TENANT_EVIDENCE")
        if record.id not in self._records and len(self._records) >= self.max_records:
            raise ValueError("EVIDENCE_STORE_FULL")
        self._records[record.id] = record
        return record

    def get(self, evidence_id: str) -> EvidenceRecord | None:
        return self._records.get(evidence_id)

    def all(self) -> list[EvidenceRecord]:
        return list(self._records.values())

    def by_type(self, evidence_type: EvidenceType) -> list[EvidenceRecord]:
        return [record for record in self._records.values() if record.source_type == evidence_type]

    def bounded_package(self, *, max_records: int = 20, max_chars: int = 8000) -> list[dict]:
        package: list[dict] = []
        used = 0
        for record in self.all()[: max(1, max_records)]:
            value = record.model_dump(mode="json")
            if "rows" in value:
                value["rows"] = value["rows"][:20]
            if "content_preview" in value:
                value["content_preview"] = value["content_preview"][:500]
            size = len(str(value))
            if package and used + size > max_chars:
                break
            package.append(value)
            used += size
        return package


__all__ = ["EvidenceStore"]
