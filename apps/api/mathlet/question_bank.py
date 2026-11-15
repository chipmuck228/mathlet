"""Stable question identities; immutable study and mapping versions remain the evidence."""
import json
from fastapi import APIRouter,HTTPException
from fastapi.responses import Response
from .db import now,connect
from .knowledge import row,packed
from .research import question_current,question_json,validate_text

router=APIRouter(prefix='/api/corpus',tags=['structured question bank'])

def register_question(c,question_id):
    c.execute('INSERT OR IGNORE INTO question_bank_questions VALUES(?,?)',(question_id,now()))

def register_analysis(c,version_id,snapshot):
    qv=row(c,'research_question_versions',snapshot['input']['question_version_id'])
    register_question(c,qv['question_id'])
    c.execute('INSERT OR IGNORE INTO question_bank_studies VALUES(?,?,?,?)',(version_id,qv['question_id'],qv['id'],snapshot.get('created_at',now())))

def register_exam(c,version_id,snapshot):
    for q in snapshot['questions']:
        key=q.get('research_question_id')
        if key and c.execute('SELECT 1 FROM research_questions WHERE id=?',(key,)).fetchone():
            register_question(c,key)
            c.execute('INSERT OR IGNORE INTO question_bank_origins VALUES(?,?)',(key,version_id))

