from __future__ import annotations

import inspect
from pathlib import Path

from ecom_agent_matrix import agents as _agents  # noqa: F401
from ecom_agent_matrix.modules import skills as _skills  # noqa: F401
from ecom_agent_matrix.agents.exec.agent import execute_exec
from ecom_agent_matrix.agents.query.agent import execute_query
from ecom_agent_matrix.config.constants import AGENT_EXEC, AGENT_MASTER, AGENT_QUERY, AGENT_RAG
from ecom_agent_matrix.core.skill.skill_registry import skill_container
from ecom_agent_matrix.runtime.messaging.registry import agent_registry
from ecom_agent_matrix.modules.data_intelligence.service import DataIntelligenceService

ROOT = Path(__file__).resolve().parents[1]


def test_exactly_four_runtime_agents_are_registered():
    assert set(agent_registry.definitions) == {AGENT_MASTER, AGENT_QUERY, AGENT_EXEC, AGENT_RAG}


def test_high_risk_side_effect_skills_require_approval():
    violations = []
    for name, skill_class in skill_container.items():
        spec = skill_class.spec()
        if spec.side_effect and spec.risk_level in {"high", "critical"}:
            if not spec.approval_required:
                violations.append(name)
    assert violations == []


def test_active_agent_execution_has_no_legacy_inference():
    assert "infer_query_kind" not in inspect.getsource(execute_query)
    assert "infer_exec_kind" not in inspect.getsource(execute_exec)


def test_business_runtime_does_not_call_legacy_execute_sql():
    offenders = []
    for package in (
        ROOT / "ecom_agent_matrix" / "agents",
        ROOT / "ecom_agent_matrix" / "workflows",
    ):
        for path in package.rglob("*.py"):
            if "execute_sql(" in path.read_text():
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_core_memory_does_not_depend_on_modules_rag():
    memory_root = ROOT / "ecom_agent_matrix" / "core" / "memory"
    source = "\n".join(path.read_text() for path in memory_root.rglob("*.py"))
    assert "modules.rag" not in source


def test_generated_sql_validation_precedes_execution_in_active_service():
    source = inspect.getsource(DataIntelligenceService.analyze)
    assert source.index("self.validator.validate") < source.index("self._execute_with_repair")
    repair_source = inspect.getsource(DataIntelligenceService._execute_with_repair)
    assert "self.validator.validate" in repair_source


def test_data_analysis_has_no_new_runtime_agent():
    assert "data_analysis" not in agent_registry.definitions
    assert set(agent_registry.definitions) == {AGENT_MASTER, AGENT_QUERY, AGENT_EXEC, AGENT_RAG}
