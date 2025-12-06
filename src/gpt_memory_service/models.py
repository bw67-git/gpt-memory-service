"""Pydantic models for the GPT Memory Service.

This module centralizes all schemas used by the API, adding strong typing,
validation and descriptive documentation to aid downstream consumers.
"""

import re
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

ISO8601_TS_HELP = (
    "Use an ISO8601 timestamp (e.g., 2024-12-31T23:59:59Z); timezone offsets like -06:00"
    " are also valid."
)


class PlanningDay(str, Enum):
    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"


class WeeklyPlanningSettings(BaseModel):
    """Preferences that guide weekly planning flows."""

    planning_day: Optional[PlanningDay] = Field(
        default=None,
        description="Preferred day of week for planning.",
    )
    planning_time_local: Optional[str] = Field(
        default=None,
        description="Preferred local time for planning, HH:MM (24h).",
    )
    calendar_link: Optional[str] = Field(
        default=None,
        description="Reference calendar to anchor planning sessions.",
    )
    timezone: Optional[str] = Field(
        default=None,
        description="IANA timezone identifier for the user (e.g., America/New_York).",
    )

    @field_validator("planning_time_local")
    @classmethod
    def validate_planning_time(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        if not re.fullmatch(r"\d{2}:\d{2}", value):
            raise ValueError("planning_time_local must be HH:MM in 24-hour time.")
        hours, minutes = map(int, value.split(":"))
        if not (0 <= hours <= 23 and 0 <= minutes <= 59):
            raise ValueError("planning_time_local must represent a valid time of day.")
        return value


class Profile(BaseModel):
    """Profile metadata used to personalize the memory experience."""

    name: Optional[str] = Field(default=None, description="Display name for the user.")
    role: Optional[str] = Field(default=None, description="Short role descriptor for context.")
    preferences: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary, user-defined preferences for prompting and formatting.",
    )
    weekly_planning: WeeklyPlanningSettings = Field(
        default_factory=WeeklyPlanningSettings,
        description="Recurring planning preferences to orchestrate weekly reviews.",
    )