def init_bank(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS question_bank_questions (
      question_id TEXT PRIMARY KEY REFERENCES research_questions(id),created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS question_bank_studies (
      analysis_version_id TEXT PRIMARY KEY REFERENCES research_analysis_versions(id),
      question_id TEXT NOT NULL REFERENCES research_questions(id),question_version_id TEXT NOT NULL REFERENCES research_question_versions(id),created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS question_bank_origins (
      question_id TEXT NOT NULL REFERENCES research_questions(id),exam_version_id TEXT NOT NULL REFERENCES exam_extraction_versions(id),
      PRIMARY KEY(question_id,exam_version_id)
    );
    CREATE INDEX IF NOT EXISTS question_bank_studies_question ON question_bank_studies(question_id);
    ''')
    if c.execute('SELECT 1 FROM schema_migrations WHERE version=14').fetchone():return
    for q in c.execute('SELECT DISTINCT question_id FROM research_question_versions'):register_question(c,q['question_id'])
    for v in c.execute('SELECT id,snapshot FROM exam_extraction_versions'):register_exam(c,v['id'],json.loads(v['snapshot']))
    for v in c.execute('SELECT id,snapshot FROM research_analysis_versions'):register_analysis(c,v['id'],json.loads(v['snapshot']))

def build(c,key):
    from .corpus import analysis_current,mapping_json
    registered=c.execute('SELECT * FROM question_bank_questions WHERE question_id=?',(key,)).fetchone()
    if not registered:raise HTTPException(404,'题库中尚无此题')
    current=row(c,'research_questions',key);current_info=question_json(c,current)
    qv=c.execute('SELECT * FROM research_question_versions WHERE question_id=? ORDER BY revision DESC LIMIT 1',(key,)).fetchone()
    question=json.loads(qv['snapshot']) if qv else json.loads(current['payload'])
    fields=['title','statement','diagram_description','figure_status','region','year','number']
    safe={k:question.get(k,'') for k in fields}
    safe['assets']=question.get('assets',[])
    safe['reference_answer']=question.get('reference_answer','') if question.get('answer_status')=='verified' else ''
    safe['answer_status']=question.get('answer_status','absent')
    sources=[{k:s.get(k) for k in ['id','document_id','document_name','category','locator','hash']} for s in question.get('sources',[]) if s['id'] in question.get('question_block_ids',[])]
    origins=[]
    for v in c.execute('SELECT v.* FROM question_bank_origins b JOIN exam_extraction_versions v ON v.id=b.exam_version_id WHERE b.question_id=? ORDER BY v.created_at DESC',(key,)):
        f=json.loads(v['snapshot']);origins.append({'id':v['id'],'title':f['title'],'filename':v['filename'],'category':f['source']['category'],'created_at':v['created_at']})
    blockers=[]
    if not current_info['confirmed']:blockers.append('完整题目条件或来源需要重新确认')
    if question.get('figure_status')=='pending':blockers.append('必要图形文字条件尚未核对')
    try:validate_text(question['statement'])
    except HTTPException as exc:blockers.append(str(exc.detail))
    studies=[];types=set();names=set();units=set();mapping_versions=[]
    for entry in c.execute('SELECT * FROM question_bank_studies WHERE question_id=? ORDER BY created_at DESC, rowid DESC',(key,)):
        v=row(c,'research_analysis_versions',entry['analysis_version_id']);f=json.loads(v['snapshot']);valid=analysis_current(c,v['id'])
        analysis=f['analysis']
        used={x['ref'] for x in analysis.get('knowledge_breakdown',[])}
        used.update(ref for x in analysis.get('assessed_points',[]) for ref in x.get('knowledge_refs',[]))
        used.update(ref for a in analysis.get('approaches',[]) for step in a['steps'] for ref in step.get('knowledge_refs',[]))
        used_knowledge=[item for item in f.get('knowledge',{}).get('items',[]) if item['ref'] in used]
        if valid:
            types.update(analysis['problem_types']);names.update(x['name'] for x in analysis.get('identified_knowledge',[]))
            for item in used_knowledge:units.add(item['unit_title']);names.add(item['title'])
        studies.append({'id':v['id'],'revision':v['revision'],'run_id':f['run_id'],'question_version_id':entry['question_version_id'],'current':valid,'created_at':v['created_at'],'analysis':analysis,'knowledge':used_knowledge,'reviewer':f.get('reviewer',''),'review_note':f.get('review_note',''),'checks':f.get('checks',[]),'independent_verification':f.get('independent_verification'),'model':f.get('model',{})})
        for mv in c.execute('SELECT v.* FROM corpus_mapping_versions v JOIN corpus_mappings m ON m.id=v.mapping_id WHERE m.analysis_version_id=? ORDER BY v.created_at DESC',(v['id'],)):
            snapshot=json.loads(mv['snapshot']);mapping=row(c,'corpus_mappings',mv['mapping_id']);state=mapping_json(c,mapping)
            effective=not state['stale'] and state['read_only'] and mapping['revision']==mv['revision']
            if effective:
                refs={link['ref'] for link in snapshot['mapping']['links']}
                for item in snapshot['knowledge']:
                    if item['ref'] in refs:units.add(item['unit_title']);names.add(item['title'])
            snapshot=snapshot|{'knowledge':[item for item in snapshot['knowledge'] if item['ref'] in {link['ref'] for link in snapshot['mapping']['links']}]}
            mapping_versions.append({'id':mv['id'],'mapping_id':mv['mapping_id'],'revision':mv['revision'],'current':effective,'snapshot':snapshot,'created_at':mv['created_at']})
    current_analyses=[s['id'] for s in studies if s['current']]
    status='research_reviewed' if current_analyses else 'question_confirmed' if current_info['confirmed'] and not blockers else 'needs_confirmation'
    return {'format':'mathlet-question-bank','schema_version':1,'id':key,'created_at':registered['created_at'],'status':status,'reusable':bool(current_analyses),'question_confirmed':current_info['confirmed'],'question_version_id':qv['id'] if qv else None,'current_question_version_id':current_info['version_id'],'question':safe,'sources':sources,'origins':origins,'research_blockers':blockers,'source_categories':sorted({s['category'] or 'unknown' for s in sources}),'source_titles':sorted({s['document_name'] or '' for s in sources}|{o['title'] for o in origins}),'problem_types':sorted(types),'knowledge_names':sorted(names),'knowledge_units':sorted(units),'research_versions':studies,'mapping_versions':mapping_versions,'current_analysis_ids':current_analyses,'stale':not question_current(c,current),'complete_question_id':key}

@router.get('/bank')
def bank():
    with connect() as c:
        result=[]
        for r in c.execute('SELECT question_id FROM question_bank_questions ORDER BY created_at DESC, rowid DESC'):
            value=build(c,r['question_id'])
            result.append({k:value[k] for k in ['id','status','reusable','question_confirmed','problem_types','knowledge_names','knowledge_units','source_categories','source_titles','current_analysis_ids','stale']}|{'title':value['question']['title'],'statement':value['question']['statement'],'research_count':len(value['research_versions']),'mapping_count':len(value['mapping_versions'])})
        return result
@router.get('/bank/{key}')
def get_bank(key:str):
    with connect() as c:return build(c,key)
@router.get('/bank/{key}/download')
def download(key:str):
    with connect() as c:value=build(c,key)
    value['exported_at']=now()
    return Response(packed(value),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="question-bank-{key}.json"'})
