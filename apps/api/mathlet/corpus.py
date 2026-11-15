"""Multiple finalized exams -> independent studies -> mappings -> cross-paper cards."""
import json,hashlib
from fastapi import APIRouter,HTTPException
from fastapi.responses import Response
from pydantic import Field
from .db import connect,uid,now
from .knowledge import row,revision,packed
from .research_models import Strict
from .corpus_models import MappingBody
from .research import sources_current,question_current,version_current,validate_text
from .model_provider import load_provider,public_provider

router=APIRouter(prefix='/api/corpus',tags=['question-first research'])
def digest(x):return hashlib.sha256(packed(x).encode()).hexdigest()
def fingerprint(q):return digest({'text':' '.join(q['statement'].split()),'diagram':' '.join(q.get('diagram_description','').split()),'assets':[a['hash'] for a in q.get('assets',[])]})

def queue(c,title,snapshot,config,reserve):
    key=uid();unit=uid();config=config.model_copy(update={'output_token_budget':max(config.output_token_budget,reserve)})
    c.execute('INSERT INTO knowledge_units(id,title,chapters,target,notes,origin,created_at) VALUES(?,?,?,?,?,?,?)',(unit,title,'[]','题库研究','',packed({'internal_research':True}),now()))
    c.execute('INSERT INTO knowledge_runs(id,unit_id,input_revision,input_json,model_json,status,stage,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',(key,unit,1,packed(snapshot),packed(public_provider(config)),'queued','corpus',now(),now()))
    return row(c,'knowledge_runs',key)
def provider():
    config=load_provider()
    if not config.api_key or not config.model:raise HTTPException(422,'请先配置模型服务')
    return config

def analysis_current(c,key):
    v=row(c,'research_analysis_versions',key);f=json.loads(v['snapshot'])
    output=row(c,'research_outputs',v['output_id'])
    latest=c.execute('SELECT id FROM research_analysis_versions WHERE output_id=? ORDER BY revision DESC LIMIT 1',(v['output_id'],)).fetchone()
    return output['state']=='approved' and output['revision']==v['revision'] and latest['id']==key and sources_current(c,f['input'])

def corpus_current(c,meta):
    if meta['kind']=='mapping':
        return analysis_current(c,meta['analysis_version_id']) and all(version_current(c,row(c,'knowledge_versions',key)) for key in meta['version_ids'])
    from .paper_research import card_sources_current
    return card_sources_current(c,meta['sources']) and all(analysis_current(c,s['id']) for s in meta['sources'])