class TaskStatus(str, Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    DELEGATED = "delegated"


class DecisionType(str, Enum):
    STRATEGIC = "strategic"
    TACTICAL = "tactical"
    PROCESS = "process"


class TimeblockType(str, Enum):
    FOCUS = "focus"
    MEETING = "meeting"
    BREAK = "break"
    ADMIN = "admin"


class Task(BaseModel):
    """Actionable item the assistant should keep top-of-mind."""

    id: Optional[str] = Field(default=None, description="Stable identifier for deduplication.")
    title: str = Field(..., description="Human readable task summary.")
    status: TaskStatus = Field(default=TaskStatus.TODO, description="Lifecycle state of the task.")
    due_at: Optional[datetime] = Field(
        default=None, description="Optional due date. " + ISO8601_TS_HELP
    )
    notes: List[str] = Field(default_factory=list, description="Supporting notes or context.")


class Decision(BaseModel):
    """Recorded decision with explicit categorization for downstream synthesis."""

    id: Optional[str] = Field(default=None, description="Unique identifier for this decision.")
    summary: str = Field(..., description="What was decided.")
    rationale: Optional[str] = Field(default=None, description="Short reasoning behind the choice.")
    decision_type: DecisionType = Field(
        default=DecisionType.TACTICAL,
        description=(
            "Classify the decision: use strategic for long-term direction, tactical for"
            " near-term actions, and process for workflow/role agreements."
        ),
    )
    decided_at: Optional[datetime] = Field(
        default=None, description="When the decision occurred. " + ISO8601_TS_HELP
    )


class Timeblock(BaseModel):
    """Calendar block the assistant should respect."""

    id: Optional[str] = Field(default=None, description="Identifier used to sync with calendars.")
    label: str = Field(..., description="Short label for the block.")
    block_type: TimeblockType = Field(
        default=TimeblockType.FOCUS,
        description=(
            "Type of time being reserved: focus for deep work, meeting for"
            " synchronous sessions, break for rest, admin for coordination chores."
        ),
    )
    start_at: datetime = Field(
        ..., description="Start time for the block. " + ISO8601_TS_HELP
    )
    end_at: datetime = Field(..., description="End time for the block. " + ISO8601_TS_HELP)

    @model_validator(mode="after")
    def validate_time_order(self) -> "Timeblock":
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at.")
        return self


class WorkingMemory(BaseModel):
    """Short-term memory that powers fast contextual responses."""

    current_focus_thread: str = Field(
        default="",
        description="Active focus thread identifier used to disambiguate context.",
    )
    active_priorities: List[str] = Field(
        default_factory=list,
        description="Key priorities the assistant should emphasize in responses.",
    )
    tasks: List[Task] = Field(default_factory=list, description="Actionable to-do items.")
    decisions: List[Decision] = Field(
        default_factory=list, description="Decisions that inform upcoming work."
    )
    timeblocks: List[Timeblock] = Field(
        default_factory=list, description="Upcoming or ongoing calendar timeblocks."
    )


class ProjectStatus(str, Enum):
    PLANNING = "planning"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"


class Project(BaseModel):
    """Project the user is working on with goals and status."""

    id: Optional[str] = Field(default=None, description="Stable project identifier.")
    name: str = Field(..., description="Project name.")
    objectives: List[str] = Field(default_factory=list, description="Goals or success criteria.")
    status: Optional[ProjectStatus] = Field(
        default=None, description="Current project status."
    )


class System(BaseModel):
    """System, tool, or integration the user relies on."""

    id: Optional[str] = Field(default=None, description="System identifier.")
    name: str = Field(..., description="Name of the system or integration.")
    notes: List[str] = Field(
        default_factory=list, description="Notes about configuration or usage."
    )


class Stakeholder(BaseModel):
    """Key person with a role or relationship to the user."""

    id: Optional[str] = Field(default=None, description="Stakeholder identifier or handle.")
    name: str = Field(..., description="Stakeholder name.")
    role: Optional[str] = Field(default=None, description="Role or relationship to the user.")
    contact: Optional[str] = Field(default=None, description="Preferred contact channel.")


class LongTermKnowledge(BaseModel):
    """Durable knowledge that rarely changes but remains critical."""

    projects: List[Project] = Field(default_factory=list, description="Projects in flight.")
    stakeholders: List[Stakeholder] = Field(
        default_factory=list, description="Important people and their roles."
    )
    systems: List[System] = Field(default_factory=list, description="Systems/tools in use.")


class EventType(str, Enum):
    MEETING = "meeting"
    SNAPSHOT = "snapshot"
    NOTE = "note"


class Event(BaseModel):
    """Structured event in the user's memory timeline (meetings, snapshots, notes)."""

    id: Optional[str] = Field(
        default=None,
        description=(
            "Stable identifier for deduplication. Use meeting-YYYYMMDD-slug for meetings "
            "or snapshot-YYYYMMDD-HHMMSS for snapshots. For snapshots, HHMMSS is 24-hour"
            " time without separators (e.g., 'snapshot-20251203-130501')."
        ),
    )
    type: EventType = Field(
        default=EventType.NOTE,
        description=(
            "Classification of the event: meeting for live discussions, snapshot for"
            " assistant-authored summaries, note for quick context drops."
        ),
    )
    title: Optional[str] = Field(default=None, description="Human-friendly title.")
    summary: Optional[str] = Field(default=None, description="Short synopsis of the event.")
    occurred_at: Optional[datetime] = Field(
        default=None, description="When the event happened. " + ISO8601_TS_HELP
    )
    captured_at: Optional[datetime] = Field(
        default=None,
        description="When the assistant captured the event. " + ISO8601_TS_HELP,
    )
    decisions: List[Decision] = Field(
        default_factory=list,
        description="Structured decisions captured from the event.",
    )
    tasks: List[Task] = Field(
        default_factory=list,
        description="Actionable tasks that surfaced during the event.",
    )
    notes: List[str] = Field(
        default_factory=list,
        description="Lightweight notes that do not fit task or decision structure.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Structured metadata such as participants or tags."
    )

    @model_validator(mode="after")
    def validate_id(self) -> "Event":
        if self.id is None:
            return self
        if self.type == EventType.MEETING:
            pattern = r"meeting-\d{8}-[a-z0-9-]+"
            if not re.fullmatch(pattern, self.id):
                raise ValueError("Meeting ids must use meeting-YYYYMMDD-slug format.")
        if self.type == EventType.SNAPSHOT:
            pattern = r"snapshot-\d{8}-\d{6}"
            if not re.fullmatch(pattern, self.id):
                raise ValueError("Snapshot ids must use snapshot-YYYYMMDD-HHMMSS format.")
        return self


class UserMemory(BaseModel):
    """Complete memory state for a single user."""

    user_id: str = Field(..., description="Unique user identifier.")
    profile: Profile = Field(default_factory=Profile, description="User profile and preferences.")
    working_memory: WorkingMemory = Field(
        default_factory=WorkingMemory,
        description="Short-term working memory backing quick responses.",
    )
    long_term_knowledge: LongTermKnowledge = Field(
        default_factory=LongTermKnowledge,
        description="Durable knowledge about projects, people, and systems.",
    )
    events: List[Event] = Field(
        default_factory=list,
        description="Timeline of meetings, snapshots, and notes.",
    )


class MemoryCreate(BaseModel):
    profile: Optional[Profile] = None
    working_memory: Optional[WorkingMemory] = None
    long_term_knowledge: Optional[LongTermKnowledge] = None
    events: List[Event] = Field(default_factory=list)


class ProfilePatch(BaseModel):
    """Partial update shape for profile metadata."""

    name: Optional[str] = Field(
        default=None,
        description="Set to update the display name; omit to leave unchanged.",
    )
    role: Optional[str] = Field(
        default=None, description="Update the short role descriptor if provided."
    )
    preferences: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Replace or extend user-defined preferences for prompting and formatting.",
    )
    weekly_planning: Optional[WeeklyPlanningSettings] = Field(
        default=None,
        description="Patch recurring planning preferences; omit to keep existing settings.",
    )


