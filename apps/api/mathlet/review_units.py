"""Knowledge final -> all current studies -> evidence mapping -> cards/training -> one approval."""
import json
from fastapi import APIRouter,HTTPException
from fastapi.responses import HTMLResponse,Response
from pydantic import Field
from .db import connect,uid,now
from .knowledge import row,revision,packed
from .research_models import Strict
from .research import version_current
from .corpus import analysis_current,digest,fingerprint,provider
from .teaching import knowledge
from .review_unit_models import UnitBody,MappingBatch,CardSet

router=APIRouter(prefix='/api/review-units',tags=['revision unit composition'])
ROLES={'core':'核心考察','support':'辅助使用','optional':'可选解法','none':'未匹配','uncertain':'依据待判断'}

def available(c):
    sources=[];seen=set();identities=set();skipped=0
    for v in c.execute('SELECT * FROM research_analysis_versions ORDER BY created_at DESC,rowid DESC'):
        f=json.loads(v['snapshot']);qid=f['input'].get('question_version_id')
        if qid in seen or not analysis_current(c,v['id']):continue
        seen.add(qid);identity=fingerprint(f['question'])
        if identity in identities:skipped+=1;continue
        identities.add(identity);sources.append({'id':v['id'],'hash':digest(f),'title':f['question']['title']})
    return sources,skipped

def unit_current(c,meta):
    try:
        if not version_current(c,row(c,'knowledge_versions',meta['knowledge_version_id'])):return False
        return all(analysis_current(c,s['id']) and digest(json.loads(row(c,'research_analysis_versions',s['id'])['snapshot']))==s['hash'] for s in meta['sources'])
    except HTTPException:return False

def study(c,key):
    f=json.loads(row(c,'research_analysis_versions',key)['snapshot'])
    return {'id':key,'question':f['question'],'analysis':f['analysis'],'teacher_review':f.get('teacher_review'),'checks':f.get('checks',[])}

def texts(node):
    if isinstance(node,str):return [node]
    if isinstance(node,list):return [s for v in node for s in texts(v)]
    if isinstance(node,dict):return [s for v in node.values() for s in texts(v)]
    return []

def evidence(value,studies):
    s=studies.get(value['analysis_id'])
    if not s:raise ValueError('证据引用了本次题库范围以外的研究终稿')
    path=next((a for a in s['analysis']['approaches'] if a['id']==value['approach_id']),None)
    if not path or value['step_index']>=len(path['steps']):raise ValueError('证据引用的解法或步骤不存在')
    if not any(value['quote'] in path['steps'][value['step_index']][key] for key in ['action','reason']):raise ValueError('证据必须逐字引用所指解题步骤中的文字')

def validate_mappings(value,know,studies):
    parsed=MappingBatch.model_validate(value).model_dump()['mappings'];allowed={k['ref'] for k in know['items']}
    if len({m['analysis_id'] for m in parsed})!=len(parsed) or {m['analysis_id'] for m in parsed}!=set(studies):raise ValueError('必须逐题保留本批研究的匹配结果，不得重复或漏题')
    for m in parsed:
        if m['relevance'] in {'none','uncertain'} and m['links']:raise ValueError('未匹配或依据待判断的题目不应强加知识关联')
        if m['relevance'] in {'core','support','optional'} and not m['links']:raise ValueError('匹配题必须给出有证据的知识关联')
        for link in m['links']:
            if link['analysis_id']!=m['analysis_id']:raise ValueError('知识关联与所属研究不一致')
            if link['knowledge_ref'] not in allowed:raise ValueError('知识关联引用了知识终稿之外的条目')
            evidence(link,studies)
    return parsed

def validate_cards(value,know,studies):
    parsed=CardSet.model_validate(value).model_dump();refs={k['ref'] for k in know['items']}
    for card in parsed['cards']:
        if not set(card['knowledge_refs'])<=refs:raise ValueError('思路卡引用了终稿之外的知识')
        for e in card['evidence']:evidence(e,studies)
        identities={fingerprint(studies[e['analysis_id']]['question']) for e in card['evidence']}
        if len(identities)<2:raise ValueError('跨题思路卡至少需要两道不同题的证据，不得用同题多解冒充跨题')
    return parsed

