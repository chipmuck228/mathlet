"""Human-confirmed questions, immutable evidence and model proposal review."""
import base64
import hashlib
import json
import re
from pathlib import Path
from fastapi import APIRouter,HTTPException
from fastapi.responses import Response
from pydantic import Field
from .db import connect,now,uid,data_dir
from .knowledge import row,revision,packed
from .research_models import Strict,QuestionBody,Relation,Analysis
from .model_provider import load_provider,public_provider
from .formulas import parts_from_text,render_latex

router=APIRouter(prefix='/api/research',tags=['question research'])


def version_current(c,version):
    from .knowledge import current
    run=row(c,'knowledge_runs',version['run_id'])
    return current(c,run) and run['revision']==version['run_revision']


def context_current(c,context):
    return all(version_current(c,row(c,'knowledge_versions',key)) for key in json.loads(context['version_ids']))


def question_current(c,question):
    payload=json.loads(question['payload'])
    for source in payload['sources']:
        current=c.execute('SELECT text,verified FROM blocks WHERE id=?',(source['id'],)).fetchone()
        if not current or hashlib.sha256(current['text'].encode()).hexdigest()!=source['hash']:return False
        if source['verified'] and not current['verified']:return False
        if payload['answer_status']=='verified' and source['id'] in payload['answer_block_ids'] and not current['verified']:return False
    for asset in payload['assets']:
        path=data_dir()/'documents'/asset['document_id']/'assets'/asset['name']
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=asset['hash']:return False
    return True


def sources_current(c,meta):
    context=row(c,'research_contexts',meta['context_id'])
    if context['revision']!=meta['context_revision'] or not context_current(c,context):return False
    if meta.get('question_version_id'):
        version=row(c,'research_question_versions',meta['question_version_id']);question=row(c,'research_questions',version['question_id'])
        if question['revision']!=version['revision'] or question['confirmed_revision']!=version['revision'] or not question_current(c,question):return False
    if meta.get('graph_version_id'):
        graph=row(c,'research_graph_versions',meta['graph_version_id'])
        if graph['context_id']!=context['id'] or graph['context_revision']!=context['revision']:return False
    return True


def question_json(c,question):
    result=dict(question);result['payload']=json.loads(result['payload']);result['stale']=not question_current(c,question)
    result['confirmed']=question['confirmed_revision']==question['revision'] and not result['stale']
    version=c.execute('SELECT id FROM research_question_versions WHERE question_id=? AND revision=?',(question['id'],question['revision'])).fetchone()
    result['version_id']=version['id'] if version else None
    return result


def context_json(c,context):
    result=dict(context);result['snapshot']=json.loads(result['snapshot']);result['version_ids']=json.loads(result['version_ids']);result['stale']=not context_current(c,context)
    return result


def validate_text(text):
    if '【未转换公式' in text:raise HTTPException(422,'题目仍含未转换公式，请核对后修正')
    try:
        parts_from_text(text,strict=True)
        for match in re.finditer(r'\\\[([\s\S]*?)\\\]|\$\$([\s\S]*?)\$\$|(?<![\\$])\$(?!\$)([^\n$]+?)(?<!\\)\$(?!\$)',text):
            render_latex(next(x for x in match.groups() if x is not None))
    except ValueError as exc:raise HTTPException(422,str(exc)) from None


