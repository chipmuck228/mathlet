"""Local closed loop: fixed knowledge + confirmed questions -> mapping, training, reader."""
import json
import hashlib
from fastapi import APIRouter,HTTPException
from fastapi.responses import HTMLResponse,Response
from pydantic import Field
from .db import connect,uid,now
from .knowledge import row,revision,packed
from .model_provider import load_provider,public_provider
from .research import version_current,question_current,sources_current,validate_references,validate_text
from .research_models import Strict
from .research_editor import safe_question
from .teaching_models import TeachingBody,TeachingCase

router=APIRouter(prefix='/api/teaching',tags=['section application and training'])
PHASES=['read','relate','plan','solve','check']
PHASE_NAMES={'read':'读懂条件与目标','relate':'连接知识与关系','plan':'选择思路','solve':'独立解题','check':'检验与反思'}
def sha(value):return hashlib.sha256(packed(value).encode()).hexdigest()
def knowledge(c,version_id):
    frozen=json.loads(row(c,'knowledge_versions',version_id)['snapshot'])
    items=[{'ref':version_id+':'+x['knowledge_id'],'title':x['body']['name'],'unit_title':frozen['unit']['title'],'scope':x['scope'],'body':x['body']} for x in frozen['items'] if x['scope']!='excluded']
    return {'version_id':version_id,'title':frozen['unit']['title'],'items':items,'relations':frozen.get('relations',[]),'editorial':frozen.get('editorial',{}),'official_coverage_verified':False}
def teaching_current(c,meta):
    try:
        if not version_current(c,row(c,'knowledge_versions',meta['knowledge_version_id'])):return False
        for key in meta['question_version_ids']:
            v=row(c,'research_question_versions',key);q=row(c,'research_questions',v['question_id'])
            if q['revision']!=v['revision'] or q['confirmed_revision']!=v['revision'] or not question_current(c,q):return False
        for key in meta.get('reused_analysis',{}).values():
            if not sources_current(c,json.loads(row(c,'research_analysis_versions',key)['snapshot'])['input']):return False
        return True
    except HTTPException:return False

def check_case(body,question,know,final=False):
    value=TeachingCase.model_validate(body).model_dump();refs={x['ref'] for x in know['items']}
    if value['question_version_id']!=question['version_id']:raise ValueError('题目版本与任务不符')
    matched=value['relevance'] in {'primary','combined','optional'}
    if not matched:
        if value['analysis'] is not None or value['applications'] or value['training']:raise ValueError('未匹配或待判断题目不能伪装成已完成的解题训练；请清空解析、应用映射和训练')
        return value
    if not value['analysis'] or not value['applications']:raise ValueError('匹配题目必须有解析与应用映射')
    analysis=value['analysis'];validate_references(analysis,'analysis',{'snapshot':packed({'items':know['items']})})
    approaches={x['id']:x for x in analysis['approaches']};ids=set();used=set()
    for m in value['applications']:
        if m['id'] in ids:raise ValueError('应用映射编号重复')
        ids.add(m['id']);used.add(m['knowledge_ref'])
        if m['knowledge_ref'] not in refs:raise ValueError('应用映射引用了终稿外的知识')
        if m['quote'] not in question['statement'] and m['quote'] not in question['diagram_description']:raise ValueError('应用映射的题目片段不是题干或图形条件中的逐字原文')
        a=approaches.get(m['approach_id'])
        if not a or m['step_index']>=len(a['steps']):raise ValueError('应用映射引用不存在的解法或推理步骤（步骤从0编号）')
        if m['knowledge_ref'] not in a['steps'][m['step_index']]['knowledge_refs']:raise ValueError('映射知识未出现在所引用的推理步骤中')
    needed={x['ref'] for x in analysis['knowledge_breakdown']}
    needed.update(r for x in analysis['assessed_points'] for r in x['knowledge_refs'])
    needed.update(r for a in analysis['approaches'] for s in a['steps'] for r in s['knowledge_refs'])
    if not needed<=used:raise ValueError('解析中使用的知识尚未解释如何与题目及步骤连接')
    if [x['phase'] for x in value['training']]!=PHASES:raise ValueError('思路训练须依次覆盖读题、连接知识、选择思路、独立解题、检验反思五阶段')
    for t in value['training']:
        if any(not s.strip() for s in t['hints']+t['checkpoints']):raise ValueError('训练提示及检查要点不得为空')
        if not set(t['mapping_ids'])<=ids:raise ValueError('训练引用不存在的应用映射')
    if final and (value['knowledge_gaps'] or analysis['missing_information']):raise ValueError('匹配题仍有知识或条件缺口，请补全依据，或改为不纳入本小节的题目')
    if final:
        def walk(x):
            if isinstance(x,str):validate_text(x)
            elif isinstance(x,list):
                for v in x:walk(v)
            elif isinstance(x,dict):
                for v in x.values():walk(v)
        walk(value)
    return value