def checked(c,meta,body):
    value=UnitBody.model_validate(body).model_dump();know=knowledge(c,meta['knowledge_version_id']);studies={s['id']:study(c,s['id']) for s in meta['sources']}
    validate_mappings({'mappings':value['mappings']},know,studies)
    selected=value['selected_analysis_ids'];eligible={m['analysis_id'] for m in value['mappings'] if m['relevance'] in {'core','support','optional'}}
    if len(set(selected))!=len(selected) or not set(selected)<=eligible:raise ValueError('代表题必须来自有依据的匹配结果，且不得重复')
    if len(selected)>meta['representative_limit']:raise ValueError('代表题数量超过本次设定')
    chosen={key:studies[key] for key in selected}
    validate_cards({'cards':value['cards'],'summary':value['summary']},know,chosen)
    refs={k['ref'] for k in know['items']}
    edges=set()
    for edge in value['knowledge_connections']:
        if edge['source_ref'] not in refs or edge['target_ref'] not in refs or edge['source_ref']==edge['target_ref']:raise ValueError('知识连接的两端须是本单元中不同的知识条目')
        key=(edge['source_ref'],edge['target_ref'],edge['relation_type'])
        if key in edges:raise ValueError('知识连接重复')
        edges.add(key)
    phases=[t['phase'] for t in value['training']]
    if selected and not {'basic','thinking','solve'} <= set(phases):raise ValueError('训练须覆盖基础唤起、思路训练和独立解题')
    if selected and not phases.index('basic')<phases.index('thinking')<phases.index('solve'):raise ValueError('训练顺序须先基础唤起，再思路训练，最后独立解题')
    for t in value['training']:
        if not set(t['source_analysis_ids'])<=set(selected) or not set(t['knowledge_refs'])<=refs:raise ValueError('训练须引用本单元代表题与知识终稿')
    from .student_presentation import current_presentation,validate
    if current_presentation(value,know):validate(value['presentation'],value,know)
    return value

def review_advice(body,checks,know):
    advice=list(checks)
    from .student_presentation import current_presentation
    presentation=current_presentation(body,know)
    if body.get('presentation') and not presentation:advice.append({'section':'presentation','message':'学生表达与当前正文不一致，或仍含内部标记／教研说明；预览已回退到当前正文及通用学习提示。','guidance':'点击优化学生表达与版式，或编辑学生表达后保存。教师参考中的编排说明不会进入学生导读；旧终稿保持不变。'})
    if not presentation or not presentation.get('summary'):advice.append({'section':'summary','message':'尚无本单元的学生思路导读。教研归纳只保留给教师，学生版使用通用思考提示。','guidance':'可点击优化学生表达与版式生成，或在学生表达中补写summary。不要把研究编号、分类标签或审核待办写进学生讲解。'})
    if presentation:
        advice.extend({'section':'presentation','message':note,'guidance':'核对学生讲解与原知识是否一致，可直接编辑后随单元整体审定。'} for note in presentation['review_notes'])
    if not body['selected_analysis_ids']:advice.append({'section':'training','message':'当前题库没有充分匹配的代表题，尚未形成思路与解题训练。','guidance':'本稿保留基础知识，不能声称已完成训练闭环。可补充相关研究终稿后重新编制，也可由教师决定本次仅作基础读物。'})
    used={l['knowledge_ref'] for m in body['mappings'] for l in m['links']}
    for k in know['items']:
        if k['ref'] not in used:advice.append({'section':'mappings','message':k['title']+'：本次题库暂无应用证据。','guidance':'保留基础复习；可补充代表题。未匹配不表示该知识不重要或可以删去。'})
    for m in body['mappings']:
        for gap in m['gaps']:advice.append({'section':'mappings','message':gap,'guidance':'对照所指原题与研究步骤，检查关联解释和成立条件；可编辑关联或由教师认可。未定位证据的题目保留待判断，不影响其他题目生成。' if gap.startswith(('引文定位核对','证据待定位')) else '核对该题的知识边界，可修改映射或排除该题；不自动增改知识终稿。'})
        if m['relevance']=='uncertain':advice.append({'section':'mappings','message':m['reason'],'guidance':'在知识映射中核对具体证据；可保留为未纳入或修改关联，教师整体确认即可。'})
    for card in body['cards']:
        for doubt in card['doubts']:advice.append({'section':'cards','message':doubt,'guidance':'核对归纳边界，修改思路卡或由教师判断是否适用；不必再次调用AI。'})
    return advice

