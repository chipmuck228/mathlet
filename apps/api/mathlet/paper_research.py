"""Reviewed-paper orchestration. AI suggests; teachers confirm sources and finals."""
import hashlib
import json
from pathlib import Path
from fastapi import APIRouter,HTTPException
from fastapi.responses import Response
from pydantic import Field
from .db import connect,data_dir,uid,now
from .knowledge import row,revision,packed
from .research import version_current,question_json,capture_question,question_current,sources_current,validate_text
from .research_models import Strict,QuestionBody
from .paper_models import PaperItem,ThinkingCard
from .model_provider import load_provider,public_provider

router=APIRouter(prefix='/api/papers',tags=['whole paper research'])
def digest(value):return hashlib.sha256(packed(value).encode()).hexdigest()
def source_snapshot(c,document_id):
    review=c.execute('SELECT * FROM source_reviews WHERE document_id=?',(document_id,)).fetchone()
    if not review:raise HTTPException(422,'请先保存原题核对文件')
    from .source_review import source_identity
    document=dict(row(c,'documents',document_id));saved=json.loads(review['snapshot'])
    blocks=[]
    for r in c.execute('SELECT * FROM blocks WHERE document_id=? ORDER BY ordinal',(document_id,)):
        b=dict(r);assets=[]
        for name in json.loads(b['assets']):
            if Path(name).name!=name:raise HTTPException(422,'原图路径无效')
            path=data_dir()/'documents'/document_id/'assets'/name
            assets.append({'id':b['id']+'/'+name,'name':name,'block_id':b['id'],'hash':hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None,'url':f'/api/documents/{document_id}/assets/{name}'})
        blocks.append({k:b[k] for k in ['id','ordinal','locator','text']}|{'verified':bool(b['verified']),'assets':assets})
    identity={'document_id':document_id,'original_hash':source_identity(document),'blocks':blocks}
    return identity|{'fingerprint':digest(identity),'review':saved['review'],'document_name':document['name'],'category':document['category']}
def project_current(c,p):
    source=json.loads(p['source'])
    if source.get('exam_extraction_version_id'):
        from .exam_extraction import version_current as exam_version_current
        return exam_version_current(c,source['exam_extraction_version_id'])
    try:return source_snapshot(c,p['document_id'])['fingerprint']==json.loads(p['source'])['fingerprint']
    except (HTTPException,OSError):return False

def knowledge_pool(c):
    result=[];seen=set()
    for v in c.execute('SELECT * FROM knowledge_versions ORDER BY created_at DESC'):
        run=row(c,'knowledge_runs',v['run_id'])
        if run['unit_id'] in seen or not version_current(c,v):continue
        seen.add(run['unit_id']);s=json.loads(v['snapshot'])
        for x in s['items']:
            if x['scope']!='excluded':result.append({'ref':v['id']+':'+x['knowledge_id'],'version_id':v['id'],'title':x['body']['name'],'unit_title':s['unit']['title'],'scope':x['scope'],'body':x['body']})
    return result

def locate(text,anchor,n):
    if not anchor:return None
    start=-1
    for _ in range(n+1):
        start=text.find(anchor,start+1)
        if start<0:raise ValueError('原文中未找到定位文字：'+anchor[:60])
    return start

