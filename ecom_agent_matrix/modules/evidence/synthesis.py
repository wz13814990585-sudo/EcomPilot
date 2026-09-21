"""Master-owned evidence synthesis service; this is deliberately not an Agent."""

from __future__ import annotations

from .grounding import validate_claims
from .models import AnalysisResult, Claim, ClaimType, DocumentEvidence, EvidenceType, SQLEvidence
from .store import EvidenceStore


class EvidenceSynthesisService:
    async def synthesize(self, question: str, store: EvidenceStore) -> AnalysisResult:
        claims: list[Claim] = []
        citations: list[str] = []
        sql_records = [
            record for record in store.by_type(EvidenceType.SQL) if isinstance(record, SQLEvidence)
        ]
        document_records = [
            record
            for record in store.by_type(EvidenceType.DOCUMENT)
            if isinstance(record, DocumentEvidence)
        ]
        for record in sql_records:
            first = record.rows[0] if record.rows else {}
            detail = "、".join(f"{key}={value}" for key, value in list(first.items())[:8])
            text = f"数据库查询返回 {record.row_count} 行"
            if detail:
                text += f"：{detail}"
            claims.append(
                Claim(
                    text=text + "。",
                    evidence_ids=[record.id],
                    confidence=record.confidence,
                    claim_type=ClaimType.FACT,
                )
            )
        for record in document_records[:5]:
            citations.append(record.citation_id)
            claims.append(
                Claim(
                    text=f"内部文档提到：{record.content_preview[:220]}",
                    evidence_ids=[record.id],
                    citation_ids=[record.citation_id],
                    confidence=record.confidence,
                    claim_type=ClaimType.FACT,
                )
            )
        uncertainties: list[str] = []
        if sql_records and document_records:
            claims.append(
                Claim(
                    text=(
                        "结构化数据中的指标变化与同期文档记录存在业务上的相关性，"
                        "但现有证据不足以单独证明因果关系。"
                    ),
                    evidence_ids=[sql_records[0].id, document_records[0].id],
                    citation_ids=[document_records[0].citation_id],
                    confidence=min(sql_records[0].confidence, document_records[0].confidence, 0.75),
                    claim_type=ClaimType.CORRELATION,
                )
            )
            uncertainties.append("当前证据只支持相关性，不支持确定因果结论。")
        elif sql_records:
            uncertainties.append("未找到可用的同期文档证据，无法解释业务原因。")
        elif document_records:
            uncertainties.append("缺少结构化指标证据，无法验证变化幅度。")
        grounding = validate_claims(claims, store)
        summary = " ".join(claim.text for claim in claims[:3]) or "当前没有足够证据回答该问题。"
        return AnalysisResult(
            summary=summary,
            claims=claims,
            uncertainties=uncertainties,
            citations=list(dict.fromkeys(citations)),
            recommended_next_steps=["按地区、品类和 SKU 进一步分解指标并验证假设。"]
            if sql_records
            else [],
            grounding=grounding,
        )


evidence_synthesis_service = EvidenceSynthesisService()


__all__ = ["EvidenceSynthesisService", "evidence_synthesis_service"]