def detail(c,r):
    meta=json.loads(r['input_json']).get('review_unit_task')
    if not meta:raise HTTPException(404,'不是复习单元任务')
    unit=row(c,'review_units',r['id']);body=json.loads(unit['payload']) if unit['payload'] else None;know=knowledge(c,meta['knowledge_version_id'])
    versions=[dict(v) for v in c.execute('SELECT id,revision,created_at FROM review_unit_versions WHERE unit_id=? ORDER BY created_at DESC,rowid DESC',(r['id'],))]
    selected=body['selected_analysis_ids'] if body else []
    checks=json.loads(unit['checks'])
    presentation_task=c.execute('SELECT k.id,k.status,k.revision,k.error,t.revision AS base_revision FROM review_unit_presentation_tasks t JOIN knowledge_runs k ON k.id=t.run_id WHERE t.unit_id=? ORDER BY k.created_at DESC,k.rowid DESC LIMIT 1',(r['id'],)).fetchone()
    presentation_task=dict(presentation_task) if presentation_task else None
    if presentation_task:presentation_task['calls']=[dict(x) for x in c.execute('SELECT step,status,error,reserved_tokens FROM knowledge_calls WHERE run_id=? ORDER BY rowid',(presentation_task['id'],))]
    current_final=next((v for v in versions if v['revision']==unit['revision']),None)
    teacher_review=json.loads(row(c,'review_unit_versions',current_final['id'])['snapshot']).get('teacher_review') if current_final else None
    return {'id':r['id'],'status':r['status'],'stage':r['stage'],'run_revision':r['revision'],'revision':unit['revision'],'error':r['error'],'stale':not unit_current(c,meta),'title':json.loads(r['input_json'])['title'],'body':body,'checks':checks,'advice':review_advice(body,checks,know) if body else [],'knowledge':know,'studies':[study(c,key) for key in selected],'sources':meta['sources'],'representative_limit':meta['representative_limit'],'skipped_duplicates':meta.get('skipped_duplicates',0),'read_only':any(v['revision']==unit['revision'] for v in versions),'versions':versions,'presentation_task':presentation_task,'parent_version':unit['parent_version'],'teacher_review':teacher_review,'calls':[dict(v) for v in c.execute('SELECT step,status,error,reserved_tokens FROM knowledge_calls WHERE run_id=? ORDER BY rowid',(r['id'],))]}

@router.get('/catalog')
def catalog():
    from .research import knowledge_versions
    with connect() as c:sources,duplicates=available(c)
    return {'knowledge_versions':knowledge_versions(),'studies':sources,'skipped_duplicates':duplicates}

class Start(Strict):
    knowledge_version_id:str
    analysis_version_ids:list[str]|None=Field(default=None,max_length=3000)
    representative_limit:int=Field(default=4,ge=2,le=8)
    instruction:str=Field(default='',max_length=3000)
    request_key:str=Field(min_length=8,max_length=100)