@router.get('/catalog')
def catalog():
    from .exam_extraction import version_current as exam_current
    with connect() as c:
        exams=[];questions=[];runs_by_question={}
        for entry in c.execute('SELECT * FROM corpus_entries'):
            run=row(c,'knowledge_runs',entry['run_id']);meta=json.loads(run['input_json'])['research_task']
            finals=[dict(v) for v in c.execute('SELECT v.id,v.created_at FROM research_analysis_versions v JOIN research_outputs o ON o.id=v.output_id WHERE o.run_id=? ORDER BY v.revision DESC',(run['id'],))]
            output=c.execute('SELECT body FROM research_outputs WHERE run_id=? ORDER BY rowid DESC LIMIT 1',(run['id'],)).fetchone()
            body=json.loads(output['body']) if output else {}
            runs_by_question.setdefault(entry['question_version_id'],[]).append({'id':run['id'],'status':run['status'],'error':run['error'],'revision':run['revision'],'problem_types':body.get('problem_types',[]),'identified_names':[x['name'] for x in body.get('identified_knowledge',[])],'stale':not sources_current(c,meta),'finals':[v|{'stale':not analysis_current(c,v['id'])} for v in finals]})
        for v in c.execute('SELECT v.* FROM exam_document_heads h JOIN exam_extraction_versions v ON v.id=h.version_id ORDER BY v.created_at DESC'):
            f=json.loads(v['snapshot']);stale=not exam_current(c,v['id'])
            exams.append({'id':v['id'],'title':f['title'],'filename':v['filename'],'category':f['source']['category'],'stale':stale,'count':len(f['questions'])})
            for q in f['questions']:
                version_id=q.get('question_version_id');blockers=[];frozen=None
                if stale:blockers.append('原文或试卷终稿已变化')
                current=c.execute('SELECT * FROM research_questions WHERE id=?',(q.get('research_question_id'),)).fetchone() if q.get('research_question_id') else None
                if current and current['confirmed_revision']==current['revision']:
                    confirmed=c.execute('SELECT id FROM research_question_versions WHERE question_id=? AND revision=?',(current['id'],current['revision'])).fetchone()
                    if confirmed:version_id=confirmed['id']
                if version_id:
                    version=row(c,'research_question_versions',version_id);current=row(c,'research_questions',version['question_id']);frozen=json.loads(version['snapshot'])
                    if current['revision']!=version['revision'] or current['confirmed_revision']!=version['revision'] or not question_current(c,current):blockers.append('完整题目已修订，请重新确认题目')
                    if frozen['figure_status']=='pending':blockers.append('必要图形条件尚未文字核对，请在题目与研究中补充')
                    try:validate_text(frozen['statement'])
                    except HTTPException as exc:blockers.append(str(exc.detail))
                else:blockers.append(q.get('research_note') or '题目尚未形成可研究的完整版本，请在题目与研究中补充条件并确认')
                questions.append({'id':v['id']+':'+q['key'],'exam_id':v['id'],'title':f['title']+' · '+(q['number'] or '未编号题'),'number':q['number'],'statement':frozen['statement'] if frozen else q['question_text'],'question_version_id':version_id,'blockers':blockers,'fingerprint':fingerprint(frozen) if frozen else '', 'runs':runs_by_question.get(version_id,[])})
        counts={}
        for q in questions:
            if q['fingerprint']:counts[q['fingerprint']]=counts.get(q['fingerprint'],0)+1
        for q in questions:q['duplicate_count']=counts.get(q['fingerprint'],1)
        return {'exams':exams,'questions':questions}

class Studies(Strict):
    question_ids:list[str]=Field(min_length=1,max_length=3000)
    instruction:str=Field(default='',max_length=3000)
@router.post('/studies',status_code=201)
def studies(body:Studies):
    config=provider();available={q['id']:q for q in catalog()['questions']};results=[]
    for key in dict.fromkeys(body.question_ids):
        q=available.get(key)
        if not q or q['blockers']:results.append({'question_id':key,'error':'；'.join(q['blockers']) if q else '题目不在当前定稿目录'});continue
        with connect() as c:
            c.execute('BEGIN IMMEDIATE')
            qv=row(c,'research_question_versions',q['question_version_id']);question=row(c,'research_questions',qv['question_id'])
            if question['revision']!=qv['revision'] or question['confirmed_revision']!=qv['revision'] or not question_current(c,question):results.append({'question_id':key,'error':'题目在发起期间发生变化'});continue
            request='independent:'+digest({'question':qv['id'],'instruction':body.instruction,'version':1})
            old=c.execute('SELECT run_id FROM research_manuscripts WHERE request_key=?',(request,)).fetchone()
            if old:run=row(c,'knowledge_runs',old['run_id'])
            else:
                context_id=uid();context={'items':[],'inherited_relations':[],'advisory_relations':[],'version_ids':[],'official_coverage_verified':False}
                c.execute('INSERT INTO research_contexts(id,title,version_ids,snapshot,created_at) VALUES(?,?,?,?,?)',(context_id,'独立研究，不预选知识','[]',packed(context),now()))
                meta={'kind':'analysis','workflow':'independent-v1','context_id':context_id,'context_revision':1,'question_version_id':qv['id'],'graph_version_id':None,'instruction':body.instruction,'limit':3}
                run=queue(c,q['title'],{'schema_version':1,'title':q['title'],'chapters':[],'research_task':meta},config,19000)
                c.execute('INSERT INTO research_manuscripts(run_id,request_key) VALUES(?,?)',(run['id'],request))
                c.execute('INSERT INTO corpus_entries VALUES(?,?,?)',(run['id'],qv['id'],q['exam_id']))
            results.append({'question_id':key,'run_id':run['id'],'status':run['status']})
    return {'results':results}