def inputs(c,meta):
    know=knowledge(c,meta['knowledge_version_id']);questions=[]
    for key in meta['question_version_ids']:
        q=json.loads(row(c,'research_question_versions',key)['snapshot']);q['version_id']=key;questions.append(q)
    return know,questions

def checked(c,meta,body,final=False):
    value=TeachingBody.model_validate(body).model_dump();know,questions=inputs(c,meta)
    ids=[x['question_version_id'] for x in value['cases']]
    if len(set(ids))!=len(ids) or set(ids)!=set(meta['question_version_ids']):raise ValueError('稿件必须逐一保留本轮选择的题目，不得重复或悄悄漏题')
    byid={q['version_id']:q for q in questions}
    for case in value['cases']:check_case(case,byid[case['question_version_id']],know,final)
    if final and not any(x['relevance'] in {'primary','combined','optional'} for x in value['cases']):raise ValueError('没有匹配本小节的题目，请更换代表题后再生成学生读物')
    return value

def report(know,body):
    result=[]
    for k in know['items']:
        applications=[{'question_version_id':c['question_version_id'],'mapping_id':m['id'],'role':c['relevance']} for c in body['cases'] for m in c['applications'] if m['knowledge_ref']==k['ref']]
        result.append({'ref':k['ref'],'title':k['title'],'applications':applications,'status':'有应用证据' if applications else '当前选题暂无应用证据，不代表不重要'})
    return result

def detail(c,run):
    meta=json.loads(run['input_json']).get('teaching_task')
    if not meta:raise HTTPException(404,'小节应用任务不存在')
    k,qs=inputs(c,meta);r=c.execute('SELECT * FROM teaching_manuscripts WHERE run_id=?',(run['id'],)).fetchone()
    result={key:run[key] for key in ['id','status','revision','error','created_at']}|{'stale':not teaching_current(c,meta),'knowledge':k,'questions':qs,'task':meta,'manuscript':None,'calls':[dict(x) for x in c.execute('SELECT step,status,error,reserved_tokens FROM knowledge_calls WHERE run_id=? ORDER BY rowid',(run['id'],))]}
    if r:
        m=dict(r)
        for key in ['payload','original_payload','checks']:m[key]=json.loads(m[key])
        m['finals']=[dict(x) for x in c.execute('SELECT id,revision,created_at FROM teaching_versions WHERE run_id=? ORDER BY created_at DESC',(run['id'],))]
        m['read_only']=any(x['revision']==m['revision'] for x in m['finals']);m['blockers']=[]
        try:checked(c,meta,m['payload'],True)
        except (ValueError,HTTPException) as exc:m['blockers']=[str(exc.detail) if isinstance(exc,HTTPException) else str(exc)]
        m['coverage']=report(k,m['payload']);result['manuscript']=m
    return result

class Start(Strict):
    knowledge_version_id:str
    question_version_ids:list[str]=Field(min_length=1,max_length=4)
    instruction:str=Field(default='',max_length=3000)
    request_key:str=Field(min_length=8,max_length=100)