@router.post('/runs',status_code=201)
def start(body:Start):
    config=provider();signature=digest(body.model_dump(exclude={'request_key'}))
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');old=c.execute('SELECT * FROM review_unit_requests WHERE request_key=?',(body.request_key,)).fetchone()
        if old:
            if old['signature']!=signature:raise HTTPException(409,'同一请求编号对应不同材料')
            return detail(c,row(c,'knowledge_runs',old['unit_id']))
        if not version_current(c,row(c,'knowledge_versions',body.knowledge_version_id)):raise HTTPException(409,'请选择当前有效的知识终稿')
        know=knowledge(c,body.knowledge_version_id)
        if not know['items'] or len(packed(know))>120000:raise HTTPException(422,'知识终稿为空或正文过长，请按小节整理后编制')
        sources,duplicates=available(c)
        if body.analysis_version_ids is not None:
            wanted=set(body.analysis_version_ids)
            sources=[s for s in sources if s['id'] in wanted]
            if wanted!={s['id'] for s in sources}:raise HTTPException(409,'所选研究包含过期版本或重复题，请刷新题库范围')
        if not sources:raise HTTPException(422,'尚无当前有效的研究终稿，请先完成至少一道题的研究审核')
        meta={'knowledge_version_id':body.knowledge_version_id,'sources':sources,'representative_limit':body.representative_limit,'instruction':body.instruction,'skipped_duplicates':duplicates}
        from .review_unit_worker import batches,compact
        try:groups=batches([compact(study(c,s['id'])) for s in sources])
        except ValueError as exc:raise HTTPException(422,str(exc)) from None
        # Reserve the full automatic pipeline explicitly, including two attempts per step.
        from .student_presentation import plan as presentation_plan
        reading_plan=presentation_plan(know)
        calls=len(groups)+3+len(reading_plan);budget=len(groups)*7000+18000+sum(tokens for _,tokens in reading_plan)
        config=config.model_copy(update={'max_calls':max(config.max_calls,calls*2),'output_token_budget':max(config.output_token_budget,budget*2)})
        key=uid();unit=uid();snapshot={'title':know['title']+' · 复习单元','chapters':[],'review_unit_task':meta}
        from .model_provider import public_provider
        c.execute('INSERT INTO knowledge_units(id,title,chapters,target,notes,origin,created_at) VALUES(?,?,?,?,?,?,?)',(unit,snapshot['title'],'[]','复习单元编制','',packed({'internal_review_unit':True}),now()))
        c.execute("INSERT INTO knowledge_runs(id,unit_id,input_revision,input_json,model_json,status,stage,created_at,updated_at) VALUES(?,?,?,?,?,'queued','unit:mapping',?,?)",(key,unit,1,packed(snapshot),packed(public_provider(config)),now(),now()))
        c.execute('INSERT INTO review_units(id,sources) VALUES(?,?)',(key,packed(meta)))
        c.execute('INSERT INTO review_unit_requests VALUES(?,?,?)',(body.request_key,key,signature))
        return detail(c,row(c,'knowledge_runs',key))
@router.get('/runs')
def runs():
    with connect() as c:
        return [{'id':r['id'],'title':(json.loads(r['payload'])['title'] if r['payload'] else json.loads(r['input_json'])['title']),'status':r['status'],'created_at':r['created_at']} for r in c.execute('SELECT k.*,u.payload FROM review_units u JOIN knowledge_runs k ON k.id=u.id ORDER BY k.created_at DESC,k.rowid DESC')]
@router.get('/runs/{key}')
def get_run(key:str):
    with connect() as c:return detail(c,row(c,'knowledge_runs',key))
class Rev(Strict):revision:int;run_revision:int
class Save(Rev):body:UnitBody
@router.put('/runs/{key}')
def save(key:str,body:Save):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');r=row(c,'knowledge_runs',key);d=detail(c,r);revision(r,body.run_revision);revision(d,body.revision)
        if d['stale'] or d['read_only'] or r['status']!='completed':raise HTTPException(409,'依据已变化、任务未完成或为只读终稿，请先继续修订')
        candidate=body.body.model_dump()
        if candidate.get('presentation') and candidate['presentation']!=(d['body'] or {}).get('presentation'):
            from .student_presentation import source_hash
            candidate['presentation']['source_hash']=source_hash(candidate,d['knowledge'])
            candidate['presentation']['agent']=((d['body'] or {}).get('presentation') or {}).get('agent')
        try:value=checked(c,json.loads(r['input_json'])['review_unit_task'],candidate)
        except ValueError as exc:raise HTTPException(422,str(exc)) from None
        c.execute('INSERT INTO review_unit_history VALUES(?,?,?,?,?)',(uid(),key,d['revision'],packed(d['body']),now()))
        c.execute('UPDATE review_units SET payload=?,revision=revision+1 WHERE id=?',(packed(value),key))
        return detail(c,r)
