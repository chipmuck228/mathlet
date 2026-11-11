"""Knowledge draft authoring: model proposals, human review, immutable snapshots."""
import json
import hashlib
from typing import Literal
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from .db import connect, now, uid
from .knowledge_models import KnowledgeBody, Scope
from .model_provider import Provider, load_provider, public_provider, save_provider
from .formulas import parts_from_text, render_latex

router=APIRouter(prefix='/api/knowledge', tags=['knowledge'])

def packed(value): return json.dumps(value,ensure_ascii=False)
def row(c, table, key):
    found=c.execute(f'SELECT * FROM {table} WHERE id=?',(key,)).fetchone()
    if found is None: raise HTTPException(404,'记录不存在')
    return dict(found)
def revision(record, expected):
    if record['revision']!=expected: raise HTTPException(409,'内容已变化，请保留输入后刷新')

def origin_stale(c, unit):
    origin=json.loads(unit['origin'])
    if origin.get('plan_id'):
        from .planning import plan_json
        record=c.execute('SELECT * FROM plans WHERE id=?',(origin['plan_id'],)).fetchone()
        return record is None or record['revision']!=origin['plan_revision'] or not plan_json(c,record)['confirmed']
    return False

def current(c, run):
    unit=row(c,'knowledge_units',run['unit_id'])
    if unit['revision']!=run['input_revision'] or origin_stale(c,unit): return False
    snapshot=json.loads(run['input_json'])
    if snapshot.get('planning_task'):
        from .planning_ai import sources_current
        return sources_current(c,snapshot)
    meta=snapshot.get('action_task')
    if meta:
        parent=c.execute('SELECT * FROM knowledge_runs WHERE id=?',(meta['base_run_id'],)).fetchone()
        return bool(parent) and parent['revision']==meta['base_revision'] and parent['input_revision']==unit['revision']
    return True


def normalized_checks(c,run):
    checks=json.loads(run['checks'])
    uncertainties={}
    for value in c.execute('SELECT knowledge_id,body FROM knowledge_candidates WHERE run_id=?',(run['id'],)):
        message=json.loads(value['body']).get('uncertainty','').strip()
        if message:
            key='uncertainty:'+value['knowledge_id']+':'+hashlib.sha256(message.encode()).hexdigest()[:12]
            uncertainties[key]={'id':key,'knowledge_id':value['knowledge_id'],'message':message,'category':'unclassified','origin':'uncertainty'}
    result=[]
    for i,check in enumerate(checks):
        if check.get('origin')=='uncertainty' and check.get('id') not in uncertainties: continue
        result.append({'category':'unclassified',**check,'id':check.get('id',f"check:{i}")})
    for key,value in uncertainties.items():
        if not any(x['id']==key for x in result): result.append(value)
    return result

def candidate_json(record):
    record=dict(record);record['body']=json.loads(record['body']);record['original_body']=json.loads(record['original_body'])
    record['origin']='model_prior' if record['original_body'] else 'teacher_authored'
    record['warnings']=body_warnings(record['body'])
    record['field_content']={key:parts_from_text(value) for key,value in record['body'].items() if isinstance(value,str)}
    record['formula_mathml']=''
    if record['body'].get('formula'):
        try: record['formula_mathml']=render_latex(record['body']['formula'])
        except ValueError: pass
    return record

def body_warnings(body):
    notes=[]
    for field,label in [('name','知识名称'),('statement','准确表述'),('conditions','成立条件'),('positive_example','正例'),('misconception','易错点／反例'),('mastery','掌握表现')]:
        if not body.get(field,'').strip(): notes.append(f'缺少{label}')
    if body.get('kind')=='method' and not body.get('method_steps','').strip(): notes.append('方法条目缺少步骤')
    try:
        for key,value in body.items():
            if isinstance(value,str): parts_from_text(value,strict=True)
        if body.get('formula'): render_latex(body['formula'])
    except ValueError as exc: notes.append('公式检查：'+str(exc))
    return notes

class UnitInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    title: str=Field(min_length=1,max_length=160)
    chapters: list[str]=Field(min_length=1,max_length=40)
    target: str=Field(default='已学习初中数学的中考复习学生；基础程度不同',min_length=1,max_length=1500)
    notes: str=Field(default='',max_length=5000)

def validate_unit(body):
    if not body.title.strip() or not body.target.strip() or any(not x.strip() or len(x)>200 for x in body.chapters):
        raise HTTPException(422,'章节标题不能为空且每项不超过200字')

def unit_json(c, value):
    value=dict(value);value['chapters']=json.loads(value['chapters']);value['origin_info']=json.loads(value['origin'])
    value['stale']=origin_stale(c,value)
    return value

@router.get('/provider')
def provider_info(): return public_provider()
@router.put('/provider')
def configure_provider(body: Provider): return save_provider(body)

@router.get('/units')
def units():
    with connect() as c: return [unit_json(c,r) for r in c.execute('SELECT * FROM knowledge_units ORDER BY created_at DESC') if not json.loads(r['origin']).get('internal_planning')]

@router.post('/units',status_code=201)
def create_unit(body: UnitInput):
    validate_unit(body)
    with connect() as c:
        key=uid(); c.execute('INSERT INTO knowledge_units(id,title,chapters,target,notes,origin,created_at) VALUES(?,?,?,?,?,?,?)',
            (key,body.title.strip(),packed(body.chapters),body.target,body.notes,'{}',now()))
        return unit_json(c,row(c,'knowledge_units',key))

class PlanUnitInput(BaseModel):
    plan_id: str
    unit_id: str
    plan_revision: int

@router.post('/units/from-plan',status_code=201)
def from_plan(body: PlanUnitInput):
    from .planning import plan_json
    with connect() as c:
        plan=row(c,'plans',body.plan_id);revision(plan,body.plan_revision)
        dbplan=c.execute('SELECT * FROM plans WHERE id=?',(body.plan_id,)).fetchone()
        if not plan_json(c,dbplan)['confirmed']: raise HTTPException(409,'请先确认当前内容规划')
        payload=json.loads(plan['payload']); source=next((u for u in payload['units'] if u['id']==body.unit_id),None)
        if not source: raise HTTPException(404,'规划单元不存在')
        selected=set(source.get('node_ids',[]))
        if payload.get('mode')=='ai_curriculum':
            nodes={n['id']:n for n in payload['nodes']}
            if not selected or any(not nodes[k]['included'] or not nodes[nodes[k]['parent_id']]['included'] for k in selected): raise HTTPException(422,'此二级主题或所属领域未纳入规划')
        for previous in c.execute('SELECT * FROM knowledge_units'):
            old_origin=json.loads(previous['origin'])
            if old_origin.get('plan_id')==body.plan_id and old_origin.get('unit_id')==body.unit_id and old_origin.get('plan_revision')==body.plan_revision:
                return unit_json(c,previous)
        titles=[n['title'] for n in payload['nodes'] if n['id'] in selected]
        body_unit=UnitInput(title=source['title'],chapters=titles or [source['title']],notes=source.get('goals',''))
        key=uid();origin={'plan_id':body.plan_id,'unit_id':body.unit_id,'plan_revision':body.plan_revision}
        origin['learning_requirements']=[{'text':r['text'],'source_id':r['source_id'],'origin':r.get('origin','official_excerpt')} for r in payload['requirements'] if body.unit_id in r['unit_ids']]
        origin['domain']=source.get('volume','')
        c.execute('INSERT INTO knowledge_units(id,title,chapters,target,notes,origin,created_at) VALUES(?,?,?,?,?,?,?)',
            (key,body_unit.title,packed(body_unit.chapters),body_unit.target,body_unit.notes,packed(origin),now()))
        return unit_json(c,row(c,'knowledge_units',key))

class UnitEdit(UnitInput): revision:int
@router.put('/units/{unit_id}')
def edit_unit(unit_id:str,body:UnitEdit):
    validate_unit(body)
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');old=row(c,'knowledge_units',unit_id);revision(old,body.revision)
        c.execute('UPDATE knowledge_units SET title=?,chapters=?,target=?,notes=?,revision=revision+1 WHERE id=?',
            (body.title,packed(body.chapters),body.target,body.notes,unit_id))
        return unit_json(c,row(c,'knowledge_units',unit_id))