def resolve(p,body):
    source=json.loads(p['source']);blocks={b['id']:b for b in source['blocks']};assets={a['id']:a for b in source['blocks'] for a in b['assets']}
    errors=[];ranges=[];texts={}
    for role in ['question','answer']:
        parts=[]
        for index,span in enumerate(body[role+'_spans']):
            try:
                b=blocks.get(span['block_id'])
                if not b or not b['verified'] and not source.get('exam_extraction_version_id'):raise ValueError('定位块不存在或尚未人工核对')
                start=locate(b['text'],span['start_anchor'],span['start_occurrence']) if span['start_anchor'] else 0
                end=locate(b['text'],span['end_anchor'],span['end_occurrence'])+len(span['end_anchor']) if span['end_anchor'] else len(b['text'])
                if end<=start:raise ValueError('终点必须在起点之后')
                part=b['text'][start:end]
                if not part.strip():raise ValueError('定位范围为空')
                parts.append(part);ranges.append({'role':role,'index':index,'block_id':b['id'],'locator':b['locator'],'start':start,'end':end})
            except ValueError as exc:errors.append(f'{role} 第{index+1}段：{exc}')
        texts[role]='\n\n'.join(parts)
    if source.get('exam_extraction_version_id') and body.get('statement_override') is not None:errors=[]
    selected=[]
    for aid in body['asset_ids']:
        a=assets.get(aid)
        if not a or not blocks[a['block_id']]['verified'] and not source.get('exam_extraction_version_id') or not a['hash']:errors.append('配图不存在、未核对或文件缺失：'+aid)
        else:selected.append(a)
    if body.get('statement_override') is not None:texts['question']=body['statement_override']
    if body.get('answer_override') is not None:texts['answer']=body['answer_override']
    return {'statement':texts['question'],'reference_answer':texts['answer'],'ranges':ranges,'assets':selected,'errors':errors}

def coverage(p,items):
    source=json.loads(p['source']);ranges={};overlaps=[]
    if source.get('exam_extraction_version_id'):return {'overlaps':[],'unassigned':[],'unchecked_blocks':[],'unassigned_assets':[]}
    for item in items:
        for r in item['resolved']['ranges']:
            bucket=ranges.setdefault(r['block_id'],[])
            for a in bucket:
                if max(a['start'],r['start'])<min(a['end'],r['end']):overlaps.append({'item_id':item['id'],'other_item_id':a['item_id'],'block_id':r['block_id'],'locator':r['locator']})
            bucket.append(r|{'item_id':item['id']})
    remaining=[]
    for b in source['blocks']:
        if not b['verified']:continue
        end=0
        for r in sorted(ranges.get(b['id'],[]),key=lambda x:x['start']):
            if r['start']>end and b['text'][end:r['start']].strip():remaining.append({'block_id':b['id'],'locator':b['locator'],'start':end,'end':r['start'],'text':b['text'][end:r['start']]})
            end=max(end,r['end'])
        if b['text'][end:].strip():remaining.append({'block_id':b['id'],'locator':b['locator'],'start':end,'end':len(b['text']),'text':b['text'][end:]})
    assigned={a for i in items for a in i['payload']['asset_ids']}
    return {'overlaps':overlaps,'unassigned':remaining,'unassigned_assets':[a for b in source['blocks'] if b['verified'] for a in b['assets'] if a['id'] not in assigned],'unchecked_blocks':[b['id'] for b in source['blocks'] if not b['verified']]}

def item_json(c,p,i):
    value=dict(i);value['payload']=json.loads(i['payload']);value['resolved']=resolve(p,value['payload']);value['question']=question_json(c,row(c,'research_questions',i['question_id'])) if i['question_id'] else None
    value['runs']=[]
    for r in c.execute('SELECT k.* FROM knowledge_runs k JOIN paper_item_runs p ON p.run_id=k.id WHERE p.item_id=? ORDER BY k.created_at DESC',(i['id'],)):
        outputs=[]
        for o in c.execute('SELECT id,revision FROM research_outputs WHERE run_id=?',(r['id'],)):
            finals=[dict(x) for x in c.execute('SELECT id,created_at FROM research_analysis_versions WHERE output_id=? ORDER BY created_at DESC',(o['id'],))]
            outputs+=finals
        value['runs'].append({'id':r['id'],'status':r['status'],'error':r['error'],'stale':not sources_current(c,json.loads(r['input_json'])['research_task']),'finals':outputs})
    return value

def paper_task_current(c,meta):
    p=c.execute('SELECT * FROM paper_projects WHERE id=?',(meta['project_id'],)).fetchone()
    if not p or p['revision']!=meta['base_revision'] or not project_current(c,p):return False
    if meta['kind']=='recommend':
        for version_id in meta.get('knowledge_version_ids',[]):
            v=c.execute('SELECT * FROM knowledge_versions WHERE id=?',(version_id,)).fetchone()
            if not v or not version_current(c,v):return False
    if meta['kind']=='cards':return card_sources_current(c,meta['sources'])
    return True