class Final(Rev):confirmed:bool;note:str=Field(default='',max_length=6000)
@router.post('/runs/{key}/finalize',status_code=201)
def finalize(key:str,body:Final):
    if not body.confirmed:raise HTTPException(422,'请确认已审核整份复习单元')
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');r=row(c,'knowledge_runs',key);d=detail(c,r);revision(r,body.run_revision);revision(d,body.revision)
        if d['stale'] or r['status']!='completed' or not d['body']:raise HTTPException(409,'依据已变化或草案尚未完成')
        old=c.execute('SELECT id FROM review_unit_versions WHERE unit_id=? AND revision=?',(key,d['revision'])).fetchone()
        if old:return {'id':old['id']}
        try:value=checked(c,json.loads(r['input_json'])['review_unit_task'],d['body'])
        except ValueError as exc:raise HTTPException(422,str(exc)) from None
        snapshot={'format':'mathlet-review-unit','schema_version':1,'body':value,'knowledge':d['knowledge'],'studies':d['studies'],'sources':d['sources'],'checks':d['advice'],'model':json.loads(r['model_json']),'parent_version':d['parent_version'],'teacher_review':{'confirmed':True,'note':body.note,'revision':d['revision'],'created_at':now()},'created_at':now()}
        from .review_unit_reader import render_reader
        try:html=render_reader(snapshot)
        except ValueError as exc:raise HTTPException(422,'公式排版失败，请修正所示语法后重试：'+str(exc)) from None
        key_version=uid();c.execute('INSERT INTO review_unit_versions VALUES(?,?,?,?,?,?)',(key_version,key,d['revision'],packed(snapshot),html,now()))
        return {'id':key_version}
@router.post('/runs/{key}/retry')
def retry(key:str,body:Rev):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');r=row(c,'knowledge_runs',key);d=detail(c,r);revision(r,body.run_revision);revision(d,body.revision)
        if d['stale'] or r['status'] not in {'failed','interrupted'}:raise HTTPException(409,'只能重试依据有效的失败或中断任务')
        if d['body']:raise HTTPException(409,'已有教师草稿，不自动覆盖')
        config=retry_budget(c,r,d['knowledge'],json.loads(r['input_json'])['review_unit_task'])
        c.execute("UPDATE knowledge_runs SET model_json=?,status='queued',error='',revision=revision+1,updated_at=? WHERE id=?",(packed(config),now(),key))
        return detail(c,row(c,'knowledge_runs',key))
@router.post('/versions/{key}/revise',status_code=201)
def revise(key:str):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');v=row(c,'review_unit_versions',key);old=row(c,'knowledge_runs',v['unit_id']);meta=json.loads(old['input_json'])['review_unit_task']
        if not unit_current(c,meta):raise HTTPException(409,'来源已变化，请用当前知识与题库重新编制；旧终稿保留')
        f=json.loads(v['snapshot']);new=uid();unit=uid()
        c.execute('INSERT INTO knowledge_units(id,title,chapters,target,notes,origin,created_at) VALUES(?,?,?,?,?,?,?)',(unit,f['body']['title'],'[]','复习单元编制','',packed({'internal_review_unit':True}),now()))
        c.execute("INSERT INTO knowledge_runs(id,unit_id,input_revision,input_json,model_json,status,stage,created_at,updated_at) VALUES(?,?,?,?,?,'completed','completed',?,?)",(new,unit,1,old['input_json'],old['model_json'],now(),now()))
        c.execute('INSERT INTO review_units(id,sources,payload,original_payload,checks,parent_version) VALUES(?,?,?,?,?,?)',(new,packed(meta),packed(f['body']),packed(f['body']),packed(json.loads(row(c,'review_units',v['unit_id'])['checks'])),key))
        return detail(c,row(c,'knowledge_runs',new))