def capture_question(c,body):
    ids=body.question_block_ids+body.answer_block_ids
    if len(set(body.question_block_ids))!=len(body.question_block_ids) or len(set(body.answer_block_ids))!=len(body.answer_block_ids):raise HTTPException(422,'同一角色的来源块不可重复')
    sources=[];assets=[];seen=set();available_assets=set()
    for key in dict.fromkeys(ids):
        block=row(c,'blocks',key);document=row(c,'documents',block['document_id'])
        if document['status']!='ready':raise HTTPException(409,'原始资料尚未就绪')
        sources.append({'id':key,'document_id':document['id'],'document_name':document['name'],'category':document['category'],'locator':block['locator'],'text':block['text'],'revision':block['revision'],'verified':bool(block['verified']),'hash':hashlib.sha256(block['text'].encode()).hexdigest()})
        if key in body.question_block_ids:
            for name in json.loads(block['assets']):
                available_assets.add(document['id']+'/'+name)
                if body.selected_assets is not None and document['id']+'/'+name not in body.selected_assets:continue
                if Path(name).name!=name:raise HTTPException(422,'配图路径无效')
                if (document['id'],name) in seen:continue
                path=data_dir()/'documents'/document['id']/'assets'/name
                if not path.is_file():raise HTTPException(422,'原题配图缺失，请恢复后核对')
                content=path.read_bytes();seen.add((document['id'],name))
                assets.append({'document_id':document['id'],'name':name,'url':f"/api/documents/{document['id']}/assets/{name}",'hash':hashlib.sha256(content).hexdigest()})
    byid={x['id']:x for x in sources}
    for r in body.source_ranges:
        if r.block_id not in byid or r.end<=r.start or r.end>len(byid[r.block_id]['text']) or r.block_id not in (body.question_block_ids if r.role=='question' else body.answer_block_ids):raise HTTPException(422,'题目原文范围无效')
    if body.selected_assets is not None and not set(body.selected_assets)<=available_assets:raise HTTPException(422,'配图选择不属于本题来源')
    if body.answer_status=='verified':
        if not body.reference_answer.strip():raise HTTPException(422,'已核对参考答案不能为空')
        # A teacher may transcribe an answer; unverified reference blocks must not be claimed verified.
        if any(not x['verified'] for x in sources if x['id'] in body.answer_block_ids):raise HTTPException(422,'参考答案来源块尚未核对，请先核对或保留为未核对')
    if body.answer_status=='absent' and (body.answer_block_ids or body.reference_answer.strip()):raise HTTPException(422,'已有答案内容时请选择未核对或已核对状态')
    basis='verified_source_blocks' if body.answer_status=='verified' and body.answer_block_ids else 'teacher_transcription' if body.answer_status=='verified' else 'unreviewed' if body.answer_status=='unchecked' else 'unavailable'
    return body.model_dump()|{'sources':sources,'assets':assets,'reference_answer_basis':basis}


@router.get('/knowledge-versions')
def knowledge_versions():
    with connect() as c:
        result=[]
        for value in c.execute('SELECT * FROM knowledge_versions ORDER BY created_at DESC'):
            snapshot=json.loads(value['snapshot'])
            result.append({'id':value['id'],'title':snapshot['unit']['title'],'run_revision':value['run_revision'],'count':len([x for x in snapshot['items'] if x['scope']!='excluded']),'stale':not version_current(c,value),'created_at':value['created_at']})
        return result

class ContextCreate(Strict):
    title:str=Field(min_length=1,max_length=160)
    version_ids:list[str]=Field(min_length=1,max_length=5)
@router.post('/contexts',status_code=201)
def create_context(body:ContextCreate):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        if len(set(body.version_ids))!=len(body.version_ids):raise HTTPException(422,'知识版本不可重复')
        items=[];inherited=[]
        for key in body.version_ids:
            version=row(c,'knowledge_versions',key)
            if not version_current(c,version):raise HTTPException(409,'所选知识版本已过期，请重新核对并固定当前版本')
            snapshot=json.loads(version['snapshot'])
            for item in snapshot['items']:
                if item['scope']=='excluded':continue
                items.append({'ref':key+':'+item['knowledge_id'],'version_id':key,'knowledge_id':item['knowledge_id'],'title':item['body']['name'],'unit_title':snapshot['unit']['title'],'scope':item['scope'],'body':item['body']})
            for edge in snapshot.get('relations',[]):
                inherited.append({'source_ref':key+':'+edge['body']['source_id'],'target_ref':key+':'+edge['body']['target_id'],**{k:v for k,v in edge['body'].items() if k not in {'source_id','target_id'}},'basis':'knowledge_version_teacher_review'})
        if not items or len(items)>80 or len(packed(items))>120000:raise HTTPException(422,'研究知识集需包含1—80项知识且正文不超过120000字符，请缩小版本选择')
        snapshot={'items':items,'inherited_relations':inherited,'version_ids':body.version_ids,'official_coverage_verified':False}
        key=uid();c.execute('INSERT INTO research_contexts(id,title,version_ids,snapshot,created_at) VALUES(?,?,?,?,?)',(key,body.title,packed(body.version_ids),packed(snapshot),now()))
        return context_json(c,row(c,'research_contexts',key))