def task_json(c,r):
    meta=json.loads(r['input_json'])['paper_task']
    return {k:r[k] for k in ['id','revision','status','error','created_at']}|{'kind':meta['kind'],'stale':(not project_current(c,row(c,'paper_projects',meta['project_id'])) if r['status']=='completed' else not paper_task_current(c,meta)),'calls':[dict(x) for x in c.execute('SELECT step,status,error,reserved_tokens FROM knowledge_calls WHERE run_id=? ORDER BY rowid',(r['id'],))]}
def project_json(c,p):
    items=[item_json(c,p,x) for x in c.execute('SELECT * FROM paper_items WHERE project_id=? AND excluded=0 ORDER BY ordinal',(p['id'],))]
    tasks=[task_json(c,r) for r in c.execute('SELECT * FROM knowledge_runs ORDER BY created_at DESC') if json.loads(r['input_json']).get('paper_task',{}).get('project_id')==p['id']]
    pool=json.loads(p['knowledge'])
    for x in pool:x['stale']=not version_current(c,row(c,'knowledge_versions',x['version_id']))
    return {k:p[k] for k in ['id','title','revision','created_at']}|{'source':json.loads(p['source']),'stale':not project_current(c,p),'knowledge':pool,'notes':json.loads(p['notes']),'items':items,'archived':[{'id':x['id'],'revision':x['revision'],'title':json.loads(x['payload'])['title']} for x in c.execute('SELECT * FROM paper_items WHERE project_id=? AND excluded=1',(p['id'],))],'coverage':coverage(p,items),'tasks':tasks,'cards':[card_json(c,r) for r in c.execute('SELECT * FROM paper_cards WHERE project_id=? ORDER BY rowid DESC',(p['id'],))]}
def mutable(c,p,expected):
    revision(p,expected)
    if not project_current(c,p):raise HTTPException(409,'核对原文已变化，请从当前核对结果建立新的整卷记录；旧记录保留')
    for r in c.execute("SELECT input_json FROM knowledge_runs WHERE status IN ('queued','running')"):
        if json.loads(r['input_json']).get('paper_task',{}).get('project_id')==p['id']:raise HTTPException(409,'整卷任务运行中，请等待后再修改')

def queue(c,p,kind,extra=None,reserve=8000,calls=1):
    config=load_provider()
    if not config.api_key or not config.model:raise HTTPException(422,'请先在知识与关系中配置调用模型')
    if config.output_token_budget<reserve or config.max_calls<calls:raise HTTPException(422,f'本轮需要至少{reserve}输出 tokens 和{calls}次调用预算')
    key=uid();unit=uid();meta={'kind':kind,'project_id':p['id'],'base_revision':p['revision'],**(extra or {})}
    c.execute('INSERT INTO knowledge_units(id,title,chapters,target,notes,origin,created_at) VALUES(?,?,?,?,?,?,?)',(unit,p['title'],'[]','整卷研究','',packed({'internal_paper':True}),now()))
    snapshot={'schema_version':1,'title':p['title'],'chapters':[],'paper_task':meta}
    c.execute("INSERT INTO knowledge_runs(id,unit_id,input_revision,input_json,model_json,status,stage,created_at,updated_at) VALUES(?,?,?,?,?,'queued','paper',?,?)",(key,unit,1,packed(snapshot),packed(public_provider(config)),now(),now()))
    return task_json(c,row(c,'knowledge_runs',key))

class Create(Strict):document_id:str
@router.post('',status_code=201)
def create(body:Create):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');source=source_snapshot(c,body.document_id)
        if not any(b['verified'] and b['text'].strip() for b in source['blocks']):raise HTTPException(422,'请先核对至少一段题目正文')
        key=uid();pool=knowledge_pool(c)
        c.execute('INSERT INTO paper_projects(id,document_id,title,source,knowledge,created_at) VALUES(?,?,?,?,?,?)',(key,body.document_id,source['document_name'],packed(source),packed(pool),now()))
        return project_json(c,row(c,'paper_projects',key))
