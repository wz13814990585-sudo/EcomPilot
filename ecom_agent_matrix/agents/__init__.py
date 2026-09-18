"""Side-load exactly four runtime agent adapters."""

from ecom_agent_matrix.agents.exec import agent as exec_agent
from ecom_agent_matrix.agents.master import agent as master_agent
from ecom_agent_matrix.agents.query import agent as query_agent
from ecom_agent_matrix.agents.rag import agent as rag_agent

__all__ = ["exec_agent", "master_agent", "query_agent", "rag_agent"]