def knowledge_snapshot(c,ids):
    items=[]
    for key in ids:
        v=row(c,'knowledge_versions',key)
        if not version_current(c,v):raise HTTPException(409,'知识终稿已变化，请选择有效版本')
        f=json.loads(v['snapshot'])
        items.extend({'ref':key+':'+x['knowledge_id'],'title':x['body']['name'],'unit_title':f['unit']['title'],'body':x['body'],'scope':x['scope']} for x in f['items'] if x['scope']!='excluded')
    if not items:raise HTTPException(422,'所选知识终稿没有纳入条目')
    return items
class Match(Strict):
    analysis_version_ids:list[str]=Field(min_length=1,max_length=3000)
    version_ids:list[str]=Field(default_factory=list,max_length=500)
@router.post('/mappings',status_code=201)
def match(body:Match):
    config=provider();results=[]
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');ids=list(dict.fromkeys(body.version_ids))
        if not ids:
            seen=set()
            for v in c.execute('SELECT v.*,k.unit_id AS source_unit FROM knowledge_versions v JOIN knowledge_runs k ON k.id=v.run_id ORDER BY v.created_at DESC,v.rowid DESC'):
                if v['source_unit'] not in seen and version_current(c,v):ids.append(v['id']);seen.add(v['source_unit'])
        knowledge=knowledge_snapshot(c,ids)
        from .corpus_worker import knowledge_batches
        groups=knowledge_batches(knowledge);calls=len(groups)+(1 if len(groups)>1 else 0)
        task_config=config.model_copy(update={'max_calls':max(config.max_calls,calls)})
        for key in dict.fromkeys(body.analysis_version_ids):
            if not analysis_current(c,key):results.append({'analysis_version_id':key,'error':'研究终稿已修订或来源变化，请选有效终稿'});continue
            meta={'kind':'mapping','analysis_version_id':key,'version_ids':sorted(ids)}
            old=next((dict(r) for r in c.execute('SELECT k.* FROM corpus_mappings m JOIN knowledge_runs k ON k.id=m.id WHERE m.analysis_version_id=?',(key,)) if json.loads(r['input_json'])['corpus_task']==meta),None)
            if old:run=old
            else:
                run=queue(c,'研究终稿知识关联',{'title':'知识关联','chapters':[],'corpus_task':meta},task_config,calls*5000)
                c.execute('INSERT INTO corpus_mappings(id,analysis_version_id,knowledge) VALUES(?,?,?)',(run['id'],key,packed(knowledge)))
            results.append({'analysis_version_id':key,'id':run['id'],'status':run['status']})
    return {'results':results}

def validate_mapping(value,knowledge):
    value=MappingBody.model_validate(value).model_dump();allowed={k['ref'] for k in knowledge}
    if not {x['ref'] for x in value['links']}<=allowed:raise ValueError('关联引用不属于所选知识终稿')
    if len({(x['ref'],x['role']) for x in value['links']})!=len(value['links']):raise ValueError('知识与作用重复')
    return value