class WorkingMemoryPatch(BaseModel):
    """Partial update shape for working memory."""

    current_focus_thread: Optional[str] = Field(
        default=None,
        description="Overwrite the active focus thread identifier when provided.",
    )
    active_priorities: Optional[List[str]] = Field(
        default=None,
        description="Replace the list of priorities; omit to leave priorities unchanged.",
    )
    tasks: Optional[List[Task]] = Field(
        default=None,
        description="Replace tasks with the provided list; omit to keep current tasks.",
    )
    decisions: Optional[List[Decision]] = Field(
        default=None,
        description="Replace decisions with the provided list; omit to leave untouched.",
    )
    timeblocks: Optional[List[Timeblock]] = Field(
        default=None,
        description="Replace timeblocks with the provided list; omit to keep current blocks.",
    )


class LongTermKnowledgePatch(BaseModel):
    """Partial update shape for durable knowledge."""

    projects: Optional[List[Project]] = Field(
        default=None,
        description="Replace known projects; omit to preserve existing project data.",
    )
    stakeholders: Optional[List[Stakeholder]] = Field(
        default=None,
        description="Replace stakeholders; omit to keep the current stakeholder list.",
    )
    systems: Optional[List[System]] = Field(
        default=None,
        description="Replace systems and integrations; omit to leave unchanged.",
    )


class MemoryPatch(BaseModel):
    profile: Optional[ProfilePatch] = Field(
        default=None, description="Patch the user profile; omit for no profile changes."
    )
    working_memory: Optional[WorkingMemoryPatch] = Field(
        default=None,
        description="Patch short-term working memory fields; omit to leave untouched.",
    )
    long_term_knowledge: Optional[LongTermKnowledgePatch] = Field(
        default=None,
        description="Patch durable knowledge such as projects, stakeholders, or systems.",
    )
    events: Optional[List[Event]] = Field(
        default=None,
        description="Replace or append to the events timeline depending on events_overwrite.",
    )
    events_overwrite: bool = Field(
        default=False,
        description="Replace the entire events array when true; append/merge otherwise.",
    )


__all__ = [
    "Decision",
    "DecisionType",
    "Event",
    "EventType",
    "LongTermKnowledge",
    "MemoryCreate",
    "MemoryPatch",
    "PlanningDay",
    "Profile",
    "ProfilePatch",
    "Project",
    "ProjectStatus",
    "Stakeholder",
    "System",
    "Task",
    "TaskStatus",
    "Timeblock",
    "TimeblockType",
    "UserMemory",
    "WeeklyPlanningSettings",
    "WorkingMemoryPatch",
    "WorkingMemory",
    "LongTermKnowledgePatch",
]
