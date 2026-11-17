"""One teacher decision for a source-bound, automatically composed revision unit."""
from typing import Literal
from pydantic import Field
from .research_models import Strict

class Evidence(Strict):
    analysis_id:str
    approach_id:str
    step_index:int=Field(ge=0)
    quote:str=Field(min_length=1,max_length=2500)
class Link(Evidence):
    knowledge_ref:str
    role:Literal['core','support','optional']
    explanation:str=Field(min_length=1,max_length=2500)
    conditions:str=Field(min_length=1,max_length=2500)
class Mapping(Strict):
    analysis_id:str
    relevance:Literal['core','support','optional','none','uncertain']
    reason:str=Field(min_length=1,max_length=2500)
    links:list[Link]=Field(max_length=30)
    gaps:list[str]=Field(default_factory=list,max_length=15)
class MappingBatch(Strict):
    mappings:list[Mapping]
class Card(Strict):
    title:str=Field(min_length=1,max_length=160)
    cues:list[str]=Field(min_length=1,max_length=10)
    structure:str=Field(min_length=1,max_length=4000)
    steps:list[str]=Field(min_length=1,max_length=10)
    conditions:list[str]=Field(min_length=1,max_length=10)
    alternatives:list[str]=Field(max_length=10)
    mistakes:list[str]=Field(max_length=10)
    knowledge_refs:list[str]=Field(min_length=1,max_length=20)
    evidence:list[Evidence]=Field(min_length=2,max_length=12)
    doubts:list[str]=Field(default_factory=list,max_length=10)
class CardSet(Strict):
    cards:list[Card]=Field(max_length=5)
    summary:str=Field(min_length=1,max_length=4000)
class Training(Strict):
    phase:Literal['basic','thinking','solve','transfer']
    kind:Literal['original','designed']
    title:str=Field(min_length=1,max_length=160)
    source_analysis_ids:list[str]=Field(min_length=1,max_length=8)
    knowledge_refs:list[str]=Field(min_length=1,max_length=20)
    prompt:str=Field(min_length=1,max_length=4000)
    hints:list[str]=Field(max_length=3)
    answer:str=Field(min_length=1,max_length=6000)
    reasoning:str=Field(min_length=1,max_length=6000)
    checkpoints:list[str]=Field(min_length=1,max_length=10)
class KnowledgeConnection(Strict):
    source_ref:str
    target_ref:str
    relation_type:Literal['prerequisite','derives','uses','contrast','representation']
    explanation:str=Field(min_length=1,max_length=3000)
    conditions:str=Field(min_length=1,max_length=3000)
    example:str=Field(min_length=1,max_length=3000)

class Composition(Strict):
    knowledge_connections:list[KnowledgeConnection]=Field(default_factory=list,max_length=12)
    title:str=Field(min_length=1,max_length=200)
    introduction:str=Field(min_length=1,max_length=5000)
    goals:list[str]=Field(min_length=1,max_length=12)
    training:list[Training]=Field(max_length=16)
class UnitBody(Composition):
    mappings:list[Mapping]
    selected_analysis_ids:list[str]=Field(max_length=8)
    cards:list[Card]=Field(max_length=5)
    summary:str=Field(min_length=1,max_length=4000)
class ReviewIssue(Strict):
    section:Literal['introduction','goals','mappings','knowledge_connections','cards','training','summary']
    message:str=Field(min_length=1,max_length=3000)
    guidance:str=Field(min_length=1,max_length=3000)
class Review(Strict):
    issues:list[ReviewIssue]=Field(max_length=40)

def init_review_units(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS review_units (
      id TEXT PRIMARY KEY REFERENCES knowledge_runs(id), sources TEXT NOT NULL,
      payload TEXT,original_payload TEXT,checks TEXT NOT NULL DEFAULT '[]',
      revision INTEGER NOT NULL DEFAULT 1,parent_version TEXT
    );
    CREATE TABLE IF NOT EXISTS review_unit_history (
      id TEXT PRIMARY KEY,unit_id TEXT NOT NULL REFERENCES review_units(id),revision INTEGER NOT NULL,
      payload TEXT NOT NULL,created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS review_unit_versions (
      id TEXT PRIMARY KEY,unit_id TEXT NOT NULL REFERENCES review_units(id),revision INTEGER NOT NULL,
      snapshot TEXT NOT NULL,rendered_html TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(unit_id,revision)
    );
    CREATE TABLE IF NOT EXISTS review_unit_discussions (
      id TEXT PRIMARY KEY REFERENCES knowledge_runs(id),unit_id TEXT NOT NULL REFERENCES review_units(id),
      request_key TEXT NOT NULL UNIQUE,signature TEXT NOT NULL,section TEXT NOT NULL,instruction TEXT NOT NULL,
      revision INTEGER NOT NULL,reply TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS review_unit_requests (
      request_key TEXT PRIMARY KEY,unit_id TEXT NOT NULL REFERENCES review_units(id),signature TEXT NOT NULL
    );
    ''')
