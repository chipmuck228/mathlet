"""Paper suggestions are anchored to reviewed text, never reconstructed as invented originals."""
from typing import Literal
from pydantic import Field
from .research_models import Strict

class Span(Strict):
    block_id:str
    start_anchor:str=Field(default='',max_length=250)
    end_anchor:str=Field(default='',max_length=250)
    start_occurrence:int=Field(default=0,ge=0,le=10000)
    end_occurrence:int=Field(default=0,ge=0,le=10000)
class Recommendation(Strict):
    ref:str
    reason:str=Field(min_length=1,max_length=1200)
    evidence:str=Field(default='',max_length=500)
class PaperItem(Strict):
    title:str=Field(min_length=1,max_length=160)
    number:str=Field(default='',max_length=80)
    question_spans:list[Span]=Field(min_length=1,max_length=30)
    answer_spans:list[Span]=Field(default_factory=list,max_length=30)
    asset_ids:list[str]=Field(default_factory=list,max_length=30)
    answer_status:Literal['absent','unchecked','verified']='absent'
    figure_status:Literal['not_needed','pending','described']='not_needed'
    diagram_description:str=Field(default='',max_length=8000)
    region:str=Field(default='',max_length=100)
    year:str=Field(default='',max_length=20)
    boundary_note:str=Field(default='',max_length=2000)
    knowledge_refs:list[str]=Field(default_factory=list,max_length=20)
    recommendations:list[Recommendation]=Field(default_factory=list,max_length=20)
    knowledge_gaps:list[str]=Field(default_factory=list,max_length=12)
class SplitItem(Strict):
    title:str=Field(min_length=1,max_length=160)
    number:str=Field(default='',max_length=80)
    question_spans:list[Span]=Field(min_length=1,max_length=30)
    answer_spans:list[Span]=Field(default_factory=list,max_length=30)
    asset_ids:list[str]=Field(default_factory=list,max_length=30)
    boundary_note:str=Field(default='',max_length=2000)
class SplitResult(Strict):
    questions:list[SplitItem]=Field(min_length=1,max_length=60)
    notes:list[str]=Field(default_factory=list,max_length=20)
class Match(Strict):
    item_id:str
    recommendations:list[Recommendation]=Field(max_length=12)
    gaps:list[str]=Field(default_factory=list,max_length=12)
class MatchResult(Strict):
    matches:list[Match]=Field(max_length=5)
class CardStep(Strict):
    action:str=Field(min_length=1,max_length=2500)
    reason:str=Field(min_length=1,max_length=2500)
    conditions:str=Field(min_length=1,max_length=2500)
    analysis_ids:list[str]=Field(min_length=1,max_length=10)
class CardExample(Strict):
    analysis_id:str
    reason:str=Field(min_length=1,max_length=2000)
class Training(Strict):
    kind:Literal['designed']='designed'
    prompt:str=Field(min_length=1,max_length=3000)
    skill_goal:str=Field(min_length=1,max_length=1500)
    hints:list[str]=Field(max_length=5)
    checkpoints:list[str]=Field(min_length=1,max_length=8)
    analysis_ids:list[str]=Field(min_length=1,max_length=10)
class ThinkingCard(Strict):
    title:str=Field(min_length=1,max_length=160)
    recognition_cues:list[str]=Field(min_length=1,max_length=8)
    common_structure:str=Field(min_length=1,max_length=3000)
    strategy_steps:list[CardStep]=Field(min_length=1,max_length=10)
    alternative_paths:list[CardStep]=Field(default_factory=list,max_length=6)
    boundaries:list[str]=Field(min_length=1,max_length=8)
    common_mistakes:list[str]=Field(max_length=8)
    examples:list[CardExample]=Field(min_length=2,max_length=10)
    transfer_training:list[Training]=Field(min_length=1,max_length=4)
    unresolved:list[str]=Field(default_factory=list,max_length=10)
class Cards(Strict):
    cards:list[ThinkingCard]=Field(max_length=3)
    summary:str=Field(min_length=1,max_length=3000)
class CardIssue(Strict):
    card_index:int|None=None
    message:str=Field(min_length=1,max_length=2500)
class CardCritic(Strict):
    issues:list[CardIssue]=Field(max_length=20)


def init_paper(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS paper_projects (
      id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
      title TEXT NOT NULL, source TEXT NOT NULL, knowledge TEXT NOT NULL,
      revision INTEGER NOT NULL DEFAULT 1, notes TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS paper_items (
      id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES paper_projects(id),
      ordinal INTEGER NOT NULL, payload TEXT NOT NULL, original_payload TEXT NOT NULL,
      revision INTEGER NOT NULL DEFAULT 1, excluded INTEGER NOT NULL DEFAULT 0, question_id TEXT, question_version_id TEXT, run_id TEXT
    );
    CREATE TABLE IF NOT EXISTS paper_item_history (
      id TEXT PRIMARY KEY, item_id TEXT NOT NULL REFERENCES paper_items(id),
      revision INTEGER NOT NULL, snapshot TEXT NOT NULL, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS paper_item_runs (
      item_id TEXT NOT NULL REFERENCES paper_items(id), run_id TEXT NOT NULL REFERENCES knowledge_runs(id),
      PRIMARY KEY(item_id,run_id)
    );
    CREATE TABLE IF NOT EXISTS paper_cards (
      id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES paper_projects(id), task_id TEXT NOT NULL,
      payload TEXT NOT NULL, original_payload TEXT NOT NULL, sources TEXT NOT NULL, checks TEXT NOT NULL,
      revision INTEGER NOT NULL DEFAULT 1, parent_version TEXT
    );
    CREATE TABLE IF NOT EXISTS paper_card_history (
      id TEXT PRIMARY KEY, card_id TEXT NOT NULL REFERENCES paper_cards(id),revision INTEGER NOT NULL,
      snapshot TEXT NOT NULL, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS paper_card_versions (
      id TEXT PRIMARY KEY, card_id TEXT NOT NULL REFERENCES paper_cards(id),revision INTEGER NOT NULL,
      snapshot TEXT NOT NULL, created_at TEXT NOT NULL,UNIQUE(card_id,revision)
    );
    ''')
