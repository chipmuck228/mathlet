"""Version-bound knowledge connections and complete-question research contracts."""
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
class Relation(Strict):
    source_ref:str
    target_ref:str
    relation_type:Literal['prerequisite','derives','uses','contrast','representation','equivalent_candidate']
    reason:str=Field(min_length=1,max_length=2500)
    conditions:str=Field(min_length=1,max_length=2500)
    example:str=Field(min_length=1,max_length=2500)
class Relations(Strict):
    relations:list[Relation]=Field(max_length=8)
class Assessed(Strict):
    name:str=Field(min_length=1,max_length=300)
    knowledge_refs:list[str]=Field(max_length=12)
    evidence:str=Field(min_length=1,max_length=2000)
class KnowledgeUse(Strict):
    ref:str
    role:str=Field(min_length=1,max_length=2000)
    conditions:str=Field(min_length=1,max_length=2000)
class Step(Strict):
    action:str=Field(min_length=1,max_length=2500)
    reason:str=Field(min_length=1,max_length=2000)
    knowledge_refs:list[str]=Field(max_length=12)
class Approach(Strict):
    id:str=Field(min_length=1,max_length=80)
    title:str=Field(min_length=1,max_length=300)
    trigger:str=Field(min_length=1,max_length=2000)
    steps:list[Step]=Field(min_length=1,max_length=10)
    conclusion:str=Field(min_length=1,max_length=3000)
    checks:str=Field(min_length=1,max_length=2500)
    limitations:str=Field(max_length=2000)
class Analysis(Strict):
    problem_types:list[str]=Field(min_length=1,max_length=6)
    classification_reason:str=Field(min_length=1,max_length=2000)
    assessed_points:list[Assessed]=Field(min_length=1,max_length=12)
    knowledge_breakdown:list[KnowledgeUse]=Field(min_length=1,max_length=20)
    approaches:list[Approach]=Field(min_length=1,max_length=3)
    recognition_cues:list[str]=Field(min_length=1,max_length=8)
    common_mistakes:list[str]=Field(max_length=8)
    variation_prompts:list[str]=Field(max_length=8)
    scope_notes:list[str]=Field(max_length=10)
    missing_information:list[str]=Field(max_length=10)
class ReviewIssue(Strict):
    approach_id:str=''
    category:Literal['correctness','source','condition','scope','teaching']
    message:str=Field(min_length=1,max_length=2500)
class Critic(Strict):
    issues:list[ReviewIssue]=Field(max_length=30)
class QuestionBody(Strict):
    title:str=Field(min_length=1,max_length=160)
    question_block_ids:list[str]=Field(min_length=1,max_length=30)
    answer_block_ids:list[str]=Field(default_factory=list,max_length=30)
    statement:str=Field(min_length=1,max_length=16000)
    answer_status:Literal['absent','unchecked','verified']='absent'
    reference_answer:str=Field(default='',max_length=8000)
    figure_status:Literal['not_needed','described','pending']='not_needed'
    diagram_description:str=Field(default='',max_length=8000)
    region:str=Field(default='',max_length=100)
    year:str=Field(default='',max_length=20)
    number:str=Field(default='',max_length=80)
    notes:str=Field(default='',max_length=3000)


def init_research(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS research_contexts (
      id TEXT PRIMARY KEY,title TEXT NOT NULL,version_ids TEXT NOT NULL,snapshot TEXT NOT NULL,
      revision INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS research_questions (
      id TEXT PRIMARY KEY,payload TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,
      confirmed_revision INTEGER,reviewer TEXT NOT NULL DEFAULT '',review_note TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS research_question_history (
      id TEXT PRIMARY KEY,question_id TEXT NOT NULL,revision INTEGER NOT NULL,snapshot TEXT NOT NULL,created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS research_question_versions (
      id TEXT PRIMARY KEY,question_id TEXT NOT NULL REFERENCES research_questions(id),revision INTEGER NOT NULL,
      snapshot TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(question_id,revision)
    );
    CREATE TABLE IF NOT EXISTS research_outputs (
      id TEXT PRIMARY KEY,run_id TEXT NOT NULL REFERENCES knowledge_runs(id),context_id TEXT NOT NULL REFERENCES research_contexts(id),
      kind TEXT NOT NULL,body TEXT NOT NULL,original_body TEXT NOT NULL,checks TEXT NOT NULL,
      revision INTEGER NOT NULL DEFAULT 1,state TEXT NOT NULL DEFAULT 'pending',reviewer TEXT NOT NULL DEFAULT '',note TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS research_output_history (
      id TEXT PRIMARY KEY,output_id TEXT NOT NULL,revision INTEGER NOT NULL,snapshot TEXT NOT NULL,created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS research_graph_versions (
      id TEXT PRIMARY KEY,context_id TEXT NOT NULL REFERENCES research_contexts(id),context_revision INTEGER NOT NULL,
      snapshot TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(context_id,context_revision)
    );
    CREATE TABLE IF NOT EXISTS research_analysis_versions (
      id TEXT PRIMARY KEY,output_id TEXT NOT NULL REFERENCES research_outputs(id),revision INTEGER NOT NULL,
      snapshot TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(output_id,revision)
    );
    ''')
