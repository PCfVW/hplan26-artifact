"""Unit tests for execution plan data models.

Ported from mcp-python-ingestion v0.29.2 (tests/orchestration/test_execution_plan.py).
Change: import path mcp_python_ingestion.orchestration -> hplan_orchestrator.orchestration.
"""

import pytest
from datetime import datetime, timezone
from pydantic import ValidationError
from hplan_orchestrator.orchestration.execution_plan import (
    ExecutionStep,
    ExecutionPlan,
    ExecutionPlanResponse,
    OrchestrationMetadata,
    StepResult,
    ExecutionStatus,
)


class TestExecutionStep:
    """Tests for ExecutionStep model."""

    def test_step_creation(self):
        """Test creating a valid execution step."""
        step = ExecutionStep(
            step=1,
            action=("pickup", "block_a"),
            server="robot-server",
            tool="robot_pickup_block",
            arguments={"block": "block_a"},
            dependencies=[],
        )
        assert step.step == 1
        assert step.action == ("pickup", "block_a")
        assert step.server == "robot-server"
        assert step.tool == "robot_pickup_block"
        assert step.arguments == {"block": "block_a"}
        assert step.dependencies == []

    def test_step_with_dependencies(self):
        """Test step with dependencies on previous steps."""
        step = ExecutionStep(
            step=3,
            action=("stack", "block_a", "block_b"),
            server="robot-server",
            tool="robot_stack",
            arguments={"top": "block_a", "bottom": "block_b"},
            dependencies=[1, 2],
        )
        assert step.dependencies == [1, 2]

    def test_step_with_description(self):
        """Test step with optional description."""
        step = ExecutionStep(
            step=1,
            action=("move", "loc_a"),
            server="robot-server",
            tool="robot_move",
            description="Move robot to location A",
        )
        assert step.description == "Move robot to location A"

    def test_step_default_arguments(self):
        """Test that arguments default to empty dict."""
        step = ExecutionStep(
            step=1,
            action=("noop",),
            server="test-server",
            tool="noop_tool",
        )
        assert step.arguments == {}
        assert step.dependencies == []

    def test_step_validation_error_missing_required(self):
        """Test validation error for missing required fields."""
        with pytest.raises(ValidationError):
            ExecutionStep(step=1, action=("test",))  # Missing server and tool

    def test_step_model_dump(self):
        """Test model serialization."""
        step = ExecutionStep(
            step=1,
            action=("pickup", "block"),
            server="robot-server",
            tool="pickup",
            arguments={"item": "block"},
        )
        data = step.model_dump()
        assert data["step"] == 1
        assert data["action"] == ("pickup", "block")
        assert data["server"] == "robot-server"


class TestExecutionPlan:
    """Tests for ExecutionPlan model."""

    def test_plan_creation(self):
        """Test creating a valid execution plan."""
        steps = [
            ExecutionStep(
                step=1, action=("pickup", "a"), server="robot", tool="pickup"
            ),
            ExecutionStep(
                step=2, action=("place", "a"), server="robot", tool="place"
            ),
        ]
        plan = ExecutionPlan(
            plan_id="plan-001",
            goal="Stack blocks",
            steps=steps,
        )
        assert plan.plan_id == "plan-001"
        assert plan.goal == "Stack blocks"
        assert len(plan.steps) == 2
        assert plan.total_steps == 2

    def test_plan_auto_total_steps(self):
        """Test that total_steps is auto-calculated from steps list."""
        steps = [
            ExecutionStep(step=i, action=(f"action{i}",), server="s", tool="t")
            for i in range(1, 6)
        ]
        plan = ExecutionPlan(plan_id="test", goal="test", steps=steps)
        assert plan.total_steps == 5

    def test_plan_created_at_default(self):
        """Test that created_at defaults to current time."""
        plan = ExecutionPlan(plan_id="test", goal="test", steps=[])
        assert isinstance(plan.created_at, datetime)

    def test_plan_empty_steps(self):
        """Test plan with no steps."""
        plan = ExecutionPlan(plan_id="empty", goal="Nothing", steps=[])
        assert plan.total_steps == 0
        assert len(plan.steps) == 0


