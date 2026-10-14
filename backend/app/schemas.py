from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')

class Fact(Strict):
    text: str
    quote: str
    kind: Literal['fact','impact','scale','urgency','uncertainty','conflict']
    certainty: str = 'reported'

class ExtractedEvent(Strict):
    title: str
    facts: list[Fact]
    affected: list[str]
    cves: list[str]
    event_date: str | None
    uncertainties: list[str]
    primary: bool
    origin_statement: str | None
    is_old_event: bool
    new_facts: list[str]

class Extraction(Strict):
    relevant: bool
    reason: str
    category: str
    sufficient: bool
    events: list[ExtractedEvent]

class Group(Strict):
    candidate_ids: list[str]
    reason: str
    conflicts: list[str]

class Grouping(Strict):
    groups: list[Group]

class Ranked(Strict):
    event_id: str
    impact: int = Field(ge=0, le=5)
    scale: int | None = Field(ge=0, le=5)
    urgency: int = Field(ge=0, le=5)
    audience: int = Field(ge=0, le=5)
    reason: str
    evidence_claim_ids: list[str]

class Ranking(Strict):
    events: list[Ranked]

class Sentence(Strict):
    text: str
    claim_ids: list[str]

class EvidenceSentence(Sentence):
    claim_ids: list[str] = Field(min_length=1)

class ComposedItem(Strict):
    event_id: str
    title: EvidenceSentence
    summary: list[EvidenceSentence] = Field(min_length=2, max_length=3)
    consequences: Sentence
    short: EvidenceSentence

class Composition(Strict):
    items: list[ComposedItem]

class Verification(Strict):
    supported: bool
    problems: list[str]
