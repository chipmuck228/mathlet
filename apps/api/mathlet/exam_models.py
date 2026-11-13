"""A whole-exam transcription review, distinct from mathematical solution review."""
from pydantic import Field
from .research_models import Strict
from .paper_models import Span,SplitItem

class ExamHint(SplitItem):
    answer_asset_ids:list[str]=Field(default_factory=list,max_length=30)
class ExamPlan(Strict):
    title:str=Field(min_length=1,max_length=200)
    questions:list[ExamHint]=Field(min_length=1,max_length=60)
    notes:list[str]=Field(default_factory=list,max_length=20)
class ExamQuestion(Strict):
    key:str=Field(min_length=1,max_length=80)
    number:str=Field(default='',max_length=80)
    question_text:str=Field(default='',max_length=16000)
    answer_text:str=Field(default='',max_length=16000)
    image_ids:list[str]=Field(default_factory=list,max_length=30)
    answer_image_ids:list[str]=Field(default_factory=list,max_length=30)
    diagram_description:str=Field(default='',max_length=8000)
    question_spans:list[Span]=Field(default_factory=list,max_length=30)
    answer_spans:list[Span]=Field(default_factory=list,max_length=30)
    notes:str=Field(default='',max_length=3000)
class ExamBody(Strict):
    title:str=Field(min_length=1,max_length=200)
    questions:list[ExamQuestion]=Field(min_length=1,max_length=60)
    notes:str=Field(default='',max_length=8000)

def init_exam(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS exam_extractions (
      id TEXT PRIMARY KEY REFERENCES knowledge_runs(id),document_id TEXT NOT NULL REFERENCES documents(id),
      source TEXT NOT NULL,payload TEXT,original_payload TEXT,revision INTEGER NOT NULL DEFAULT 1,
      filename TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL,parent_version TEXT
    );
    CREATE TABLE IF NOT EXISTS exam_extraction_history (
      id TEXT PRIMARY KEY,extraction_id TEXT NOT NULL REFERENCES exam_extractions(id),revision INTEGER NOT NULL,
      snapshot TEXT NOT NULL,created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS exam_extraction_versions (
      id TEXT PRIMARY KEY,extraction_id TEXT NOT NULL REFERENCES exam_extractions(id),revision INTEGER NOT NULL,
      version_number INTEGER NOT NULL,snapshot TEXT NOT NULL,filename TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL,
      UNIQUE(extraction_id,revision)
    );
    CREATE TABLE IF NOT EXISTS exam_document_heads (
      document_id TEXT PRIMARY KEY REFERENCES documents(id),version_id TEXT NOT NULL REFERENCES exam_extraction_versions(id)
    );
    CREATE TABLE IF NOT EXISTS exam_extraction_papers (
      version_id TEXT PRIMARY KEY REFERENCES exam_extraction_versions(id),project_id TEXT NOT NULL REFERENCES paper_projects(id)
    );
    ''')