@router.get('/runs/{key}/preview')
def preview(key:str):
    from .review_unit_reader import render_reader
    with connect() as c:d=detail(c,row(c,'knowledge_runs',key))
    if not d['body']:raise HTTPException(409,'草案尚未完成')
    try:return HTMLResponse(render_reader(d|{'teacher_review':{'confirmed':False}}))
    except ValueError as exc:raise HTTPException(422,'公式排版失败：'+str(exc)) from None
@router.get('/versions/{key}/reader')
def reader(key:str):
    with connect() as c:v=row(c,'review_unit_versions',key)
    return HTMLResponse(v['rendered_html'])
@router.get('/versions/{key}/download')
def download(key:str):
    with connect() as c:v=row(c,'review_unit_versions',key)
    return HTMLResponse(v['rendered_html'],headers={'Content-Disposition':f'attachment; filename="mathlet-review-unit-{key}.html"'})
@router.get('/versions/{key}/json')
def export_json(key:str):
    with connect() as c:v=row(c,'review_unit_versions',key)
    return Response(v['snapshot'],media_type='application/json',headers={'Content-Disposition':f'attachment; filename="mathlet-review-unit-{key}.json"'})

@router.get('/runs/{key}/studies/{analysis_id}')
def get_study(key:str,analysis_id:str):
    with connect() as c:
        r=row(c,'review_units',key)
        if analysis_id not in {s['id'] for s in json.loads(r['sources'])['sources']}:raise HTTPException(404,'此研究不在本次范围中')
        return study(c,analysis_id)

class Discuss(Rev):
    body:UnitBody
    section:str=Field(min_length=1,max_length=60)
    instruction:str=Field(min_length=1,max_length=4000)
    request_key:str=Field(min_length=8,max_length=100)
@router.get('/runs/{key}/discussions')
def discussions(key:str):
    with connect() as c:
        row(c,'review_units',key)
        return [dict(r) for r in c.execute('SELECT d.*,k.status,k.error FROM review_unit_discussions d JOIN knowledge_runs k ON k.id=d.id WHERE d.unit_id=? ORDER BY d.created_at DESC,d.rowid DESC',(key,))]
@router.post('/runs/{key}/discussions',status_code=201)
def discuss(key:str,body:Discuss):
    config=provider()
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');r=row(c,'knowledge_runs',key);d=detail(c,r);revision(r,body.run_revision);revision(d,body.revision)
        if d['stale'] or r['status']!='completed' or not d['body']:raise HTTPException(409,'请等待草案完成并使用有效来源讨论')
        if body.section not in {'introduction','goals','basics','mappings','cards','training','solutions','summary','knowledge_connections','presentation'}:raise HTTPException(422,'未知栏目')
        # Discussion may contain unsaved work, but can never mutate the saved manuscript.
        from .review_unit_worker import compact
        payload={'knowledge':d['knowledge'],'reviewed_studies':[compact(s) for s in d['studies']],'section':body.section,'current_section':(body.body.presentation.model_dump().get(body.section) if body.body.presentation and body.section in {'introduction','goals','summary'} else body.body.model_dump().get(body.section)),'instruction':body.instruction,'based_revision':body.revision,'uses_unsaved_body':body.body.model_dump()!=d['body']}
        if len(packed(payload))>220000:raise HTTPException(422,'当前栏目与依据过长，请缩小单元的代表题范围后讨论；未发送模型')
        signature=digest({'unit':key,'payload':payload})
        old=c.execute('SELECT * FROM review_unit_discussions WHERE request_key=?',(body.request_key,)).fetchone()
        if old:
            if old['signature']!=signature:raise HTTPException(409,'讨论请求编号对应不同内容')
            return {'id':old['id']}
        if c.execute("SELECT 1 FROM review_unit_discussions d JOIN knowledge_runs k ON k.id=d.id WHERE d.unit_id=? AND k.status IN ('queued','running')",(key,)).fetchone():raise HTTPException(409,'当前讨论尚未完成，请稍候')
        from .corpus import queue
        task={'review_unit_discussion':{'sources':json.loads(r['input_json'])['review_unit_task'],'payload':payload},'title':'复习单元AI讨论','chapters':[]}
        child=queue(c,'复习单元AI讨论',task,config,2500)
        c.execute('INSERT INTO review_unit_discussions VALUES(?,?,?,?,?,?,?,?,?,?)',(child['id'],key,body.request_key,signature,body.section,body.instruction,body.revision,'',packed(payload),now()))
        return {'id':child['id']}


