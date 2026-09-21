"""Master-owned evidence synthesis service; this is deliberately not an Agent."""

from __future__ import annotations

from .grounding import validate_claims
from .models import AnalysisResult, Claim, ClaimType, DocumentEvidence, EvidenceType, SQLEvidence
from .store import EvidenceStore
from ...platform.observability.metrics import metrics


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
                        "结构化指标变化与文档记录出现在同一业务分析上下文中，"
                        "但尚未建立定量关联或因果关系。"
                    ),
                    evidence_ids=[sql_records[0].id, document_records[0].id],
                    citation_ids=[document_records[0].citation_id],
                    confidence=min(sql_records[0].confidence, document_records[0].confidence, 0.75),
                    claim_type=ClaimType.CO_OCCURRENCE,
                )
            )
            uncertainties.append("当前证据只支持共现，不支持相关性或确定因果结论。")
        elif sql_records:
            uncertainties.append("未找到可用的同期文档证据，无法解释业务原因。")
        elif document_records:
            uncertainties.append("缺少结构化指标证据，无法验证变化幅度。")
        grounding = validate_claims(claims, store)
        metrics.observe_evidence("sql", len(sql_records))
        metrics.observe_evidence("document", len(document_records))
        for issue in grounding.issues:
            metrics.observe_grounding_failure(issue.code)
        facts = " ".join(claim.text for claim in claims if claim.claim_type == ClaimType.FACT)
        cooccurrence = " ".join(
            claim.text for claim in claims if claim.claim_type == ClaimType.CO_OCCURRENCE
        )
        summary = (
            f"Observed Facts: {facts or '无。'}\n"
            f"Supporting Documents: {len(document_records)} 份。\n"
            f"Co-occurring Events: {cooccurrence or '无。'}\n"
            "Hypotheses: 需要进一步定量验证。\n"
            f"Unknowns: {' '.join(uncertainties) or '无。'}\n"
            "Recommended Next Investigation: 按品类和 SKU 继续分解并验证假设。"
        )
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