@router.get('')
def projects():
    with connect() as c:return [{k:r[k] for k in ['id','title','created_at','revision']} for r in c.execute('SELECT * FROM paper_projects ORDER BY created_at DESC')]
@router.get('/{project_id}')
def get_project(project_id:str):
    with connect() as c:return project_json(c,row(c,'paper_projects',project_id))
class Rev(Strict):revision:int
@router.post('/{project_id}/split',status_code=201)
def split(project_id:str,body:Rev):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');p=row(c,'paper_projects',project_id);mutable(c,p,body.revision)
        if c.execute('SELECT 1 FROM paper_items WHERE project_id=?',(project_id,)).fetchone():raise HTTPException(409,'已有分题，请编辑分题边界；需要重新分题可从核对文件新建整卷记录，旧修订保留')
        source=json.loads(p['source']);blocks=[b for b in source['blocks'] if b['verified']]
        if len(blocks)>400 or sum(len(b['text']) for b in blocks)>90000:raise HTTPException(422,'试卷过长，请拆分资料，不会静默截断原文')
        return queue(c,p,'split')
class Select(Rev):item_ids:list[str]=Field(min_length=1,max_length=60)
def chosen(c,p,ids):
    if len(set(ids))!=len(ids):raise HTTPException(422,'题目选择重复')
    values=[row(c,'paper_items',k) for k in ids]
    if any(x['project_id']!=p['id'] or x['excluded'] for x in values):raise HTTPException(422,'题目不属于本卷')
    return values
@router.post('/{project_id}/recommend',status_code=201)
def recommend(project_id:str,body:Select):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');p=row(c,'paper_projects',project_id);mutable(c,p,body.revision);items=chosen(c,p,body.item_ids)
        if any(resolve(p,json.loads(i['payload']))['errors'] for i in items):raise HTTPException(422,'请先修正所选题目的原文边界')
        pool=knowledge_pool(c)
        if not pool:raise HTTPException(422,'尚无有效知识终稿，请先形成知识终稿')
        if len(pool)>1000 or len(packed(pool))>1500000:raise HTTPException(422,'知识池过大，请按主题拆分研究范围')
        active_versions=list(dict.fromkeys(x['version_id'] for x in pool))
        selected_refs={ref for i in c.execute('SELECT payload FROM paper_items WHERE project_id=? AND excluded=0',(project_id,)) for ref in json.loads(i['payload'])['knowledge_refs']}
        known={x['ref'] for x in pool}
        pool.extend(x for x in json.loads(p['knowledge']) if x['ref'] in selected_refs and x['ref'] not in known)
        c.execute('UPDATE paper_projects SET knowledge=?,revision=revision+1 WHERE id=?',(packed(pool),project_id));p=row(c,'paper_projects',project_id)
        chunks=(len(items)+4)//5
        return queue(c,p,'recommend',{'item_ids':body.item_ids,'knowledge_version_ids':active_versions},reserve=chunks*3000,calls=chunks)

@router.post('/{project_id}/items',status_code=201)
def add_item(project_id:str,body:Rev):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');p=row(c,'paper_projects',project_id);mutable(c,p,body.revision)
        count=c.execute('SELECT COUNT(*) FROM paper_items WHERE project_id=? AND excluded=0',(project_id,)).fetchone()[0]
        if count>=60:raise HTTPException(422,'每卷最多60道大题')
        source=json.loads(p['source']);block=next(b for b in source['blocks'] if b['verified'] and b['text'].strip())
        ordinal=c.execute('SELECT COALESCE(MAX(ordinal),-1)+1 FROM paper_items WHERE project_id=?',(project_id,)).fetchone()[0]
        value=PaperItem(title='待分题 '+str(ordinal+1),question_spans=[{'block_id':block['id']}]).model_dump()
        c.execute('INSERT INTO paper_items(id,project_id,ordinal,payload,original_payload) VALUES(?,?,?,?,?)',(uid(),project_id,ordinal,packed(value),packed(value)))
        c.execute('UPDATE paper_projects SET revision=revision+1 WHERE id=?',(project_id,))
        return project_json(c,row(c,'paper_projects',project_id))