@router.get('/contexts')
def contexts():
    with connect() as c:return [context_json(c,x) for x in c.execute('SELECT * FROM research_contexts ORDER BY created_at DESC')]

@router.post('/questions',status_code=201)
def create_question(body:QuestionBody):
    with connect() as c:
        key=uid();payload=capture_question(c,body)
        c.execute('INSERT INTO research_questions(id,payload,created_at) VALUES(?,?,?)',(key,packed(payload),now()))
        return question_json(c,row(c,'research_questions',key))
class QuestionEdit(QuestionBody):revision:int
@router.put('/questions/{question_id}')
def edit_question(question_id:str,body:QuestionEdit):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');old=row(c,'research_questions',question_id);revision(old,body.revision)
        payload=capture_question(c,QuestionBody.model_validate(body.model_dump(exclude={'revision'})))
        c.execute('INSERT INTO research_question_history VALUES(?,?,?,?,?)',(uid(),question_id,old['revision'],packed(old),now()))
        c.execute("UPDATE research_questions SET payload=?,revision=revision+1,confirmed_revision=NULL,reviewer='',review_note='' WHERE id=?",(packed(payload),question_id))
        return question_json(c,row(c,'research_questions',question_id))
@router.get('/questions')
def questions():
    with connect() as c:return [question_json(c,x) for x in c.execute('SELECT * FROM research_questions ORDER BY created_at DESC')]
class Confirm(Strict):
    revision:int
    reviewer:str=Field(min_length=1,max_length=80)
    note:str=Field(min_length=1,max_length=3000)
    confirmed:bool=False
@router.post('/questions/{question_id}/confirm')
def confirm_question(question_id:str,body:Confirm):
    if not body.confirmed:raise HTTPException(422,'请明确确认完整题干、条件、小问、配图与答案状态')
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');question=row(c,'research_questions',question_id);revision(question,body.revision)
        if not question_current(c,question):raise HTTPException(409,'来源已修改，请重新保存并核对题目')
        if question['confirmed_revision']==question['revision'] and c.execute('SELECT 1 FROM research_question_versions WHERE question_id=? AND revision=?',(question_id,question['revision'])).fetchone():return question_json(c,question)
        payload=json.loads(question['payload']);validate_text(payload['statement']);validate_text(payload['diagram_description'])
        if payload['answer_status']=='verified':validate_text(payload['reference_answer'])
        if payload['figure_status']=='pending':raise HTTPException(422,'配图尚待核对，不能确认完整题目')
        if payload['assets'] and payload['figure_status']=='not_needed' and not payload['diagram_description'].strip():raise HTTPException(422,'题目附有图片，请描述必要图形条件，或说明图片为何不影响本题')
        if payload['figure_status']=='described' and not payload['diagram_description'].strip():raise HTTPException(422,'请填写图形条件的文字描述')
        frozen=json.loads(packed(payload));total=0
        for asset in frozen['assets']:
            content=(data_dir()/'documents'/asset['document_id']/'assets'/asset['name']).read_bytes();total+=len(content)
            if total>8*1024*1024:raise HTTPException(422,'题目配图合计超过8MB，请先整理资料')
            asset['data_url']='data:image/png;base64,'+base64.b64encode(content).decode()
        c.execute('UPDATE research_questions SET confirmed_revision=revision,reviewer=?,review_note=? WHERE id=?',(body.reviewer,body.note,question_id))
        frozen.update(question_id=question_id,revision=question['revision'],reviewer=body.reviewer,review_note=body.note)
        c.execute('INSERT OR IGNORE INTO research_question_versions(id,question_id,revision,snapshot,created_at) VALUES(?,?,?,?,?)',(uid(),question_id,question['revision'],packed(frozen),now()))
        return question_json(c,row(c,'research_questions',question_id))