def retry_budget(c,run,know,meta=None):
    from .student_presentation import plan
    steps=plan(know)
    if meta is not None:
        from .review_unit_worker import batches,compact
        groups=batches([compact(study(c,s['id'])) for s in meta['sources']])
        steps=[(f'unit:mapping:{i+1}',7000) for i in range(len(groups))]+[('unit:cards',6500),('unit:training',8500),('unit:review',3000)]+steps
    successful={x['step'] for x in c.execute("SELECT step FROM knowledge_calls WHERE run_id=? AND status IN ('succeeded','revalidated')",(run['id'],))}
    count,reserved=c.execute('SELECT count(*),coalesce(sum(reserved_tokens),0) FROM knowledge_calls WHERE run_id=?',(run['id'],)).fetchone()
    remaining=[tokens for step,tokens in steps if step not in successful];config=json.loads(run['model_json'])
    config.update(max_calls=max(config['max_calls'],count+len(remaining)),output_token_budget=max(config['output_token_budget'],reserved+sum(remaining)))
    return config

class Present(Rev):request_key:str=Field(min_length=8,max_length=100)
@router.post('/runs/{key}/presentation',status_code=201)
def start_presentation(key:str,body:Present):
    from .student_presentation import plan
    config=provider()
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');r=row(c,'knowledge_runs',key);d=detail(c,r)
        old=c.execute('SELECT * FROM review_unit_presentation_tasks WHERE request_key=?',(body.request_key,)).fetchone()
        if old:
            if old['unit_id']!=key or old['revision']!=body.revision:raise HTTPException(409,'此请求编号对应另一个稿件修订')
            return {'id':old['run_id']}
        revision(r,body.run_revision);revision(d,body.revision)
        if d['stale'] or d['read_only'] or r['status']!='completed' or not d['body']:raise HTTPException(409,'请基于有效的可编辑工作稿生成；已定稿时先继续修订')
        if d['presentation_task'] and d['presentation_task']['status'] in {'queued','running'}:raise HTTPException(409,'学生表达正在生成，请稍候')
        steps=plan(d['knowledge']);config=config.model_copy(update={'max_calls':max(config.max_calls,len(steps)*2),'output_token_budget':max(config.output_token_budget,sum(t for _,t in steps)*2)})
        from .corpus import queue
        meta={'parent_id':key,'parent_revision':body.revision,'sources':json.loads(r['input_json'])['review_unit_task'],'body':d['body'],'knowledge':d['knowledge']}
        child=queue(c,'学生阅读表达Agent',{'title':'学生阅读表达Agent','chapters':[],'presentation_task':meta},config,sum(t for _,t in steps)*2)
        c.execute('INSERT INTO review_unit_presentation_tasks VALUES(?,?,?,?)',(child['id'],key,body.revision,body.request_key))
        return {'id':child['id']}
class PresentationRetry(Strict):revision:int
@router.post('/presentation-tasks/{key}/retry')
def retry_presentation(key:str,body:PresentationRetry):
    from .student_presentation import task_current
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');r=row(c,'knowledge_runs',key);revision(r,body.revision);meta=json.loads(r['input_json']).get('presentation_task')
        if not meta or r['status'] not in {'failed','interrupted'} or not task_current(c,meta):raise HTTPException(409,'正文或依据已变化，或任务不可重试；请基于当前工作稿重新生成学生表达')
        config=retry_budget(c,r,meta['knowledge'])
        c.execute("UPDATE knowledge_runs SET model_json=?,status='queued',error='',revision=revision+1,updated_at=? WHERE id=?",(packed(config),now(),key))
        return {'id':key}