class Archive(Rev):item_revision:int;excluded:bool
@router.post('/{project_id}/items/{item_id}/archive')
def archive_item(project_id:str,item_id:str,body:Archive):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');p=row(c,'paper_projects',project_id);mutable(c,p,body.revision);i=row(c,'paper_items',item_id);revision(i,body.item_revision)
        if i['project_id']!=project_id:raise HTTPException(422,'题目不属于本卷')
        c.execute('INSERT INTO paper_item_history VALUES(?,?,?,?,?)',(uid(),item_id,i['revision'],packed(i),now()))
        if i['question_id']:
            q=row(c,'research_questions',i['question_id'])
            c.execute('INSERT INTO research_question_history VALUES(?,?,?,?,?)',(uid(),q['id'],q['revision'],packed(q),now()))
            c.execute("UPDATE research_questions SET confirmed_revision=NULL,revision=revision+1,reviewer='',review_note='' WHERE id=?",(q['id'],))
        c.execute('UPDATE paper_items SET excluded=?,revision=revision+1,question_version_id=NULL,run_id=NULL WHERE id=?',(int(body.excluded),item_id))
        c.execute('UPDATE paper_projects SET revision=revision+1 WHERE id=?',(project_id,))
        return project_json(c,row(c,'paper_projects',project_id))

class SaveItem(Rev):item_revision:int;body:PaperItem
@router.put('/{project_id}/items/{item_id}')
def save_item(project_id:str,item_id:str,body:SaveItem):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');p=row(c,'paper_projects',project_id);mutable(c,p,body.revision);i=chosen(c,p,[item_id])[0];revision(i,body.item_revision)
        payload=body.body.model_dump();old=json.loads(i['payload']);known={x['ref'] for x in json.loads(p['knowledge'])}
        if len(set(payload['knowledge_refs']))!=len(payload['knowledge_refs']) or not set(payload['knowledge_refs'])<=known:raise HTTPException(422,'知识选择重复或不在本卷知识池中')
        c.execute('INSERT INTO paper_item_history VALUES(?,?,?,?,?)',(uid(),item_id,i['revision'],packed(dict(i)),now()))
        changed=any(old.get(k)!=payload[k] for k in payload if k not in {'knowledge_refs','recommendations','knowledge_gaps','boundary_note'})
        qid=i['question_id']
        if changed and qid:
            q=row(c,'research_questions',qid)
            c.execute('INSERT INTO research_question_history VALUES(?,?,?,?,?)',(uid(),qid,q['revision'],packed(q),now()))
            c.execute("UPDATE research_questions SET confirmed_revision=NULL,reviewer='',review_note='',revision=revision+1 WHERE id=?",(qid,))
        c.execute('UPDATE paper_items SET payload=?,revision=revision+1,question_version_id=?,run_id=NULL WHERE id=?',(packed(payload),None if changed else i['question_version_id'],item_id))
        c.execute('UPDATE paper_projects SET revision=revision+1 WHERE id=?',(project_id,))
        return project_json(c,row(c,'paper_projects',project_id))

def question_body(p,item):
    body=json.loads(item['payload']);r=resolve(p,body)
    if r['errors']:raise HTTPException(422,'；'.join(r['errors']))
    qids=list(dict.fromkeys([x['block_id'] for x in body['question_spans']]+[a['block_id'] for a in r['assets']]))
    try:
        return QuestionBody(title=body['title'],statement=r['statement'],question_block_ids=qids,answer_block_ids=list(dict.fromkeys(x['block_id'] for x in body['answer_spans'])),reference_answer=r['reference_answer'],answer_status=body['answer_status'],figure_status=body['figure_status'],diagram_description=body['diagram_description'],region=body['region'],year=body['year'],number=body['number'],notes='整卷分题：'+p['id'],selected_assets=[p['document_id']+'/'+a['name'] for a in r['assets']],source_ranges=[{k:x[k] for k in ['block_id','role','start','end']} for x in r['ranges']])
    except ValueError as exc:raise HTTPException(422,'完整题目超出大小或结构限制：'+str(exc)) from None
