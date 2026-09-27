"""
Orchestration middleware for cross-server MCP plan execution.

This module provides middleware that intercepts MCP tool calls and
automatically orchestrates execution plans across multiple servers.
"""

from .middleware import OrchestrationMiddleware
from .execution_plan import (
    ExecutionStep,
    ExecutionPlan,
    ExecutionPlanResponse,
    OrchestrationMetadata,
)

__all__ = [
    "OrchestrationMiddleware",
    "ExecutionStep",
    "ExecutionPlan",
    "ExecutionPlanResponse",
    "OrchestrationMetadata",
]

__version__ = "0.29.2"