@router.post('/runs',status_code=201)
def start(body:Start):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');existing=c.execute('SELECT * FROM teaching_requests WHERE request_key=?',(body.request_key,)).fetchone();signature=sha(body.model_dump(exclude={'request_key'}))
        if existing:
            if existing['input_hash']!=signature:raise HTTPException(409,'请求编号对应不同的材料')
            return detail(c,row(c,'knowledge_runs',existing['run_id']))
        if len(set(body.question_version_ids))!=len(body.question_version_ids):raise HTTPException(422,'题目版本不可重复')
        meta=body.model_dump(exclude={'request_key'});meta['reused_analysis']={}
        if not teaching_current(c,meta):raise HTTPException(409,'请选择当前有效的知识终稿与已确认完整题目')
        know,qs=inputs(c,meta)
        if not know['items'] or len(know['items'])>80 or len(packed(know))>120000:raise HTTPException(422,'本轮知识范围需为1—80项，正文不超过120000字符')
        identities=[q['question_id'] for q in qs]
        if len(set(identities))!=len(identities):raise HTTPException(422,'同一题目的不同版本不能作为不同代表题')
        if any(len(packed(safe_question(q)))>24000 for q in qs):raise HTTPException(422,'完整题目过长，请先整理题目')
        refs={x['ref'] for x in know['items']}
        for q in qs:
            for v in c.execute('SELECT * FROM research_analysis_versions ORDER BY created_at DESC'):
                f=json.loads(v['snapshot'])
                if f['input'].get('question_version_id')!=q['version_id'] or not sources_current(c,f['input']):continue
                context_refs={x['ref'] for x in f['knowledge']['items']}
                if context_refs and context_refs<=refs:
                    meta['reused_analysis'][q['version_id']]=v['id'];break
        config=load_provider();reserve=len(qs)*7000
        if not config.api_key or not config.model:raise HTTPException(422,'请先在小节编制或知识与关系中配置模型')
        if config.output_token_budget<reserve or config.max_calls<len(qs)*2:raise HTTPException(422,f'本轮需至少{reserve}输出 tokens 和{len(qs)*2}次调用预算')
        key=uid();unit=uid();snapshot={'schema_version':1,'title':know['title']+' · 应用与训练','chapters':[],'teaching_task':meta}
        c.execute('INSERT INTO knowledge_units(id,title,chapters,target,notes,origin,created_at) VALUES(?,?,?,?,?,?,?)',(unit,snapshot['title'],'[]','小节应用训练','',packed({'internal_teaching':True}),now()))
        c.execute("INSERT INTO knowledge_runs(id,unit_id,input_revision,input_json,model_json,status,stage,created_at,updated_at) VALUES(?,?,?,?,?,'queued','teaching',?,?)",(key,unit,1,packed(snapshot),packed(public_provider(config)),now(),now()))
        c.execute('INSERT INTO teaching_requests VALUES(?,?,?)',(body.request_key,key,signature))
        return detail(c,row(c,'knowledge_runs',key))
@router.get('/runs')
def runs():
    with connect() as c:return [{k:r[k] for k in ['id','status','created_at']}|{'title':json.loads(r['input_json'])['title']} for r in c.execute('SELECT * FROM knowledge_runs ORDER BY created_at DESC') if json.loads(r['input_json']).get('teaching_task')]
@router.get('/runs/{run_id}')
def get_run(run_id:str):
    with connect() as c:return detail(c,row(c,'knowledge_runs',run_id))
class Rev(Strict):revision:int
@router.post('/runs/{run_id}/retry')
def retry(run_id:str,body:Rev):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');r=row(c,'knowledge_runs',run_id);revision(r,body.revision);meta=json.loads(r['input_json']).get('teaching_task')
        if not meta or r['status'] not in {'failed','interrupted'} or not teaching_current(c,meta):raise HTTPException(409,'仅可重试依据未变化的失败任务')
        c.execute("UPDATE knowledge_runs SET status='queued',error='',revision=revision+1,updated_at=? WHERE id=?",(now(),run_id));return detail(c,row(c,'knowledge_runs',run_id))
class Save(Strict):
    revision:int
    run_revision:int
    body:TeachingBody
@router.put('/runs/{run_id}')
def save(run_id:str,body:Save):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');r=row(c,'knowledge_runs',run_id);revision(r,body.run_revision);m=dict(c.execute('SELECT * FROM teaching_manuscripts WHERE run_id=?',(run_id,)).fetchone() or {})
        if not m:raise HTTPException(409,'任务尚无完成稿件')
        revision(m,body.revision)
        d=detail(c,r)
        if d['stale'] or r['status']!='completed' or d['manuscript']['read_only']:raise HTTPException(409,'来源已变化、任务未完成或稿件已固定，请先继续修订')
        try:value=checked(c,d['task'],body.body.model_dump())
        except ValueError as exc:raise HTTPException(422,str(exc)) from None
        c.execute('INSERT INTO teaching_history VALUES(?,?,?,?,?)',(uid(),run_id,m['revision'],packed(m),now()))
        c.execute('UPDATE teaching_manuscripts SET payload=?,revision=revision+1 WHERE run_id=?',(packed(value),run_id));return detail(c,r)
