"""Stage 0/1 contracts. Execution, mathematical review and scope are independent."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

Kind = Literal['concept', 'property', 'theorem', 'method']
Scope = Literal['pending', 'core', 'connection', 'extension', 'excluded']

class KnowledgeBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=160)
    kind: Kind
    statement: str = Field(max_length=6000)
    conditions: str = Field(max_length=3000)
    formula: str = Field(default='', max_length=6000)
    positive_example: str = Field(max_length=4000)
    misconception: str = Field(max_length=4000)
    mastery: str = Field(max_length=3000)
    method_steps: str = Field(default='', max_length=4000)
    uncertainty: str = Field(default='', max_length=2000)


def init_knowledge(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS knowledge_units (
      id TEXT PRIMARY KEY, title TEXT NOT NULL, chapters TEXT NOT NULL,
      target TEXT NOT NULL, notes TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
      origin TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS knowledge_runs (
      id TEXT PRIMARY KEY, unit_id TEXT NOT NULL REFERENCES knowledge_units(id),
      input_revision INTEGER NOT NULL, input_json TEXT NOT NULL, model_json TEXT NOT NULL,
      status TEXT NOT NULL, stage TEXT NOT NULL, error TEXT NOT NULL DEFAULT '',
      catalog TEXT NOT NULL DEFAULT '[]', selected_ids TEXT NOT NULL DEFAULT '[]',
      checks TEXT NOT NULL DEFAULT '[]', base_run_id TEXT,
      revision INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS knowledge_candidates (
      id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES knowledge_runs(id),
      knowledge_id TEXT NOT NULL, body TEXT NOT NULL, original_body TEXT NOT NULL,
      scope TEXT NOT NULL DEFAULT 'pending', review_state TEXT NOT NULL DEFAULT 'pending',
      revision INTEGER NOT NULL DEFAULT 1, reviewer TEXT NOT NULL DEFAULT '',
      review_note TEXT NOT NULL DEFAULT '', UNIQUE(run_id,knowledge_id)
    );
    CREATE TABLE IF NOT EXISTS knowledge_candidate_history (
      id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL REFERENCES knowledge_candidates(id),
      revision INTEGER NOT NULL, snapshot TEXT NOT NULL, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS knowledge_calls (
      id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES knowledge_runs(id),
      step TEXT NOT NULL, status TEXT NOT NULL, request_json TEXT NOT NULL,
      raw_response TEXT NOT NULL DEFAULT '', usage TEXT, error TEXT NOT NULL DEFAULT '',
      reserved_tokens INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS knowledge_versions (
      id TEXT PRIMARY KEY, unit_id TEXT NOT NULL REFERENCES knowledge_units(id),
      run_id TEXT NOT NULL REFERENCES knowledge_runs(id), run_revision INTEGER NOT NULL,
      snapshot TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(run_id,run_revision)
    );
    ''')