@router.get('/questions/{question_id}/history')
def question_history(question_id:str):
    with connect() as c:
        row(c,'research_questions',question_id)
        return [dict(x)|{'snapshot':json.loads(x['snapshot'])} for x in c.execute('SELECT * FROM research_question_history WHERE question_id=? ORDER BY revision DESC',(question_id,))]

class Start(Strict):
    kind:str
    context_id:str
    context_revision:int
    question_version_id:str|None=None
    graph_version_id:str|None=None
    instruction:str=Field(default='',max_length=3000)
    limit:int=Field(default=4,ge=1,le=8)
    consent:bool=False
@router.post('/runs',status_code=201)
def start(body:Start):
    if body.kind not in {'connections','analysis'}:raise HTTPException(422,'任务类型无效')
    config=load_provider()
    if not body.consent or not config.api_key or not config.model:raise HTTPException(422,'请配置模型并确认发送题目与已审核知识版本')
    reserve=6000 if body.kind=='connections' else 11000
    if config.output_token_budget<reserve:raise HTTPException(422,'本任务输出预留预算不足，请调整模型配置')
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');context=row(c,'research_contexts',body.context_id);revision(context,body.context_revision)
        meta=body.model_dump(exclude={'consent'});meta.pop('instruction');meta['instruction']=body.instruction
        if body.kind=='analysis' and not body.question_version_id:raise HTTPException(422,'请选择已确认的完整题目版本')
        if body.kind=='connections' and (body.question_version_id or body.graph_version_id):raise HTTPException(422,'关联生成只接收知识集')
        if not sources_current(c,meta):raise HTTPException(409,'知识、关系或题目版本已过期，请重新核对并选择')
        if body.question_version_id:
            frozen=json.loads(row(c,'research_question_versions',body.question_version_id)['snapshot'])
            if len(frozen['statement'])+len(frozen['diagram_description'])+len(frozen['reference_answer'])>24000:raise HTTPException(422,'题目文字超出研究范围，请拆分题目包')
        key=uid();unit_id=uid();snapshot={'schema_version':1,'prompt_version':'research-v1','title':context['title'],'chapters':[],'research_task':meta}
        c.execute('INSERT INTO knowledge_units(id,title,chapters,target,notes,origin,created_at) VALUES(?,?,?,?,?,?,?)',(unit_id,context['title'],'[]','单题研究','',packed({'internal_research':True}),now()))
        c.execute('INSERT INTO knowledge_runs(id,unit_id,input_revision,input_json,model_json,status,stage,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',(key,unit_id,1,packed(snapshot),packed(public_provider(config)),'queued','research',now(),now()))
        return task_json(c,row(c,'knowledge_runs',key))


def task_json(c,run):
    meta=json.loads(run['input_json'])['research_task'];result={k:run[k] for k in ['id','revision','status','stage','error','created_at']}
    result.update(task=meta,stale=not sources_current(c,meta),model=json.loads(run['model_json']))
    result['outputs']=[dict(x)|{'body':json.loads(x['body']),'original_body':json.loads(x['original_body']),'checks':json.loads(x['checks'])} for x in c.execute('SELECT * FROM research_outputs WHERE run_id=? ORDER BY rowid',(run['id'],))]
    result['calls']=[dict(x) for x in c.execute('SELECT step,status,reserved_tokens,usage,error FROM knowledge_calls WHERE run_id=? ORDER BY rowid',(run['id'],))]
    return result