class ConfirmItem(Rev):item_revision:int;confirmed:bool
@router.post('/{project_id}/items/{item_id}/confirm')
def confirm_item(project_id:str,item_id:str,body:ConfirmItem):
    if not body.confirmed:raise HTTPException(422,'请确认题干、小问、选项、配图边界和答案状态')
    # Prepare and confirm with the same checks as Stage A; hold a file lock across its transactions.
    from filelock import FileLock
    from .research import confirm_question,Confirm
    with FileLock(str(data_dir()/'paper-confirm.lock')):
        with connect() as c:
            c.execute('BEGIN IMMEDIATE');p=row(c,'paper_projects',project_id);mutable(c,p,body.revision);i=chosen(c,p,[item_id])[0];revision(i,body.item_revision)
            qb=question_body(p,i);payload=capture_question(c,qb);qid=i['question_id'] or uid()
            if i['question_id']:
                q=row(c,'research_questions',qid)
                if json.loads(q['payload'])!=payload:
                    c.execute('INSERT INTO research_question_history VALUES(?,?,?,?,?)',(uid(),qid,q['revision'],packed(q),now()))
                    c.execute("UPDATE research_questions SET payload=?,revision=revision+1,confirmed_revision=NULL,reviewer='',review_note='' WHERE id=?",(packed(payload),qid))
            else:c.execute('INSERT INTO research_questions(id,payload,created_at) VALUES(?,?,?)',(qid,packed(payload),now()))
            c.execute('UPDATE paper_items SET question_id=? WHERE id=?',(qid,item_id));q=row(c,'research_questions',qid)
        result=confirm_question(qid,Confirm(revision=q['revision'],reviewer='本机教师',note='整卷分题边界与完整性确认',confirmed=True))
        with connect() as c:
            c.execute('BEGIN IMMEDIATE');p=row(c,'paper_projects',project_id);revision(p,body.revision)
            c.execute('UPDATE paper_items SET question_version_id=? WHERE id=?',(result['version_id'],item_id))
            c.execute('UPDATE paper_projects SET revision=revision+1 WHERE id=?',(project_id,))
            return project_json(c,row(c,'paper_projects',project_id))

class Batch(Select):instruction:str=Field(default='',max_length=3000)
@router.post('/{project_id}/analyses',status_code=201)
def batch(project_id:str,body:Batch):
    from .research_editor import Start,start_manuscript,relation_references
    with connect() as c:
        p=row(c,'paper_projects',project_id);mutable(c,p,body.revision);items=chosen(c,p,body.item_ids)
        plans=[]
        for i in items:
            b=json.loads(i['payload']);refs=sorted(b['knowledge_refs']);versions=sorted({x.split(':')[0] for x in refs})
            if not i['question_version_id'] or not refs:plans.append((i,None,'请先确认完整题目并选择知识依据'));continue
            relations=[]
            for v in versions:
                available=relation_references(c,[v])
                if available:relations.append(available[0]['id'])
            key='paper:'+digest({'item':i['id'],'question':i['question_version_id'],'refs':sorted(refs),'relations':relations,'instruction':body.instruction})
            plans.append((i,Start(version_ids=versions,question_version_id=i['question_version_id'],knowledge_refs=refs,relation_message_ids=relations,instruction=body.instruction,request_key=key),'') if len(versions)<=5 else (i,None,'每题最多选择五个知识终稿'))
    results=[]
    for i,request,error in plans:
        if request is None:results.append({'item_id':i['id'],'error':error});continue
        try:
            r=start_manuscript(request)
            with connect() as c:
                c.execute('BEGIN IMMEDIATE');latest=row(c,'paper_items',i['id'])
                if latest['revision']!=i['revision']:raise HTTPException(409,'题目选择在发起期间已变化；任务保留在研究记录中')
                c.execute('INSERT OR IGNORE INTO paper_item_runs VALUES(?,?)',(i['id'],r['id']))
                c.execute('UPDATE paper_items SET run_id=? WHERE id=?',(r['id'],i['id']))
            results.append({'item_id':i['id'],'run_id':r['id'],'status':r['status']})
        except HTTPException as exc:results.append({'item_id':i['id'],'error':str(exc.detail)})
    return {'results':results}


