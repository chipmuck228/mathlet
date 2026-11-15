"""Question-first research and separately versioned knowledge mappings."""
from typing import Literal
from pydantic import Field
from .research_models import Strict,AuthoringAnalysis,KnowledgeUse,ReviewIssue

class Identified(Strict):
    name:str=Field(min_length=1,max_length=200)
    role:Literal['primary','support','method','check']
    reason:str=Field(min_length=1,max_length=2000)
    conditions:str=Field(min_length=1,max_length=2000)
class IndependentAnalysis(AuthoringAnalysis):
    knowledge_breakdown:list[KnowledgeUse]=Field(default_factory=list,max_length=20)
    identified_knowledge:list[Identified]=Field(min_length=1,max_length=20)
class Verification(Strict):
    verdict:Literal['consistent','disagrees','insufficient']
    summary:str=Field(min_length=1,max_length=3000)
    issues:list[ReviewIssue]=Field(default_factory=list,max_length=30)
class MappingLink(Strict):
    ref:str
    role:Literal['primary','support','method','check']
    reason:str=Field(min_length=1,max_length=2000)
    evidence:str=Field(min_length=1,max_length=2000)
class MappingBody(Strict):
    links:list[MappingLink]=Field(default_factory=list,max_length=40)
    gaps:list[str]=Field(default_factory=list,max_length=20)
    summary:str=Field(min_length=1,max_length=3000)

def init_corpus(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS corpus_entries (
      run_id TEXT PRIMARY KEY REFERENCES knowledge_runs(id),question_version_id TEXT NOT NULL REFERENCES research_question_versions(id),
      exam_version_id TEXT NOT NULL REFERENCES exam_extraction_versions(id)
    );
    CREATE TABLE IF NOT EXISTS independent_reviews (
      run_id TEXT PRIMARY KEY REFERENCES knowledge_runs(id),payload TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS corpus_mappings (
      id TEXT PRIMARY KEY REFERENCES knowledge_runs(id),analysis_version_id TEXT NOT NULL REFERENCES research_analysis_versions(id),
      knowledge TEXT NOT NULL,payload TEXT,revision INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS corpus_mapping_history (
      id TEXT PRIMARY KEY,mapping_id TEXT NOT NULL REFERENCES corpus_mappings(id),revision INTEGER NOT NULL,snapshot TEXT NOT NULL,created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS corpus_mapping_versions (
      id TEXT PRIMARY KEY,mapping_id TEXT NOT NULL REFERENCES corpus_mappings(id),revision INTEGER NOT NULL,
      snapshot TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(mapping_id,revision)
    );
    CREATE TABLE IF NOT EXISTS corpus_card_tasks (
      run_id TEXT PRIMARY KEY REFERENCES knowledge_runs(id),project_id TEXT NOT NULL REFERENCES paper_projects(id)
    );
    ''')
