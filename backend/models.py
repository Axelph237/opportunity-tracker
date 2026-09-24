"""Pydantic models for every entity exposed by the API."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

SourceType = Literal["job_board", "company_careers", "research_program", "aggregator", "university", "government"]
ScrapeMethod = Literal["html", "api", "search_query"]
OpportunityType = Literal["internship", "job", "research", "grad_program", "fellowship", "other"]
ExperienceLevel = Literal["entry", "mid", "senior", "student", "postdoc", "any"]
ApplicationStatus = Literal[
    "bookmarked", "planning_to_apply", "applied", "assessment",
    "interview", "offer", "rejected", "withdrawn", "closed",
]
ProposalStatus = Literal["pending", "approved", "rejected"]

APPLICATION_STATUSES: list[str] = list(ApplicationStatus.__args__)  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- sources

class SourceBase(BaseModel):
    name: str
    url: str
    type: SourceType
    scrape_method: ScrapeMethod = "html"
    search_query: Optional[str] = None
    active: bool = True
    notes: Optional[str] = None


class SourceCreate(SourceBase):
    added_by: Literal["user", "claude"] = "user"
    pending_approval: bool = False


class SourceUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    type: Optional[SourceType] = None
    scrape_method: Optional[ScrapeMethod] = None
    search_query: Optional[str] = None
    active: Optional[bool] = None
    pending_approval: Optional[bool] = None
    notes: Optional[str] = None


class Source(SourceBase):
    id: int
    last_scraped: Optional[str] = None
    last_result_count: Optional[int] = None
    # 'ok' | 'blocked' | 'error' — how the most recent scrape attempt ended.
    last_status: Optional[str] = None
    last_error: Optional[str] = None
    date_added: Optional[str] = None
    added_by: str = "user"
    pending_approval: bool = False


# --------------------------------------------------------------------- opportunities

class Opportunity(BaseModel):
    id: int
    title: str
    organization: str
    type: OpportunityType
    location: Optional[str] = None
    remote: bool = False
    url: str
    description: Optional[str] = None
    deadline: Optional[str] = None
    date_found: Optional[str] = None
    source_id: Optional[int] = None
    source_name: Optional[str] = None
    relevance_score: Optional[float] = None
    relevance_summary: Optional[str] = None
    skill_matches: list[str] = Field(default_factory=list)
    experience_level: Optional[ExperienceLevel] = None
    strong_match: bool = False
    tags: list[str] = Field(default_factory=list)
    notes: Optional[str] = None
    is_active: bool = True
    last_seen: Optional[str] = None
    application_id: Optional[int] = None
    application_status: Optional[str] = None
    advice_generated_at: Optional[str] = None
    resume_instance_id: Optional[int] = None
    resume_instance_name: Optional[str] = None


class ResumeRequirement(BaseModel):
    requirement: str
    importance: Literal["required", "preferred", "nice_to_have"] = "preferred"
    status: Literal["met", "partial", "gap", "unknown"] = "unknown"
    evidence: Optional[str] = None


class ResumeAdjustment(BaseModel):
    section: str
    current: Optional[str] = None
    suggested: str
    rationale: Optional[str] = None
    priority: Literal["high", "medium", "low"] = "medium"


class ResumeAdvice(BaseModel):
    opportunity_id: int
    generated_at: Optional[str] = None
    resume_filename: Optional[str] = None
    stale: bool = False
    fit_summary: Optional[str] = None
    fit_score: Optional[float] = None
    requirements: list[ResumeRequirement] = Field(default_factory=list)
    adjustments: list[ResumeAdjustment] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    talking_points: list[str] = Field(default_factory=list)


class RoleGroup(BaseModel):
    label: str
    count: int = 0
    description: Optional[str] = None
    example_titles: list[str] = Field(default_factory=list)


class LandscapeRequirement(BaseModel):
    requirement: str
    frequency: Optional[str] = None
    status: Literal["met", "partial", "gap", "unknown"] = "unknown"
    evidence: Optional[str] = None
    gap_note: Optional[str] = None


class RecommendedSkill(BaseModel):
    skill: str
    why: Optional[str] = None
    unlocks: Optional[str] = None
    effort: Optional[str] = None
    priority: Literal["high", "medium", "low"] = "medium"


class RoleAnalysis(BaseModel):
    id: int
    generated_at: Optional[str] = None
    edited_at: Optional[str] = None
    scope: Optional[str] = None
    opportunity_count: int = 0
    resume_filename: Optional[str] = None
    summary: Optional[str] = None
    role_groups: list[RoleGroup] = Field(default_factory=list)
    requirements: list[LandscapeRequirement] = Field(default_factory=list)
    recommended_skills: list[RecommendedSkill] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)


class RoleAnalysisRequest(BaseModel):
    """Filters selecting which listings the aggregate analysis covers."""

    type: Optional[list[OpportunityType]] = None
    strong_match: Optional[bool] = None
    experience_level: Optional[list[ExperienceLevel]] = None
    source_id: Optional[int] = None
    search: Optional[str] = None
    status: Optional[str] = None
    limit: int = Field(default=25, ge=1, le=40)


class RoleAnalysisUpdate(BaseModel):
    """Hand-edits to a stored analysis. Every field is replaced wholesale."""

    scope: Optional[str] = None
    summary: Optional[str] = None
    role_groups: Optional[list[RoleGroup]] = None
    requirements: Optional[list[LandscapeRequirement]] = None
    recommended_skills: Optional[list[RecommendedSkill]] = None
    strengths: Optional[list[str]] = None


class OpportunityUpdate(BaseModel):
    """Manual edits to a listing. Only the fields sent are changed."""

    title: Optional[str] = None
    organization: Optional[str] = None
    type: Optional[OpportunityType] = None
    location: Optional[str] = None
    remote: Optional[bool] = None
    url: Optional[str] = None
    description: Optional[str] = None
    deadline: Optional[str] = None
    experience_level: Optional[ExperienceLevel] = None
    relevance_summary: Optional[str] = None
    skill_matches: Optional[list[str]] = None
    tags: Optional[list[str]] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None
    relevance_score: Optional[float] = None
    # Explicit null unlinks the listing from whichever resume it pointed at.
    resume_instance_id: Optional[int] = None

    @field_validator("title", "organization", "url")
    @classmethod
    def _required_text(cls, value: Optional[str]) -> Optional[str]:
        # These three are NOT NULL in the schema, so an empty edit must be refused
        # here rather than becoming a 500 from SQLite.
        if value is not None and not value.strip():
            raise ValueError("cannot be empty")
        return value.strip() if value is not None else None


class OpportunityDetail(Opportunity):
    application: Optional["Application"] = None


# ---------------------------------------------------------------------- applications

class Contact(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = None


class ApplicationCreate(BaseModel):
    opportunity_id: int
    status: ApplicationStatus = "bookmarked"
    notes: Optional[str] = None


class ApplicationUpdate(BaseModel):
    status: Optional[ApplicationStatus] = None
    date_applied: Optional[str] = None
    deadline_override: Optional[str] = None
    cover_letter_notes: Optional[str] = None
    contacts: Optional[list[Contact]] = None
    notes: Optional[str] = None


class Application(BaseModel):
    id: int
    opportunity_id: int
    status: ApplicationStatus
    date_bookmarked: Optional[str] = None
    date_applied: Optional[str] = None
    deadline_override: Optional[str] = None
    cover_letter_notes: Optional[str] = None
    contacts: list[Contact] = Field(default_factory=list)
    notes: Optional[str] = None
    last_updated: Optional[str] = None
    opportunity: Optional[Opportunity] = None


# ------------------------------------------------------------------ source proposals

class SourceProposal(BaseModel):
    id: int
    name: str
    url: str
    type: str
    scrape_method: str = "html"
    rationale: Optional[str] = None
    confidence: Optional[float] = None
    date_proposed: Optional[str] = None
    status: ProposalStatus = "pending"


class DiscoveryRequest(BaseModel):
    count: int = Field(default=12, ge=1, le=25)
    focus: Optional[str] = None

    @field_validator("focus")
    @classmethod
    def _strip(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value else None


# ----------------------------------------------------------------------- walten

WaltenMode = Literal["assistant", "engineer"]


class WaltenToolCall(BaseModel):
    tool: Optional[str] = None
    detail: Optional[str] = None
    at: Optional[str] = None


class WaltenMessage(BaseModel):
    id: int
    session_id: int
    role: Literal["user", "assistant"]
    phase: Literal["plan", "apply"] = "plan"
    content: Optional[str] = None
    tool_calls: list[WaltenToolCall] = Field(default_factory=list)
    cost_usd: Optional[float] = None
    duration_ms: Optional[int] = None
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    needs_approval: bool = False
    resolved: bool = False
    error: Optional[str] = None
    created_at: Optional[str] = None
    # The commit taken just before this message was sent, and whether restoring
    # it would actually change anything on disk.
    snapshot_sha: Optional[str] = None
    can_undo: bool = False


class WaltenUndoPreview(BaseModel):
    can_undo: bool = False
    count: int = 0
    files: list[str] = Field(default_factory=list)
    later_messages: int = 0
    error: Optional[str] = None


class WaltenUndoResult(BaseModel):
    ok: bool = True
    count: int = 0
    files: list[str] = Field(default_factory=list)


class WaltenSession(BaseModel):
    id: int
    title: str
    mode: WaltenMode = "assistant"
    model: str = "sonnet"
    context_files: list[str] = Field(default_factory=list)
    context_urls: list[str] = Field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    message_count: int = 0


class WaltenSessionDetail(WaltenSession):
    messages: list[WaltenMessage] = Field(default_factory=list)
    running: bool = False
    live: Optional[dict[str, Any]] = None


class WaltenSessionCreate(BaseModel):
    title: Optional[str] = None
    mode: WaltenMode = "assistant"
    model: str = "sonnet"


class WaltenSessionUpdate(BaseModel):
    title: Optional[str] = None
    mode: Optional[WaltenMode] = None
    model: Optional[str] = None
    context_files: Optional[list[str]] = None
    context_urls: Optional[list[str]] = None


class WaltenPrompt(BaseModel):
    prompt: str = Field(min_length=1)


# -------------------------------------------------------------------------- scraping

class ScrapeLog(BaseModel):
    id: int
    source_id: Optional[int] = None
    source_name: Optional[str] = None
    timestamp: str
    status: Literal["success", "error"]
    new_count: int = 0
    error_message: Optional[str] = None


class ScrapeRunSummary(BaseModel):
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    sources_scraped: int = 0
    new_opportunities: int = 0
    dead_links_skipped: int = 0
    errors: int = 0
    # Sources the host refused (403, 429, …). A subset of `errors`, not an
    # addition to it — a blocked source is still a source that did not scrape.
    blocked: int = 0
    running: bool = False
    detail: list[dict[str, Any]] = Field(default_factory=list)


class ScrapeStatus(BaseModel):
    running: bool = False
    last_run: Optional[str] = None
    next_run: Optional[str] = None
    cron_schedule: Optional[str] = None
    last_summary: Optional[ScrapeRunSummary] = None


# -------------------------------------------------------------------------- settings

class SettingsUpdate(BaseModel):
    cron_schedule: Optional[str] = None
    model: Optional[str] = None
    max_chunks_per_source: Optional[int] = None
    request_timeout_seconds: Optional[int] = None
    domain_delay_seconds: Optional[int] = None
    verify_listing_urls: Optional[bool] = None
    walten_name: Optional[str] = None
    walten_icon: Optional[str] = None
    claude_bin: Optional[str] = None
    latex_bin: Optional[str] = None
    onboarding_complete: Optional[bool] = None


class LatexIssue(BaseModel):
    """A known reason this source will not compile with the engine we ship."""

    id: str
    title: str
    detail: str
    line: int
    snippet: str


class ResumeTexStatus(BaseModel):
    """The uploaded LaTeX source, which is separate from the scored document."""

    present: bool = False
    filename: Optional[str] = None
    characters: int = 0
    updated_at: Optional[str] = None
    issues: list[LatexIssue] = Field(default_factory=list)


class ResumeStatus(BaseModel):
    loaded: bool
    filename: Optional[str] = None
    characters: int = 0
    updated_at: Optional[str] = None
    tex: ResumeTexStatus = Field(default_factory=ResumeTexStatus)


class LatexStatus(BaseModel):
    """Which TeX engine, if any, this machine can compile with."""

    available: bool = False
    path: Optional[str] = None
    engine: Optional[str] = None
    version: Optional[str] = None
    candidates: list[str] = Field(default_factory=list)


# ------------------------------------------------------------- resume instances

class CompileError(BaseModel):
    line: Optional[int] = None
    message: str


class ResumeInstanceSummary(BaseModel):
    """A row in the resume list: everything but the document itself."""

    id: int
    name: str
    description: Optional[str] = None
    pdf_filename: Optional[str] = None
    has_pdf: bool = False
    compiled_at: Optional[str] = None
    compile_ok: bool = False
    compile_errors: list[CompileError] = Field(default_factory=list)
    is_default: bool = False
    linked_count: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ResumeInstance(ResumeInstanceSummary):
    latex: str = ""
    compile_log: Optional[str] = None
    # Derived from `latex`, not stored: the source is the only truth, and a
    # cached copy of its problems would go stale on the next keystroke.
    issues: list[LatexIssue] = Field(default_factory=list)


class ResumeInstanceCreate(BaseModel):
    name: str = "New resume"
    description: Optional[str] = None
    latex: Optional[str] = None
    # Start from an existing variant rather than the template or resume.tex.
    copy_from: Optional[int] = None

    @field_validator("name")
    @classmethod
    def _named(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("cannot be empty")
        return value.strip()


class ResumeInstanceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    latex: Optional[str] = None

    @field_validator("name")
    @classmethod
    def _named(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not value.strip():
            raise ValueError("cannot be empty")
        return value.strip() if value is not None else None


class ResumeTexUpdate(BaseModel):
    latex: str


class ResumeAsset(BaseModel):
    """An image or include file staged beside the source at compile time."""

    name: str
    size: int
    updated_at: Optional[str] = None


class LinkedOpportunity(BaseModel):
    """A listing this resume is attached to, as shown in the editor sidebar."""

    id: int
    title: str
    organization: str
    url: Optional[str] = None
    deadline: Optional[str] = None
    relevance_score: Optional[float] = None
    advice_generated_at: Optional[str] = None


OpportunityDetail.model_rebuild()
