"""Knowledge-to-problem mappings and progressive training are teacher-reviewed proposals."""
from typing import Literal
from pydantic import Field
from .research_models import Strict,AuthoringAnalysis

class Application(Strict):
    id:str=Field(min_length=1,max_length=80)
    quote:str=Field(min_length=1,max_length=1500)
    knowledge_ref:str
    why:str=Field(min_length=1,max_length=2000)
    operation:str=Field(min_length=1,max_length=2000)
    conditions:str=Field(min_length=1,max_length=1500)
    approach_id:str
    step_index:int=Field(ge=0,le=9)
class Exercise(Strict):
    phase:Literal['read','relate','plan','solve','check']
    prompt:str=Field(min_length=1,max_length=2500)
    mapping_ids:list[str]=Field(min_length=1,max_length=12)
    hints:list[str]=Field(min_length=1,max_length=3)
    expected_reasoning:str=Field(min_length=1,max_length=3000)
    checkpoints:list[str]=Field(min_length=1,max_length=6)
class TeachingCase(Strict):
    question_version_id:str
    relevance:Literal['primary','combined','optional','none','uncertain']
    relevance_reason:str=Field(min_length=1,max_length=2000)
    analysis:AuthoringAnalysis|None=None
    applications:list[Application]=Field(default_factory=list,max_length=20)
    training:list[Exercise]=Field(default_factory=list,max_length=5)
    knowledge_gaps:list[str]=Field(default_factory=list,max_length=10)
class TeachingBody(Strict):
    title:str=Field(min_length=1,max_length=160)
    teacher_notes:str=Field(default='',max_length=5000)
    cases:list[TeachingCase]=Field(min_length=1,max_length=4)
class TeachingCritic(Strict):
    issues:list[str]=Field(max_length=20)

def init_teaching(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS teaching_manuscripts (
      run_id TEXT PRIMARY KEY REFERENCES knowledge_runs(id), payload TEXT NOT NULL,
      original_payload TEXT NOT NULL, checks TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
      parent_version TEXT
    );
    CREATE TABLE IF NOT EXISTS teaching_history (
      id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES teaching_manuscripts(run_id),
      revision INTEGER NOT NULL, snapshot TEXT NOT NULL,created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS teaching_versions (
      id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES teaching_manuscripts(run_id),revision INTEGER NOT NULL,
      snapshot TEXT NOT NULL,rendered_html TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(run_id,revision)
    );
    CREATE TABLE IF NOT EXISTS teaching_requests (
      request_key TEXT PRIMARY KEY,run_id TEXT NOT NULL REFERENCES knowledge_runs(id),input_hash TEXT NOT NULL
    );
    ''')