def card_sources_current(c,sources):
    try:
        for s in sources:
            v=row(c,'research_analysis_versions',s['id']);f=json.loads(v['snapshot'])
            if digest(f)!=s['hash'] or not sources_current(c,f['input']):return False
        return True
    except HTTPException:return False

def card_check(c,body,sources,final=False):
    value=ThinkingCard.model_validate(body).model_dump();allowed={s['id'] for s in sources}
    examples={e['analysis_id'] for e in value['examples']}
    if len(examples)<2 or not examples<=allowed:raise ValueError('思路卡必须引用至少两道已选研究终稿')
    for step in value['strategy_steps']+value['alternative_paths']+value['transfer_training']:
        if not set(step['analysis_ids'])<=allowed:raise ValueError('思路卡引用不存在的研究终稿')
    if final:
        if value['unresolved']:raise ValueError('请补全或修订仍未解决的内容后定稿')
        def walk(x):
            if isinstance(x,str):validate_text(x)
            elif isinstance(x,list):
                for v in x:walk(v)
            elif isinstance(x,dict):
                for v in x.values():walk(v)
        walk(value)
        if not card_sources_current(c,sources):raise HTTPException(409,'研究终稿依据已变化，旧卡片保留，请重新归纳')
    return value

def card_json(c,r):
    value=dict(r)
    for k in ['payload','original_payload','sources','checks']:value[k]=json.loads(value[k])
    value['stale']=not card_sources_current(c,value['sources']);value['finals']=[dict(v) for v in c.execute('SELECT id,revision,created_at FROM paper_card_versions WHERE card_id=? ORDER BY created_at DESC',(r['id'],))]
    value['read_only']=any(v['revision']==r['revision'] for v in value['finals']);value['blockers']=[]
    try:card_check(c,value['payload'],value['sources'],True)
    except (ValueError,HTTPException) as exc:value['blockers']=[str(exc.detail) if isinstance(exc,HTTPException) else str(exc)]
    return value
class CardStart(Rev):analysis_version_ids:list[str]=Field(min_length=2,max_length=10)
@router.post('/{project_id}/cards',status_code=201)
def start_cards(project_id:str,body:CardStart):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');p=row(c,'paper_projects',project_id);mutable(c,p,body.revision)
        sources=[];questions=set()
        for key in body.analysis_version_ids:
            v=row(c,'research_analysis_versions',key);o=row(c,'research_outputs',v['output_id']);f=json.loads(v['snapshot'])
            belongs=c.execute('SELECT 1 FROM paper_item_runs r JOIN paper_items i ON i.id=r.item_id WHERE r.run_id=? AND i.project_id=?',(o['run_id'],project_id)).fetchone()
            if not belongs:raise HTTPException(422,'研究终稿不属于本卷的题目')
            qid=f['question']['question_id']
            if qid in questions:raise HTTPException(422,'请至少选择两道不同题目，不能将同题不同版本当作多题')
            questions.add(qid);sources.append({'id':key,'hash':digest(f),'title':f['question']['title']})
        if not card_sources_current(c,sources):raise HTTPException(409,'研究终稿依据已变化')
        return queue(c,p,'cards',{'sources':sources},reserve=10500,calls=2)