@router.get('/runs')
def tasks():
    with connect() as c:return [task_json(c,dict(x)) for x in c.execute('SELECT * FROM knowledge_runs ORDER BY created_at DESC') if json.loads(x['input_json']).get('research_task')]
@router.get('/runs/{run_id}')
def task(run_id:str):
    with connect() as c:
        run=row(c,'knowledge_runs',run_id)
        if not json.loads(run['input_json']).get('research_task'):raise HTTPException(404,'研究任务不存在')
        return task_json(c,run)
class Retry(Strict):revision:int
@router.post('/runs/{run_id}/retry')
def retry(run_id:str,body:Retry):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');run=row(c,'knowledge_runs',run_id);revision(run,body.revision)
        if not json.loads(run['input_json']).get('research_task'):raise HTTPException(404,'研究任务不存在')
        if run['status'] not in {'failed','interrupted'} or not sources_current(c,json.loads(run['input_json'])['research_task']):raise HTTPException(409,'任务不可重试或依据已过期')
        c.execute("UPDATE knowledge_runs SET status='queued',error='',revision=revision+1,updated_at=? WHERE id=?",(now(),run_id))
        return task_json(c,row(c,'knowledge_runs',run_id))


def validate_references(body,kind,context):
    refs={x['ref'] for x in json.loads(context['snapshot'])['items']}
    if kind=='relation':
        if body['source_ref'] not in refs or body['target_ref'] not in refs or body['source_ref']==body['target_ref']:raise ValueError('关系引用缺失、越界或指向自身')
    else:
        used={x['ref'] for x in body['knowledge_breakdown']}
        used.update(ref for x in body['assessed_points'] for ref in x['knowledge_refs'])
        used.update(ref for a in body['approaches'] for s in a['steps'] for ref in s['knowledge_refs'])
        if not used<=refs:raise ValueError('分析引用不存在的知识版本条目')
        ids=[x['id'] for x in body['approaches']]
        if len(set(ids))!=len(ids):raise ValueError('解法编号重复')

class OutputEdit(Strict):
    revision:int
    body:dict
@router.put('/outputs/{output_id}')
def edit_output(output_id:str,body:OutputEdit):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');old=row(c,'research_outputs',output_id);revision(old,body.revision);run=row(c,'knowledge_runs',old['run_id']);meta=json.loads(run['input_json'])['research_task']
        if run['status']!='completed' or not sources_current(c,meta):raise HTTPException(409,'任务未完成或依据过期，输入未覆盖')
        try:
            from .research_editor import analysis_schema
            valid=(Relation if old['kind']=='relation' else analysis_schema(meta)).model_validate(body.body).model_dump();validate_references(valid,old['kind'],row(c,'research_contexts',old['context_id']))
        except ValueError as exc:raise HTTPException(422,str(exc)) from None
        c.execute('INSERT INTO research_output_history VALUES(?,?,?,?,?)',(uid(),output_id,old['revision'],packed(old),now()))
        c.execute("UPDATE research_outputs SET body=?,revision=revision+1,state='pending',reviewer='',note='' WHERE id=?",(packed(valid),output_id))
        c.execute('UPDATE knowledge_runs SET revision=revision+1 WHERE id=?',(run['id'],))
        if old['kind']=='relation' and old['state']=='approved':c.execute('UPDATE research_contexts SET revision=revision+1 WHERE id=?',(old['context_id'],))
        return task_json(c,row(c,'knowledge_runs',old['run_id']))

class Selection(Strict):
    id:str
    revision:int
class Review(Strict):
    run_revision:int
    items:list[Selection]=Field(min_length=1,max_length=8)
    reviewer:str=Field(min_length=1,max_length=80)
    note:str=Field(min_length=1,max_length=3000)
    confirmed:bool=False
    decision:str='approve'