def mapping_json(c,r):
    run=row(c,'knowledge_runs',r['id']);meta=json.loads(run['input_json'])['corpus_task'];finals=[dict(v) for v in c.execute('SELECT id,revision,created_at FROM corpus_mapping_versions WHERE mapping_id=? ORDER BY revision DESC',(r['id'],))]
    analysis=json.loads(row(c,'research_analysis_versions',r['analysis_version_id'])['snapshot'])
    return dict(r)|{'question_title':analysis['question']['title'],'knowledge':[{k:x[k] for k in ['ref','title','unit_title']} for x in json.loads(r['knowledge'])],'payload':json.loads(r['payload']) if r['payload'] else None,'status':run['status'],'error':run['error'],'run_revision':run['revision'],'stale':not corpus_current(c,meta),'read_only':any(v['revision']==r['revision'] for v in finals),'finals':finals,'calls':[dict(x) for x in c.execute('SELECT step,status,error FROM knowledge_calls WHERE run_id=?',(r['id'],))]}
@router.get('/mappings')
def mappings():
    with connect() as c:return [mapping_json(c,r) for r in c.execute('SELECT * FROM corpus_mappings ORDER BY rowid DESC')]
class SaveMapping(Strict):revision:int;body:MappingBody
@router.put('/mappings/{key}')
def save_mapping(key:str,body:SaveMapping):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');r=row(c,'corpus_mappings',key);revision(r,body.revision);d=mapping_json(c,r)
        if d['read_only'] or d['stale'] or d['status']!='completed':raise HTTPException(409,'关联未完成、已过期或为只读终稿，请先继续修订')
        try:value=validate_mapping(body.body,json.loads(r['knowledge']))
        except ValueError as exc:raise HTTPException(422,str(exc)) from None
        c.execute('INSERT INTO corpus_mapping_history VALUES(?,?,?,?,?)',(uid(),key,r['revision'],packed(r),now()))
        c.execute('UPDATE corpus_mappings SET payload=?,revision=revision+1 WHERE id=?',(packed(value),key));return mapping_json(c,row(c,'corpus_mappings',key))
class Confirm(Strict):revision:int;confirmed:bool
@router.post('/mappings/{key}/finalize',status_code=201)
def finalize_mapping(key:str,body:Confirm):
    if not body.confirmed:raise HTTPException(422,'请确认知识关联与使用依据')
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');r=row(c,'corpus_mappings',key);revision(r,body.revision);d=mapping_json(c,r)
        if d['stale'] or d['status']!='completed' or not d['payload']:raise HTTPException(409,'关联依据已变化或尚未生成')
        old=c.execute('SELECT id FROM corpus_mapping_versions WHERE mapping_id=? AND revision=?',(key,r['revision'])).fetchone()
        if not old:
            value=validate_mapping(d['payload'],d['knowledge']);snapshot={'analysis_version_id':r['analysis_version_id'],'knowledge':d['knowledge'],'mapping':value,'teacher_confirmed':True,'created_at':now()};v=uid()
            c.execute('INSERT INTO corpus_mapping_versions VALUES(?,?,?,?,?)',(v,key,r['revision'],packed(snapshot),now()))
        return mapping_json(c,row(c,'corpus_mappings',key))
@router.post('/mappings/{key}/revise')
def revise_mapping(key:str,body:Confirm):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');r=row(c,'corpus_mappings',key);revision(r,body.revision);d=mapping_json(c,r)
        if not d['read_only'] or d['stale']:raise HTTPException(409,'仅可继续修订有效的关联终稿')
        c.execute('INSERT INTO corpus_mapping_history VALUES(?,?,?,?,?)',(uid(),key,r['revision'],packed(r),now()))
        c.execute('UPDATE corpus_mappings SET revision=revision+1 WHERE id=?',(key,));return mapping_json(c,row(c,'corpus_mappings',key))
@router.get('/mapping-versions/{key}/download')
def mapping_download(key:str):
    with connect() as c:r=row(c,'corpus_mapping_versions',key)
    return Response(r['snapshot'],media_type='application/json',headers={'Content-Disposition':f'attachment; filename="knowledge-mapping-{key}.json"'})