class CardSave(Strict):revision:int;body:ThinkingCard
@router.put('/{project_id}/cards/{card_id}')
def save_card(project_id:str,card_id:str,body:CardSave):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');r=row(c,'paper_cards',card_id);revision(r,body.revision)
        if r['project_id']!=project_id:raise HTTPException(422,'卡片不属于本卷')
        if card_json(c,r)['read_only']:raise HTTPException(409,'终稿固定，请先继续修订')
        try:value=card_check(c,body.body.model_dump(),json.loads(r['sources']))
        except ValueError as exc:raise HTTPException(422,str(exc)) from None
        if not card_sources_current(c,json.loads(r['sources'])):raise HTTPException(409,'依据已变化')
        c.execute('INSERT INTO paper_card_history VALUES(?,?,?,?,?)',(uid(),card_id,r['revision'],packed(dict(r)),now()))
        c.execute('UPDATE paper_cards SET payload=?,revision=revision+1 WHERE id=?',(packed(value),card_id))
        return card_json(c,row(c,'paper_cards',card_id))
class CardFinal(Strict):revision:int;confirmed:bool
@router.post('/{project_id}/cards/{card_id}/finalize',status_code=201)
def finalize_card(project_id:str,card_id:str,body:CardFinal):
    if not body.confirmed:raise HTTPException(422,'请确认思路卡正文、引用、使用边界与自编练习')
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');r=row(c,'paper_cards',card_id);revision(r,body.revision)
        if r['project_id']!=project_id:raise HTTPException(422,'卡片不属于本卷')
        old=c.execute('SELECT * FROM paper_card_versions WHERE card_id=? AND revision=?',(card_id,body.revision)).fetchone()
        if old:return {'id':old['id']}
        try:value=card_check(c,json.loads(r['payload']),json.loads(r['sources']),True)
        except ValueError as exc:raise HTTPException(422,str(exc)) from None
        key=uid();snapshot={'body':value,'sources':json.loads(r['sources']),'checks':json.loads(r['checks']),'parent_version':r['parent_version'],'teacher_confirmed':True,'created_at':now()}
        c.execute('INSERT INTO paper_card_versions VALUES(?,?,?,?,?)',(key,card_id,r['revision'],packed(snapshot),now()))
        return {'id':key}
@router.get('/card-versions/{version_id}/download')
def download_card(version_id:str):
    with connect() as c:r=row(c,'paper_card_versions',version_id)
    return Response(r['snapshot'],media_type='application/json',headers={'Content-Disposition':f'attachment; filename="thinking-card-{version_id}.json"'})
@router.post('/card-versions/{version_id}/revise',status_code=201)
def revise_card(version_id:str):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');v=row(c,'paper_card_versions',version_id);old=row(c,'paper_cards',v['card_id']);f=json.loads(v['snapshot'])
        if not card_sources_current(c,f['sources']):raise HTTPException(409,'依据已变化，旧终稿保留')
        key=uid();c.execute('INSERT INTO paper_cards(id,project_id,task_id,payload,original_payload,sources,checks,parent_version) VALUES(?,?,?,?,?,?,?,?)',(key,old['project_id'],old['task_id'],packed(f['body']),packed(f['body']),packed(f['sources']),packed(f['checks']),version_id))
        return card_json(c,row(c,'paper_cards',key))
@router.post('/tasks/{run_id}/retry')
def retry(run_id:str,body:Rev):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');r=row(c,'knowledge_runs',run_id);revision(r,body.revision);meta=json.loads(r['input_json']).get('paper_task')
        if not meta:raise HTTPException(404,'整卷任务不存在')
        if r['status'] not in {'failed','interrupted'} or not paper_task_current(c,meta):raise HTTPException(409,'仅可重试依据未变化的失败任务')
        p=row(c,'paper_projects',meta['project_id']);mutable(c,p,p['revision'])
        c.execute("UPDATE knowledge_runs SET status='queued',error='',revision=revision+1,updated_at=? WHERE id=?",(now(),run_id))
        return task_json(c,row(c,'knowledge_runs',run_id))