@router.post('/runs/{run_id}/review')
def review(run_id:str,body:Review):
    if not body.confirmed or body.decision not in {'approve','return'}:raise HTTPException(422,'请明确确认审核决定')
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');run=row(c,'knowledge_runs',run_id);revision(run,body.run_revision);meta=json.loads(run['input_json']).get('research_task')
        if not meta:raise HTTPException(404,'研究任务不存在')
        if run['status']!='completed' or not sources_current(c,meta):raise HTTPException(409,'研究依据已过期或任务未完成')
        if len({x.id for x in body.items})!=len(body.items):raise HTTPException(422,'审核选择重复')
        selected=[]
        existing_edges={(json.loads(x['body'])['source_ref'],json.loads(x['body'])['target_ref'],json.loads(x['body'])['relation_type']):x['id'] for x in c.execute("SELECT id,body FROM research_outputs WHERE context_id=? AND kind='relation' AND state='approved'",(meta['context_id'],))}
        for item in body.items:
            value=row(c,'research_outputs',item.id);revision(value,item.revision)
            if value['run_id']!=run_id:raise HTTPException(422,'不能跨任务审核')
            decoded=json.loads(value['body'])
            if body.decision=='approve':
                if value['kind']=='relation':
                    key=(decoded['source_ref'],decoded['target_ref'],decoded['relation_type'])
                    if key in existing_edges and existing_edges[key]!=value['id']:raise HTTPException(422,'同方向同类型关系已存在，请避免重复审核纳入')
                    existing_edges[key]=value['id']
                if value['kind']=='analysis' and decoded['missing_information']:raise HTTPException(422,'分析仍有缺失信息，请补全题目或修订分析后确认')
                def check(node):
                    if isinstance(node,str):validate_text(node)
                    elif isinstance(node,list):
                        for x in node:check(x)
                    elif isinstance(node,dict):
                        for x in node.values():check(x)
                check(decoded)
            selected.append(value)
        for value in selected:
            c.execute('INSERT INTO research_output_history VALUES(?,?,?,?,?)',(uid(),value['id'],value['revision'],packed(value),now()))
            c.execute('UPDATE research_outputs SET state=?,revision=revision+1,reviewer=?,note=? WHERE id=?',('approved' if body.decision=='approve' else 'returned',body.reviewer,body.note,value['id']))
        if any(x['kind']=='relation' and (body.decision=='approve' or x['state']=='approved') for x in selected):c.execute('UPDATE research_contexts SET revision=revision+1 WHERE id=?',(meta['context_id'],))
        c.execute('UPDATE knowledge_runs SET revision=revision+1 WHERE id=?',(run_id,))
        return task_json(c,row(c,'knowledge_runs',run_id))

@router.post('/contexts/{context_id}/graph-versions',status_code=201)
def freeze_graph(context_id:str,body:Retry):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');context=row(c,'research_contexts',context_id);revision(context,body.revision)
        if not context_current(c,context):raise HTTPException(409,'知识版本已过期')
        existing=c.execute('SELECT * FROM research_graph_versions WHERE context_id=? AND context_revision=?',(context_id,context['revision'])).fetchone()
        if existing:return dict(existing)|{'snapshot':json.loads(existing['snapshot'])}
        edges=[dict(x)|{'body':json.loads(x['body'])} for x in c.execute("SELECT * FROM research_outputs WHERE context_id=? AND kind='relation' AND state='approved'",(context_id,))]
        snapshot={'context':json.loads(context['snapshot']),'reviewed_relations':edges,'context_revision':context['revision'],'created_at':now()}
        key=uid();c.execute('INSERT INTO research_graph_versions VALUES(?,?,?,?,?)',(key,context_id,context['revision'],packed(snapshot),now()))
        return {'id':key,'snapshot':snapshot}
@router.get('/graph-versions')
def graph_versions():
    with connect() as c:return [dict(x) for x in c.execute('SELECT id,context_id,context_revision,created_at FROM research_graph_versions ORDER BY created_at DESC')]