@router.get('/tasks')
def tasks():
    from .paper_research import card_json
    with connect() as c:
        result=[]
        for r in c.execute('SELECT k.* FROM corpus_card_tasks t JOIN knowledge_runs k ON k.id=t.run_id ORDER BY k.created_at DESC'):
            meta=json.loads(r['input_json'])['corpus_task']
            result.append({'id':r['id'],'revision':r['revision'],'status':r['status'],'error':r['error'],'stale':not corpus_current(c,meta),'summary':next((x.get('summary','') for x in json.loads(r['checks']) if 'summary' in x),''),'cards':[card_json(c,x) for x in c.execute('SELECT * FROM paper_cards WHERE task_id=?',(r['id'],))]})
        return result
class CardStart(Strict):analysis_version_ids:list[str]=Field(min_length=2,max_length=10)
@router.post('/cards',status_code=201)
def cards(body:CardStart):
    from .exam_extraction import open_paper
    config=provider();sources=[];seen=set();exam_id=None
    with connect() as c:
        for key in body.analysis_version_ids:
            if not analysis_current(c,key):raise HTTPException(409,'请选择有效研究终稿')
            v=row(c,'research_analysis_versions',key);f=json.loads(v['snapshot']);identity=fingerprint(f['question'])
            if identity in seen:raise HTTPException(422,'同一道题的重复试卷或不同版本不能当作多道证据')
            seen.add(identity);sources.append({'id':key,'hash':digest(f),'title':f['question']['title']})
            entry=c.execute('SELECT exam_version_id FROM corpus_entries WHERE run_id=?',(f['run_id'],)).fetchone()
            if not entry:raise HTTPException(422,'请选择题库独立研究终稿')
            exam_id=exam_id or entry['exam_version_id']
    project=open_paper(exam_id)
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');meta={'kind':'cards','sources':sources}
        if not corpus_current(c,meta):raise HTTPException(409,'研究终稿在发起期间发生变化')
        run=queue(c,'跨试卷思路卡',{'title':'跨试卷思路卡','chapters':[],'corpus_task':meta},config,10500)
        c.execute('INSERT INTO corpus_card_tasks VALUES(?,?)',(run['id'],project['id']))
        return {'id':run['id'],'status':run['status']}
@router.post('/tasks/{key}/retry')
def retry_task(key:str,body:Confirm):
    from .knowledge import current
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');r=row(c,'knowledge_runs',key);revision(r,body.revision)
        if not json.loads(r['input_json']).get('corpus_task') or r['status'] not in ['failed','interrupted'] or not current(c,r):raise HTTPException(409,'任务不可重试或依据已变化')
        meta=json.loads(r['input_json'])['corpus_task'];config=json.loads(r['model_json'])
        completed={x['step'] for x in c.execute("SELECT step FROM knowledge_calls WHERE run_id=? AND status IN ('succeeded','revalidated')",(key,))}
        count,reserved=c.execute('SELECT count(*),coalesce(sum(reserved_tokens),0) FROM knowledge_calls WHERE run_id=?',(key,)).fetchone()
        if meta['kind']=='mapping':
            from .corpus_worker import knowledge_batches
            groups=knowledge_batches(json.loads(row(c,'corpus_mappings',key)['knowledge']))
            plan=[('corpus:mapping' if len(groups)==1 else f'corpus:mapping:{i+1}',5000) for i in range(len(groups))]
            if len(groups)>1:plan.append(('corpus:mapping-merge',5000))
        else:plan=[('corpus:cards',8000),('corpus:cards-critic',2500)]
        remaining=[tokens for step,tokens in plan if step not in completed]
        config.update(max_calls=max(config['max_calls'],count+len(remaining)),output_token_budget=max(config['output_token_budget'],reserved+sum(remaining)))
        c.execute("UPDATE knowledge_runs SET model_json=?,status='queued',error='',revision=revision+1 WHERE id=?",(packed(config),key));return {'id':key}
