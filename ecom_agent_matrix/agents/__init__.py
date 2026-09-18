"""Side-load exactly four runtime agent adapters."""

from .exec import agent as exec_agent
from .master import agent as master_agent
from .query import agent as query_agent
from .rag import agent as rag_agent

__all__ = ["exec_agent", "master_agent", "query_agent", "rag_agent"]