class Final(Strict):revision:int;run_revision:int;confirmed:bool
@router.post('/runs/{run_id}/finalize',status_code=201)
def finalize(run_id:str,body:Final):
    if not body.confirmed:raise HTTPException(422,'请确认知识应用映射、训练提示与解析均已审定')
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');r=row(c,'knowledge_runs',run_id);revision(r,body.run_revision);d=detail(c,r);m=d['manuscript']
        if not m:raise HTTPException(409,'任务尚无完成稿件')
        revision(m,body.revision)
        if d['stale'] or r['status']!='completed':raise HTTPException(409,'来源已变化或任务未完成，不能定稿')
        old=c.execute('SELECT id FROM teaching_versions WHERE run_id=? AND revision=?',(run_id,body.revision)).fetchone()
        if old:return {'id':old['id']}
        try:value=checked(c,d['task'],m['payload'],True)
        except ValueError as exc:raise HTTPException(422,str(exc)) from None
        from .teaching_reader import render_reader
        snapshot={'body':value,'knowledge':d['knowledge'],'questions':d['questions'],'coverage':m['coverage'],'checks':m['checks'],'sources':d['task'],'model':json.loads(r['model_json']),'teacher_confirmed':True,'parent_version':m['parent_version'],'created_at':now()}
        try:html=render_reader(snapshot)
        except ValueError as exc:raise HTTPException(422,'读物公式排版失败，请核对知识或题目公式：'+str(exc)) from None
        key=uid()
        c.execute('INSERT INTO teaching_versions VALUES(?,?,?,?,?,?)',(key,run_id,body.revision,packed(snapshot),html,now()));return {'id':key}
@router.get('/versions/{version_id}/download')
def download(version_id:str):
    with connect() as c:v=row(c,'teaching_versions',version_id)
    return HTMLResponse(v['rendered_html'],headers={'Content-Disposition':f'attachment; filename="mathlet-section-{version_id}.html"'})
@router.get('/versions/{version_id}/reader')
def reader(version_id:str):
    with connect() as c:v=row(c,'teaching_versions',version_id)
    return HTMLResponse(v['rendered_html'])
@router.get('/versions/{version_id}/json')
def json_version(version_id:str):
    with connect() as c:v=row(c,'teaching_versions',version_id)
    return Response(v['snapshot'],media_type='application/json')
@router.post('/versions/{version_id}/revise',status_code=201)
def revise(version_id:str):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');v=row(c,'teaching_versions',version_id);old=row(c,'knowledge_runs',v['run_id']);f=json.loads(v['snapshot']);meta=f['sources']
        if not teaching_current(c,meta):raise HTTPException(409,'旧终稿依据已变化，请选择当前材料重新编制；旧文件保留')
        key=uid();unit=uid();snapshot=json.loads(old['input_json'])
        c.execute('INSERT INTO knowledge_units(id,title,chapters,target,notes,origin,created_at) VALUES(?,?,?,?,?,?,?)',(unit,f['body']['title'],'[]','小节应用训练','',packed({'internal_teaching':True}),now()))
        c.execute("INSERT INTO knowledge_runs(id,unit_id,input_revision,input_json,model_json,status,stage,created_at,updated_at) VALUES(?,?,?,?,?,'completed','completed',?,?)",(key,unit,1,packed(snapshot),old['model_json'],now(),now()))
        c.execute('INSERT INTO teaching_manuscripts(run_id,payload,original_payload,checks,parent_version) VALUES(?,?,?,?,?)',(key,packed(f['body']),packed(f['body']),packed(f['checks']),version_id));return detail(c,row(c,'knowledge_runs',key))

@router.get('/runs/{run_id}/preview')
def preview(run_id:str):
    from .teaching_reader import render_reader
    with connect() as c:d=detail(c,row(c,'knowledge_runs',run_id))
    if not d['manuscript']:raise HTTPException(409,'尚无完成草稿可供预览')
    snapshot={'body':d['manuscript']['payload'],'knowledge':d['knowledge'],'questions':d['questions'],'coverage':d['manuscript']['coverage'],'created_at':now(),'teacher_confirmed':False}
    try:return HTMLResponse(render_reader(snapshot))
    except ValueError as exc:raise HTTPException(422,'草稿公式排版失败：'+str(exc)) from None
