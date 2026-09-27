"""
Data models for cross-server execution plans.

These Pydantic models define the structure of execution plans returned
by python_execute_plan when execution_mode="mcp_distributed".
"""

from typing import Dict, List, Any, Optional, Tuple
from pydantic import BaseModel, Field
from datetime import datetime, timezone
from enum import Enum


def _utc_now() -> datetime:
    """Return current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)


class ExecutionStatus(str, Enum):
    """Status of an execution step or plan."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class ExecutionStep(BaseModel):
    """Single step in an execution plan."""

    step: int = Field(..., description="Step number (1-indexed)")
    action: Tuple[str, ...] = Field(..., description="GTPyhop action tuple")
    server: str = Field(..., description="Target MCP server name")
    tool: str = Field(..., description="MCP tool to invoke")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Tool arguments")
    dependencies: List[int] = Field(
        default_factory=list,
        description="List of step numbers this step depends on"
    )
    description: Optional[str] = Field(None, description="Human-readable step description")
    output_extractors: Dict[str, str] = Field(
        default_factory=dict,
        description="Map of context variable names to JSON paths for extracting output data"
    )

    model_config = {"frozen": False}


class ExecutionPlan(BaseModel):
    """Complete execution plan with multiple steps."""
    
    plan_id: str = Field(..., description="Unique identifier for this plan")
    goal: str = Field(..., description="Goal description")
    steps: List[ExecutionStep] = Field(..., description="Ordered list of execution steps")
    created_at: datetime = Field(default_factory=_utc_now)
    total_steps: int = Field(0, description="Total number of steps")

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        if self.total_steps == 0:
            object.__setattr__(self, 'total_steps', len(self.steps))

    model_config = {"frozen": False}


class OrchestrationMetadata(BaseModel):
    """Metadata about the orchestration execution."""
    
    execution_id: str = Field(..., description="Unique execution identifier")
    started_at: Optional[datetime] = Field(None, description="When execution started")
    completed_at: Optional[datetime] = Field(None, description="When execution completed")
    status: ExecutionStatus = Field(
        default=ExecutionStatus.PENDING,
        description="Current execution status"
    )
    steps_completed: int = Field(0, description="Number of steps completed")
    steps_failed: int = Field(0, description="Number of steps that failed")
    current_step: Optional[int] = Field(None, description="Currently executing step number")
    error_message: Optional[str] = Field(None, description="Error message if failed")

    model_config = {"frozen": False}


class StepResult(BaseModel):
    """Result of executing a single step."""
    
    step: int = Field(..., description="Step number that was executed")
    status: ExecutionStatus = Field(..., description="Execution status")
    result: Optional[Dict[str, Any]] = Field(None, description="Result data if successful")
    error: Optional[str] = Field(None, description="Error message if failed")
    started_at: datetime = Field(default_factory=_utc_now)
    completed_at: Optional[datetime] = Field(None)
    duration_ms: Optional[float] = Field(None, description="Execution duration in milliseconds")

    model_config = {"frozen": False}


class ExecutionPlanResponse(BaseModel):
    """
    Response from python_execute_plan when execution_mode="mcp_distributed".
    
    This response indicates that the client needs to orchestrate the execution
    across multiple MCP servers.
    """
    
    requires_client_orchestration: bool = Field(
        True,
        description="Flag indicating client-side orchestration is required"
    )
    plan: ExecutionPlan = Field(..., description="The execution plan to orchestrate")
    metadata: OrchestrationMetadata = Field(..., description="Orchestration metadata")
    servers_required: List[str] = Field(
        default_factory=list,
        description="List of MCP servers required for execution"
    )
    
    @classmethod
    def from_plan_response(cls, data: Dict[str, Any]) -> "ExecutionPlanResponse":
        """Create from raw dictionary response."""
        return cls.model_validate(data)
    
    def get_step(self, step_number: int) -> Optional[ExecutionStep]:
        """Get a specific step by number."""
        for step in self.plan.steps:
            if step.step == step_number:
                return step
        return None

    model_config = {"frozen": False}