class TestOrchestrationMetadata:
    """Tests for OrchestrationMetadata model."""

    def test_metadata_creation(self):
        """Test creating orchestration metadata."""
        metadata = OrchestrationMetadata(execution_id="exec-001")
        assert metadata.execution_id == "exec-001"
        assert metadata.status == ExecutionStatus.PENDING
        assert metadata.steps_completed == 0
        assert metadata.steps_failed == 0

    def test_metadata_with_status(self):
        """Test metadata with different statuses."""
        metadata = OrchestrationMetadata(
            execution_id="exec-002",
            status=ExecutionStatus.RUNNING,
            current_step=3,
        )
        assert metadata.status == ExecutionStatus.RUNNING
        assert metadata.current_step == 3

    def test_metadata_completed(self):
        """Test completed metadata."""
        now = datetime.now(timezone.utc)
        metadata = OrchestrationMetadata(
            execution_id="exec-003",
            status=ExecutionStatus.SUCCESS,
            started_at=now,
            completed_at=now,
            steps_completed=5,
        )
        assert metadata.status == ExecutionStatus.SUCCESS
        assert metadata.steps_completed == 5

    def test_metadata_failed_with_error(self):
        """Test failed metadata with error message."""
        metadata = OrchestrationMetadata(
            execution_id="exec-004",
            status=ExecutionStatus.FAILED,
            error_message="Server timeout",
            steps_failed=1,
        )
        assert metadata.status == ExecutionStatus.FAILED
        assert metadata.error_message == "Server timeout"


class TestStepResult:
    """Tests for StepResult model."""

    def test_successful_result(self):
        """Test successful step result."""
        result = StepResult(
            step=1,
            status=ExecutionStatus.SUCCESS,
            result={"output": "done"},
            duration_ms=15.5,
        )
        assert result.step == 1
        assert result.status == ExecutionStatus.SUCCESS
        assert result.result == {"output": "done"}
        assert result.duration_ms == 15.5

    def test_failed_result(self):
        """Test failed step result."""
        result = StepResult(
            step=2,
            status=ExecutionStatus.FAILED,
            error="Connection refused",
        )
        assert result.status == ExecutionStatus.FAILED
        assert result.error == "Connection refused"
        assert result.result is None


class TestExecutionPlanResponse:
    """Tests for ExecutionPlanResponse model."""

    def test_response_creation(self):
        """Test creating an execution plan response."""
        step = ExecutionStep(
            step=1, action=("test",), server="srv", tool="tool"
        )
        plan = ExecutionPlan(plan_id="p1", goal="Test", steps=[step])
        metadata = OrchestrationMetadata(execution_id="e1")

        response = ExecutionPlanResponse(
            plan=plan,
            metadata=metadata,
            servers_required=["srv"],
        )
        assert response.requires_client_orchestration is True
        assert response.plan.plan_id == "p1"
        assert response.servers_required == ["srv"]

    def test_from_plan_response(self):
        """Test creating response from dictionary."""
        data = {
            "requires_client_orchestration": True,
            "plan": {
                "plan_id": "p2",
                "goal": "Test goal",
                "steps": [
                    {
                        "step": 1,
                        "action": ["pickup", "block"],
                        "server": "robot",
                        "tool": "pickup_tool",
                    }
                ],
            },
            "metadata": {"execution_id": "exec-123"},
            "servers_required": ["robot"],
        }
        response = ExecutionPlanResponse.from_plan_response(data)
        assert response.plan.plan_id == "p2"
        assert len(response.plan.steps) == 1

    def test_get_step(self):
        """Test getting a specific step by number."""
        steps = [
            ExecutionStep(step=1, action=("a1",), server="s", tool="t"),
            ExecutionStep(step=2, action=("a2",), server="s", tool="t"),
            ExecutionStep(step=3, action=("a3",), server="s", tool="t"),
        ]
        plan = ExecutionPlan(plan_id="p", goal="g", steps=steps)
        metadata = OrchestrationMetadata(execution_id="e")
        response = ExecutionPlanResponse(plan=plan, metadata=metadata)

        assert response.get_step(2).action == ("a2",)
        assert response.get_step(99) is None

    def test_json_schema_generation(self):
        """Test that JSON schema can be generated."""
        schema = ExecutionPlanResponse.model_json_schema()
        assert "properties" in schema
        assert "requires_client_orchestration" in schema["properties"]
        assert "plan" in schema["properties"]