@router.post('/outputs/{output_id}/versions',status_code=201)
def freeze_analysis(output_id:str,body:Retry):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');value=row(c,'research_outputs',output_id);revision(value,body.revision)
        run=row(c,'knowledge_runs',value['run_id'])
        if value['kind']!='analysis' or value['state']!='approved' or not sources_current(c,json.loads(run['input_json'])['research_task']):raise HTTPException(409,'只能固定依据有效且已审核的单题研究')
        found=c.execute('SELECT * FROM research_analysis_versions WHERE output_id=? AND revision=?',(output_id,value['revision'])).fetchone()
        if found:return dict(found)|{'snapshot':json.loads(found['snapshot'])}
        meta=json.loads(run['input_json'])['research_task'];question=row(c,'research_question_versions',meta['question_version_id']);context=row(c,'research_contexts',meta['context_id'])
        snapshot={'analysis':json.loads(value['body']),'checks':json.loads(value['checks']),'reviewer':value['reviewer'],'review_note':value['note'],
            'question':json.loads(question['snapshot']),'knowledge':json.loads(context['snapshot']),'model':json.loads(run['model_json']),'run_id':run['id'],'input':meta,
            'graph':json.loads(row(c,'research_graph_versions',meta['graph_version_id'])['snapshot']) if meta.get('graph_version_id') else None,'created_at':now()}
        key=uid();c.execute('INSERT INTO research_analysis_versions VALUES(?,?,?,?,?)',(key,output_id,value['revision'],packed(snapshot),now()))
        return {'id':key,'snapshot':snapshot}
@router.get('/analysis-versions')
def analysis_versions():
    with connect() as c:return [dict(x) for x in c.execute('SELECT id,output_id,revision,created_at FROM research_analysis_versions ORDER BY created_at DESC')]
@router.get('/versions/{kind}/{version_id}/download')
def download(kind:str,version_id:str):
    tables={'analysis':'research_analysis_versions','graph':'research_graph_versions','question':'research_question_versions'}
    if kind not in tables:raise HTTPException(404,'版本类型不存在')
    with connect() as c:
        record=row(c,tables[kind],version_id)
        return Response(record['snapshot'],media_type='application/json',headers={'Content-Disposition':f'attachment; filename="mathlet-{kind}-{version_id[:8]}.json"'})
@router.get('/outputs/{output_id}/history')
def output_history(output_id:str):
    with connect() as c:
        row(c,'research_outputs',output_id)
        return [dict(x)|{'snapshot':json.loads(x['snapshot'])} for x in c.execute('SELECT * FROM research_output_history WHERE output_id=? ORDER BY revision DESC',(output_id,))]

@router.get('/contexts/{context_id}/relations')
def reviewed_relations(context_id:str):
    with connect() as c:
        row(c,'research_contexts',context_id)
        return [dict(x)|{'body':json.loads(x['body'])} for x in c.execute("SELECT * FROM research_outputs WHERE context_id=? AND kind='relation' AND state='approved'",(context_id,))]
class Withdraw(Confirm):context_revision:int
@router.post('/relations/{output_id}/withdraw')
def withdraw(output_id:str,body:Withdraw):
    if not body.confirmed:raise HTTPException(422,'请明确确认撤回关系')
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');value=row(c,'research_outputs',output_id);revision(value,body.revision);context=row(c,'research_contexts',value['context_id']);revision(context,body.context_revision)
        if value['kind']!='relation' or value['state']!='approved' or not context_current(c,context):raise HTTPException(409,'关系不可撤回或知识依据已过期')
        c.execute('INSERT INTO research_output_history VALUES(?,?,?,?,?)',(uid(),output_id,value['revision'],packed(value),now()))
        c.execute("UPDATE research_outputs SET state='returned',revision=revision+1,reviewer=?,note=? WHERE id=?",(body.reviewer,body.note,output_id))
        c.execute('UPDATE research_contexts SET revision=revision+1 WHERE id=?',(context['id'],))
        return context_json(c,row(c,'research_contexts',context['id']))