class RunInput(BaseModel):
    unit_revision:int
    consent:bool
    max_items:int=Field(default=12,ge=1,le=30)
    base_run_id:str|None=None

@router.post('/units/{unit_id}/runs',status_code=201)
def start_run(unit_id:str,body:RunInput):
    provider=load_provider()
    if not provider.api_key or not provider.model: raise HTTPException(422,'请先配置模型名称与 API Key；尚未调用模型')
    if not body.consent: raise HTTPException(422,'请确认本次发送的服务及单元范围')
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');unit=row(c,'knowledge_units',unit_id);revision(unit,body.unit_revision)
        if origin_stale(c,unit): raise HTTPException(409,'关联规划已变化，请重新从当前规划创建知识单元')
        catalog=[]
        if body.base_run_id:
            base=row(c,'knowledge_runs',body.base_run_id)
            if base['unit_id']!=unit_id or not current(c,base): raise HTTPException(409,'原候选的单元范围已变化，请重新生成清单')
            catalog=json.loads(base['catalog'])
            if not catalog: raise HTTPException(422,'原任务尚无清单，请先重试或重新生成清单')
        snapshot={'schema_version':1,'prompt_version':'knowledge-v1','title':unit['title'],'chapters':json.loads(unit['chapters']),
            'target':unit['target'],'notes':unit['notes'],'max_items':body.max_items,
            'basis':'model_prior','official_coverage_verified':False,'origin':json.loads(unit['origin']),
            'learning_requirements':json.loads(unit['origin']).get('learning_requirements',[])}
        key=uid();state='awaiting_selection' if catalog else 'queued'
        c.execute('INSERT INTO knowledge_runs(id,unit_id,input_revision,input_json,model_json,status,stage,catalog,base_run_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (key,unit_id,unit['revision'],packed(snapshot),packed(public_provider(provider)),state,'details' if catalog else 'catalog',packed(catalog),body.base_run_id,now(),now()))
        return run_json(c,row(c,'knowledge_runs',key))

def run_json(c,run):
    result=dict(run)
    for field in ['input_json','model_json','catalog','selected_ids','checks']: result[field]=json.loads(result[field])
    result['checks']=normalized_checks(c,run)
    result['stale']=not current(c,run)
    result['items']=[candidate_json(r) for r in c.execute('SELECT * FROM knowledge_candidates WHERE run_id=? ORDER BY rowid',(run['id'],))]
    result['calls']=[dict(r)|{'usage':json.loads(r['usage']) if r['usage'] else None} for r in c.execute('SELECT id,step,status,usage,error,reserved_tokens,created_at FROM knowledge_calls WHERE run_id=? ORDER BY rowid',(run['id'],))]
    from .knowledge_actions import outputs, relations
    result['outputs']=outputs(c,run['id'])
    result['relations']=relations(c,run['id'])
    result['tasks']=[dict(x)|{'input_json':packed({'action_task':{'action':json.loads(x['input_json'])['action_task']['action']}})} for x in c.execute('SELECT id,status,revision,input_json FROM knowledge_runs WHERE base_run_id=? ORDER BY created_at DESC',(run['id'],)) if json.loads(x['input_json']).get('action_task')]
    return result

@router.get('/units/{unit_id}/runs')
def runs(unit_id:str):
    with connect() as c:
        row(c,'knowledge_units',unit_id)
        return [{k:r[k] for k in ['id','status','stage','error','revision','created_at']} for r in c.execute('SELECT * FROM knowledge_runs WHERE unit_id=? ORDER BY created_at DESC',(unit_id,)) if not json.loads(r['input_json']).get('action_task')]
@router.get('/runs/{run_id}')
def run_detail(run_id:str):
    with connect() as c: return run_json(c,row(c,'knowledge_runs',run_id))

class ExpandInput(BaseModel):
    revision:int
    selected_ids:list[str]=Field(min_length=1,max_length=30)
@router.post('/runs/{run_id}/expand')
def expand(run_id:str,body:ExpandInput):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');run=row(c,'knowledge_runs',run_id);revision(run,body.revision)
        if run['status']!='awaiting_selection' or not current(c,run): raise HTTPException(409,'任务状态或单元已变化')
        allowed={x['id'] for x in json.loads(run['catalog'])}
        if len(set(body.selected_ids))!=len(body.selected_ids) or not set(body.selected_ids)<=allowed: raise HTTPException(422,'知识清单选择无效')
        model=json.loads(run['model_json'])
        used,count=c.execute('SELECT coalesce(sum(reserved_tokens),0),count(*) FROM knowledge_calls WHERE run_id=?',(run_id,)).fetchone()
        remaining_calls=(len(body.selected_ids)+3)//4+1
        if used+((len(body.selected_ids)+3)//4)*5000+2200>model['output_token_budget'] or count+remaining_calls>model['max_calls']:
            raise HTTPException(422,'所选条目超过此任务的调用／输出预留预算，请减少选择，或提高配置预算后另建新候选')
        c.execute("UPDATE knowledge_runs SET selected_ids=?,status='queued',stage='details',revision=revision+1,updated_at=? WHERE id=?",(packed(body.selected_ids),now(),run_id))
        return run_json(c,row(c,'knowledge_runs',run_id))

class RevisionInput(BaseModel): revision:int
@router.post('/runs/{run_id}/retry')
def retry(run_id:str,body:RevisionInput):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');run=row(c,'knowledge_runs',run_id);revision(run,body.revision)
        if run['status'] not in {'failed','interrupted'} or not current(c,run): raise HTTPException(409,'只有当前范围内失败或中断的任务可以重试')
        c.execute("UPDATE knowledge_runs SET status='queued',error='',revision=revision+1,updated_at=? WHERE id=?",(now(),run_id))
        return run_json(c,row(c,'knowledge_runs',run_id))

class CandidateEdit(BaseModel):
    revision:int
    body:KnowledgeBody
    scope:Scope
    review_note:str=Field(default='',max_length=3000)
@router.put('/candidates/{candidate_id}')
def edit_candidate(candidate_id:str,body:CandidateEdit):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');old=row(c,'knowledge_candidates',candidate_id);revision(old,body.revision)
        run=row(c,'knowledge_runs',old['run_id'])
        if run['status']!='completed' or not current(c,run): raise HTTPException(409,'任务尚未完成或候选已过期；输入未覆盖')
        c.execute('INSERT INTO knowledge_candidate_history VALUES(?,?,?,?,?)',(uid(),candidate_id,old['revision'],packed(old),now()))
        c.execute("UPDATE knowledge_candidates SET body=?,scope=?,review_note=?,review_state='pending',reviewer='',revision=revision+1 WHERE id=?",(packed(body.body.model_dump()),body.scope,body.review_note,candidate_id))
        c.execute('UPDATE knowledge_runs SET revision=revision+1,updated_at=? WHERE id=?',(now(),run['id']))
        return candidate_json(row(c,'knowledge_candidates',candidate_id))

class ReviewItem(BaseModel): id:str; revision:int
class GroupReview(BaseModel):
    revision:int
    items:list[ReviewItem]=Field(min_length=1,max_length=30)
    reviewer:str=Field(min_length=1,max_length=80)
    confirmed:bool
    decision:Literal['approve','return']='approve'
    note:str=Field(default='',max_length=3000)
@router.post('/runs/{run_id}/review')
def review(run_id:str,body:GroupReview):
    if not body.confirmed or not body.reviewer.strip(): raise HTTPException(422,'请填写审核人并明确确认数学内容和适用范围')
    if body.decision=='return' and not body.note.strip(): raise HTTPException(422,'请填写退回原因')
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');run=row(c,'knowledge_runs',run_id);revision(run,body.revision)
        if run['status']!='completed' or not current(c,run): raise HTTPException(409,'任务未完成或范围已变化')
        if len({i.id for i in body.items})!=len(body.items): raise HTTPException(422,'重复条目')
        chosen=[]
        for item in body.items:
            value=row(c,'knowledge_candidates',item.id);revision(value,item.revision)
            if value['run_id']!=run_id: raise HTTPException(422,'不能跨候选批次确认')
            if body.decision=='approve' and value['scope']=='pending': raise HTTPException(422,'请先确定每项的基础／综合／拓展／不纳入范围')
            warnings=body_warnings(json.loads(value['body']))
            relevant=[x for x in normalized_checks(c,run) if x['knowledge_id']==value['knowledge_id']]
            unresolved=[x for x in relevant if x.get('origin')=='uncertainty' and x['category'] in {'unclassified','correctness'}]
            if body.decision=='approve' and value['scope']!='excluded' and unresolved: raise HTTPException(422,'未解决问题需修正正文并清空；范围或教学问题可先分类并记录处理依据')
            if body.decision=='approve' and value['scope']!='excluded' and warnings: raise HTTPException(422, '请先处理条目疑问：'+'；'.join(warnings))
            if body.decision=='approve' and value['scope']!='excluded' and any(i.get('category')!='system' for i in relevant) and not value['review_note'].strip():
                raise HTTPException(422,'此条目有AI复核意见，请填写教师处理说明后确认')
            chosen.append(value)
        for value in chosen:
            c.execute('INSERT INTO knowledge_candidate_history VALUES(?,?,?,?,?)',(uid(),value['id'],value['revision'],packed(value),now()))
            state='approved' if body.decision=='approve' else 'returned'
            note=value['review_note'] if state=='approved' else (value['review_note']+'\n退回：'+body.note.strip()).strip()
            c.execute("UPDATE knowledge_candidates SET review_state=?,reviewer=?,review_note=?,revision=revision+1 WHERE id=?",(state,body.reviewer.strip(),note,value['id']))
        c.execute('UPDATE knowledge_runs SET revision=revision+1,updated_at=? WHERE id=?',(now(),run_id))
        return run_json(c,row(c,'knowledge_runs',run_id))

@router.get('/candidates/{candidate_id}/history')
def history(candidate_id:str):
    with connect() as c:
        row(c,'knowledge_candidates',candidate_id)
        return [dict(r)|{'snapshot':json.loads(r['snapshot'])} for r in c.execute('SELECT * FROM knowledge_candidate_history WHERE candidate_id=? ORDER BY revision DESC',(candidate_id,))]

@router.post('/runs/{run_id}/versions',status_code=201)
def freeze(run_id:str,body:RevisionInput):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');run=row(c,'knowledge_runs',run_id);revision(run,body.revision)
        if run['status']!='completed' or not current(c,run): raise HTTPException(409,'候选已过期或未完成，不能固定知识版本')
        existing=c.execute('SELECT * FROM knowledge_versions WHERE run_id=? AND run_revision=?',(run_id,run['revision'])).fetchone()
        if existing: return dict(existing)|{'snapshot':json.loads(existing['snapshot'])}
        items=[candidate_json(r) for r in c.execute("SELECT * FROM knowledge_candidates WHERE run_id=? AND review_state='approved'",(run_id,))]
        included=[x for x in items if x['scope']!='excluded']
        if not included: raise HTTPException(422,'至少需要一个已审核且纳入的知识条目')
        snapshot={'schema_version':1,'unit':unit_json(c,row(c,'knowledge_units',run['unit_id'])), 'model':json.loads(run['model_json']), 'input':json.loads(run['input_json']), 'run_id':run_id,'run_revision':run['revision'],
            'items':items,'reviewed_count':len(items),'selected_count':len(json.loads(run['selected_ids'])),
            'official_coverage_verified':False,'basis':'model_prior_and_teacher_review','checks':normalized_checks(c,run)}
        from .knowledge_actions import relations
        included_ids={x['knowledge_id'] for x in included}
        snapshot['relations']=[edge for edge in relations(c,run_id) if edge['usable'] and edge['body']['source_id'] in included_ids and edge['body']['target_id'] in included_ids]
        key=uid();c.execute('INSERT INTO knowledge_versions VALUES(?,?,?,?,?,?)',(key,run['unit_id'],run_id,run['revision'],packed(snapshot),now()))
        return {'id':key,'snapshot':snapshot}

@router.get('/units/{unit_id}/versions')
def versions(unit_id:str):
    with connect() as c:
        row(c,'knowledge_units',unit_id)
        return [dict(r) for r in c.execute('SELECT id,run_id,run_revision,created_at FROM knowledge_versions WHERE unit_id=? ORDER BY created_at DESC',(unit_id,))]
@router.get('/versions/{version_id}/download')
def download(version_id:str):
    with connect() as c: version=row(c,'knowledge_versions',version_id)
    return Response(version['snapshot'],media_type='application/json',headers={'Content-Disposition':f'attachment; filename="mathlet-knowledge-{version_id[:8]}.json"'})

class ManualItem(BaseModel):
    revision:int
    body:KnowledgeBody
    scope:Scope='pending'
@router.post('/runs/{run_id}/items',status_code=201)
def add_item(run_id:str,body:ManualItem):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');run=row(c,'knowledge_runs',run_id);revision(run,body.revision)
        if run['status']!='completed' or not current(c,run): raise HTTPException(409,'请在当前已完成候选中补充知识')
        catalog=json.loads(run['catalog']);selected=json.loads(run['selected_ids'])
        if len(selected)>=30: raise HTTPException(422,'本批最多30项，请另建单元或批次')
        if any(json.loads(r['body'])['name'].strip().casefold()==body.body.name.strip().casefold() for r in c.execute('SELECT body FROM knowledge_candidates WHERE run_id=?',(run_id,))):
            raise HTTPException(422,'本批已有同名知识，请修改现有条目或明确区分含义')
        knowledge_id=uid();key=uid();catalog.append({'id':knowledge_id,'name':body.body.name,'kind':body.body.kind,'reason':'教师补充'})
        selected.append(knowledge_id)
        c.execute('INSERT INTO knowledge_candidates(id,run_id,knowledge_id,body,original_body,scope) VALUES(?,?,?,?,?,?)',(key,run_id,knowledge_id,packed(body.body.model_dump()),'{}',body.scope))
        c.execute('UPDATE knowledge_runs SET catalog=?,selected_ids=?,revision=revision+1,updated_at=? WHERE id=?',(packed(catalog),packed(selected),now(),run_id))
        return candidate_json(row(c,'knowledge_candidates',key))

class GroupScope(BaseModel):
    revision:int
    items:list[ReviewItem]=Field(min_length=1,max_length=30)
    scope:Scope
@router.post('/runs/{run_id}/scope')
def group_scope(run_id:str,body:GroupScope):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');run=row(c,'knowledge_runs',run_id);revision(run,body.revision)
        if run['status']!='completed' or not current(c,run): raise HTTPException(409,'任务未完成或候选已过期')
        if len({i.id for i in body.items})!=len(body.items): raise HTTPException(422,'重复条目')
        items=[]
        for item in body.items:
            old=row(c,'knowledge_candidates',item.id);revision(old,item.revision)
            if old['run_id']!=run_id: raise HTTPException(422,'不能跨批次修改范围')
            items.append(old)
        for old in items:
            c.execute('INSERT INTO knowledge_candidate_history VALUES(?,?,?,?,?)',(uid(),old['id'],old['revision'],packed(old),now()))
            c.execute("UPDATE knowledge_candidates SET scope=?,review_state='pending',reviewer='',revision=revision+1 WHERE id=?",(body.scope,old['id']))
        c.execute('UPDATE knowledge_runs SET revision=revision+1,updated_at=? WHERE id=?',(now(),run_id))
        return run_json(c,row(c,'knowledge_runs',run_id))

@router.get('/runs/{run_id}/artifacts')
def artifacts(run_id:str):
    with connect() as c:
        run=row(c,'knowledge_runs',run_id)
        return {'input':json.loads(run['input_json']),'model':json.loads(run['model_json']),
            'calls':[dict(r) for r in c.execute('SELECT step,status,request_json,raw_response,usage,error FROM knowledge_calls WHERE run_id=? ORDER BY rowid',(run_id,))]}
