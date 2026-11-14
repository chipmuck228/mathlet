"""Whole-paper extraction proposals, manual editing, immutable transcription finals."""
import base64
import hashlib
import json
import os
import tempfile
from pathlib import Path
from fastapi import APIRouter,HTTPException
from fastapi.responses import Response
from .db import connect,data_dir,uid,now
from .knowledge import row,revision,packed
from .model_provider import load_provider,public_provider
from .source_review import source_identity,review_time,filename_at
from .exam_models import ExamBody,ExamQuestion
from .research_models import Strict,QuestionBody
from .research import capture_question

router=APIRouter(prefix='/api',tags=['whole exam extraction'])
def digest(value):return hashlib.sha256(packed(value).encode()).hexdigest()
def raw_source(c,document_id):
    doc=row(c,'documents',document_id)
    if doc['status']!='ready':raise HTTPException(409,'资料尚未完成读取')
    blocks=[]
    for r in c.execute('SELECT * FROM blocks WHERE document_id=? ORDER BY ordinal',(document_id,)):
        assets=[]
        for name in json.loads(r['assets']):
            if Path(name).name!=name:raise HTTPException(422,'图片路径无效')
            p=data_dir()/'documents'/document_id/'assets'/name
            assets.append({'id':r['id']+'/'+name,'block_id':r['id'],'name':name,'hash':hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None,'url':f'/api/documents/{document_id}/assets/{name}'})
        blocks.append({k:r[k] for k in ['id','ordinal','locator','text']}|{'assets':assets})
    identity={'document_id':document_id,'original_hash':source_identity(doc),'blocks':blocks}
    return identity|{'fingerprint':digest(identity),'document_name':doc['name'],'category':doc['category'],'kind':doc['kind']}
def source_current(c,r):
    try:return raw_source(c,r['document_id'])['fingerprint']==json.loads(r['source'])['fingerprint']
    except (HTTPException,OSError):return False

def exam_task_current(c,meta):
    r=c.execute('SELECT * FROM exam_extractions WHERE id=?',(meta['extraction_id'],)).fetchone()
    return bool(r) and source_current(c,r)
def version_current(c,version_id):
    v=row(c,'exam_extraction_versions',version_id);r=row(c,'exam_extractions',v['extraction_id'])
    head=c.execute('SELECT version_id FROM exam_document_heads WHERE document_id=?',(r['document_id'],)).fetchone()
    return bool(head) and head['version_id']==version_id and source_current(c,r)

def validate_body(body,source,final=False):
    value=ExamBody.model_validate(body).model_dump();assets={a['id'] for b in source['blocks'] for a in b['assets']};blocks={b['id'] for b in source['blocks']};keys=set()
    for q in value['questions']:
        if q['key'] in keys:raise HTTPException(422,'题目内部编号重复，请重新添加题目')
        keys.add(q['key'])
        if value['content_mode']=='questions_only' and (q['answer_text'] or q['answer_spans'] or q['answer_image_ids']):raise HTTPException(422,'本提取稿仅包含题目，不能添加答案字段内容')
        if not set(q['image_ids']+q['answer_image_ids'])<=assets:raise HTTPException(422,'选择的图片不属于本份原文')
        if any(s['block_id'] not in blocks for s in q['question_spans']+q['answer_spans']):raise HTTPException(422,'题目原文定位不属于此文件')
        if final and not q['question_text'].strip():raise HTTPException(422,'请补全题目文字或移除空题后定稿')
    # Transcription correctness and formula interpretation are the teacher's judgment, not a renderer veto.
    return value

def detail(c,r):
    run=row(c,'knowledge_runs',r['id']);source=json.loads(r['source']);versions=[dict(v) for v in c.execute('SELECT id,revision,version_number,filename,created_at FROM exam_extraction_versions WHERE extraction_id=? ORDER BY version_number DESC',(r['id'],))]
    payload=json.loads(r['payload']) if r['payload'] else None
    return {k:r[k] for k in ['id','document_id','revision','filename','created_at','parent_version']}|{'status':run['status'],'run_revision':run['revision'],'error':run['error'],'model':json.loads(run['model_json']),'source':source,'payload':payload,'read_only':any(v['revision']==r['revision'] for v in versions),'versions':versions,'stale':not source_current(c,r),'calls':[dict(x) for x in c.execute('SELECT step,status,reserved_tokens,error FROM knowledge_calls WHERE run_id=? ORDER BY rowid',(r['id'],))]}
class Start(Strict):document_id:str

def new_record(c,document_id,config=None,payload=None):
    source=raw_source(c,document_id);key=uid();unit=uid();stamp=review_time();filename=filename_at(stamp)
    # uid suffix prevents a same-clock collision without altering a record's later filename.
    if c.execute('SELECT 1 FROM exam_extractions WHERE filename=?',(filename,)).fetchone():filename=filename[:-5]+'-'+key[:6]+'.json'
    snapshot={'schema_version':1,'title':source['document_name'],'chapters':[],'exam_task':{'extraction_id':key}}
    c.execute('INSERT INTO knowledge_units(id,title,chapters,target,notes,origin,created_at) VALUES(?,?,?,?,?,?,?)',(unit,source['document_name'],'[]','整份原题提取','',packed({'internal_exam':True}),now()))
    c.execute('INSERT INTO knowledge_runs(id,unit_id,input_revision,input_json,model_json,status,stage,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',(key,unit,1,packed(snapshot),packed(public_provider(config)) if config else '{}','completed' if payload else 'queued','completed' if payload else 'exam',now(),now()))
    c.execute('INSERT INTO exam_extractions(id,document_id,source,payload,original_payload,filename,created_at) VALUES(?,?,?,?,?,?,?)',(key,document_id,packed(source),packed(payload) if payload else None,packed(payload) if payload else None,filename,stamp.isoformat()))
    return row(c,'exam_extractions',key)
@router.post('/exam-extractions',status_code=201)
def start(body:Start):
    config=load_provider()
    if not config.api_key or not config.model:raise HTTPException(422,'请先配置模型服务，再点击AI提取整份试卷')
    if config.output_token_budget<10000:raise HTTPException(422,'整卷提取需至少10000输出 tokens 预算')
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');source=raw_source(c,body.document_id)
        existing=c.execute("SELECT e.* FROM exam_extractions e JOIN knowledge_runs k ON k.id=e.id WHERE e.document_id=? AND k.status IN ('queued','running') ORDER BY e.created_at DESC LIMIT 1",(body.document_id,)).fetchone()
        if existing:return detail(c,dict(existing))
        if not source['blocks'] or not any(b['text'].strip() for b in source['blocks']):raise HTTPException(422,'尚无可读取正文；扫描件需先进行文字识别。不会根据空白正文猜题')
        if len(source['blocks'])>500 or sum(len(b['text']) for b in source['blocks'])>100000:raise HTTPException(422,'原文超过本轮范围，请拆分文件；不会静默截断并声称整卷已提取')
        return detail(c,new_record(c,body.document_id,config))
@router.get('/documents/{document_id}/exam-extractions')
def list_records(document_id:str):
    with connect() as c:
        return [{k:r[k] for k in ['id','revision','filename','created_at']}|{'title':json.loads(r['payload'])['title'] if r['payload'] else row(c,'documents',document_id)['name'],'status':r['status'],'final_count':r['final_count']} for r in c.execute('SELECT e.*,k.status,(SELECT COUNT(*) FROM exam_extraction_versions v WHERE v.extraction_id=e.id) final_count FROM exam_extractions e JOIN knowledge_runs k ON k.id=e.id WHERE e.document_id=? ORDER BY e.created_at DESC',(document_id,))]
@router.get('/exam-extractions/{extraction_id}')
def get_record(extraction_id:str):
    with connect() as c:return detail(c,row(c,'exam_extractions',extraction_id))
class Rev(Strict):revision:int
class Save(Rev):body:ExamBody
@router.put('/exam-extractions/{extraction_id}')
def save(extraction_id:str,body:Save):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');r=row(c,'exam_extractions',extraction_id);revision(r,body.revision);d=detail(c,r)
        if d['read_only'] or d['stale'] or d['status']!='completed':raise HTTPException(409,'终稿只读，或来源已变化／提取未完成；请先继续修订或重新提取')
        value=validate_body(body.body.model_dump(),d['source'])
        if packed(value)==r['payload']:return d
        c.execute('INSERT INTO exam_extraction_history VALUES(?,?,?,?,?)',(uid(),extraction_id,r['revision'],packed(r),now()))
        c.execute('UPDATE exam_extractions SET payload=?,revision=revision+1 WHERE id=?',(packed(value),extraction_id))
        return detail(c,row(c,'exam_extractions',extraction_id))


def freeze_assets(source,ids):
    byid={a['id']:a for b in source['blocks'] for a in b['assets']};result=[];size=0
    for key in dict.fromkeys(ids):
        a=byid[key];path=data_dir()/'documents'/source['document_id']/'assets'/a['name']
        if not path.is_file():raise HTTPException(422,'选定图片文件已丢失，请从全部图片中重新选择')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=a['hash']:raise HTTPException(409,'图片在核对期间发生变化，请基于当前原文重新提取')
        size+=len(raw)
        if size>32*1024*1024:raise HTTPException(422,'选定图片合计超过32MB，请减少重复或无关图片')
        result.append(a|{'data_url':'data:image/png;base64,'+base64.b64encode(raw).decode()})
    return result

def publish_questions(c,r,value,assets,version_id):
    """Publish human-confirmed transcription directly, never claim answer-math verification."""
    from .research import question_json
    source=json.loads(r['source']);assetmap={a['id']:a for a in assets};blocks=source['blocks'];byblock={b['id']:b for b in blocks}
    head=c.execute('SELECT v.snapshot FROM exam_document_heads h JOIN exam_extraction_versions v ON v.id=h.version_id WHERE h.document_id=?',(r['document_id'],)).fetchone()
    previous=json.loads(head['snapshot'])['questions'] if head else []
    bykey={q['key']:q for q in previous};numbers={q['number']:[x for x in previous if x['number']==q['number']] for q in previous}
    counts={q['number']:sum(x['number']==q['number'] for x in value['questions']) for q in value['questions']}
    result=[];used=set()
    for q in value['questions']:
        old=bykey.get(q['key'])
        if not old and q['number'] and counts[q['number']]==1 and len(numbers.get(q['number'],[]))==1:old=numbers[q['number']][0]
        if old and not old.get('research_question_id'):old=None
        qid=old['research_question_id'] if old and old['research_question_id'] not in used else uid();used.add(qid)
        qblocks=list(dict.fromkeys([s['block_id'] for s in q['question_spans']]+[assetmap[x]['block_id'] for x in q['image_ids']]))
        if not qblocks:qblocks=[blocks[0]['id']]
        ablocks=list(dict.fromkeys([s['block_id'] for s in q['answer_spans']]+[assetmap[x]['block_id'] for x in q['answer_image_ids']]))
        has_answer=bool(q['answer_text'].strip() or q['answer_image_ids'])
        title=(value['title']+' · '+(q['number'] or str(len(result)+1)))[:160]
        # QuestionBody has tighter research limits; extraction remains valid even for oversized research candidates.
        research_ready=len(qblocks)<=30 and len(ablocks)<=30 and len(q['answer_text'])<=8000
        qblocks=qblocks[:30];ablocks=ablocks[:30]
        qb=QuestionBody(title=title,statement=q['question_text'],question_block_ids=qblocks,answer_block_ids=ablocks if has_answer else [],reference_answer=q['answer_text'][:8000],answer_status='unchecked' if has_answer else 'absent',figure_status='described' if q['diagram_description'].strip() else 'pending' if q['image_ids'] else 'not_needed',diagram_description=q['diagram_description'],number=q['number'],notes='原题整卷提取记录：'+r['id'],selected_assets=[source['document_id']+'/'+assetmap[x]['name'] for x in q['image_ids']])
        # Never silently publish a truncated research question as complete.
        if not research_ready:
            result.append(q|{'research_question_id':old['research_question_id'] if old else None,'question_version_id':None,'research_ready':False,'research_note':'内容超过单题研究容量；整题原文完整保存在此提取文件中，请整理后研究'})
            if old:used.discard(old['research_question_id'])
            continue
        payload=capture_question(c,qb)
        if any(a['hash']!=next(x['hash'] for x in assets if x['name']==a['name']) for a in payload['assets']):raise HTTPException(409,'配图在定稿期间发生变化，请重新核对')
        existing=c.execute('SELECT * FROM research_questions WHERE id=?',(qid,)).fetchone()
        if existing:
            existing=dict(existing)
            if json.loads(existing['payload'])!=payload:
                c.execute('INSERT INTO research_question_history VALUES(?,?,?,?,?)',(uid(),qid,existing['revision'],packed(existing),now()))
                c.execute("UPDATE research_questions SET payload=?,revision=revision+1,confirmed_revision=NULL,reviewer='',review_note='' WHERE id=?",(packed(payload),qid))
        else:c.execute('INSERT INTO research_questions(id,payload,created_at) VALUES(?,?,?)',(qid,packed(payload),now()))
        current=row(c,'research_questions',qid);ready=qb.figure_status!='pending'
        if ready:
            frozen=json.loads(packed(payload))
            for a in frozen['assets']:
                original=next(x for x in assets if x['name']==a['name']);a['data_url']=original['data_url']
            frozen.update(question_id=qid,revision=current['revision'],reviewer='本机教师整卷核对',review_note='核对题干、配图与完整性；本次仅提取题目' if value['content_mode']=='questions_only' else '核对题干、配图和原文解答转录；未核验答案数学正确性',extraction_version_id=version_id)
            c.execute("UPDATE research_questions SET confirmed_revision=revision,reviewer='本机教师整卷核对',review_note=? WHERE id=?",(frozen['review_note'],qid))
            c.execute('INSERT OR IGNORE INTO research_question_versions(id,question_id,revision,snapshot,created_at) VALUES(?,?,?,?,?)',(uid(),qid,current['revision'],packed(frozen),now()))
        qjson=question_json(c,row(c,'research_questions',qid))
        result.append(q|{'research_question_id':qid,'question_version_id':qjson['version_id'] if ready else None,'research_ready':ready,'research_note':'' if ready else '题干与图已核对；后续文字模型研究仍需补充必要图形文字条件'})
    for old in previous:
        qid=old.get('research_question_id')
        if qid and qid not in used:
            q=row(c,'research_questions',qid)
            c.execute('INSERT INTO research_question_history VALUES(?,?,?,?,?)',(uid(),qid,q['revision'],packed(q),now()))
            c.execute("UPDATE research_questions SET revision=revision+1,confirmed_revision=NULL,reviewer='',review_note='' WHERE id=?",(qid,))
    return result

def materialize(v):
    folder=data_dir()/'exam-extractions';folder.mkdir(exist_ok=True)
    path=folder/v['filename'];temp=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',dir=folder,encoding='utf-8',delete=False) as f:
            temp=Path(f.name);os.chmod(f.name,0o600);f.write(v['snapshot'])
        temp.replace(path)
    finally:
        if temp:temp.unlink(missing_ok=True)

class Final(Rev):confirmed:bool
@router.post('/exam-extractions/{extraction_id}/finalize',status_code=201)
def finalize(extraction_id:str,body:Final):
    if not body.confirmed:raise HTTPException(422,'请确认整份试卷的标题、完整题目与配图已核对')
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');r=row(c,'exam_extractions',extraction_id);revision(r,body.revision);d=detail(c,r)
        if d['stale'] or d['status']!='completed' or not d['payload']:raise HTTPException(409,'来源已变化或尚无完整提取稿')
        old=c.execute('SELECT * FROM exam_extraction_versions WHERE extraction_id=? AND revision=?',(extraction_id,r['revision'])).fetchone()
        if old:v=dict(old)
        else:
            value=validate_body(d['payload'],d['source'],True);key=uid();ids=[a for q in value['questions'] for a in q['image_ids']+q['answer_image_ids']];assets=freeze_assets(d['source'],ids)
            questions=publish_questions(c,r,value,assets,key)
            if value['content_mode']=='questions_only':questions=[{k:v for k,v in q.items() if k not in {'answer_text','answer_spans','answer_image_ids'}} for q in questions]
            number=c.execute('SELECT COALESCE(MAX(version_number),0)+1 FROM exam_extraction_versions WHERE extraction_id=?',(extraction_id,)).fetchone()[0]
            if not source_current(c,r):raise HTTPException(409,'原文在定稿期间发生变化，请重新提取')
            filename=r['filename'][:-5]+'-V'+str(number)+'.json'
            snapshot={'format':'mathlet-exam-extraction','schema_version':1,'content_mode':value['content_mode'],'title':value['title'],'questions':questions,'notes':value['notes'],'assets':assets,'source':d['source'],'extraction_id':extraction_id,'extraction_revision':r['revision'],'version_id':key,'version_number':number,'filename':filename,'teacher_confirmed_transcription':True,'answer_math_verified':False,'created_at':now(),'parent_version':r['parent_version']}
            c.execute('INSERT INTO exam_extraction_versions VALUES(?,?,?,?,?,?,?)',(key,extraction_id,r['revision'],number,packed(snapshot),filename,now()))
            c.execute('INSERT INTO exam_document_heads VALUES(?,?) ON CONFLICT(document_id) DO UPDATE SET version_id=excluded.version_id',(r['document_id'],key))
            v=row(c,'exam_extraction_versions',key)
        result=detail(c,row(c,'exam_extractions',extraction_id))
    try:materialize(v);result['file_saved']=True
    except OSError:result.update(file_saved=False,file_error='终稿已保存在数据库，可下载JSON；本地文件副本暂未写入')
    return result
@router.get('/exam-extraction-versions/{version_id}/download')
def download(version_id:str):
    with connect() as c:v=row(c,'exam_extraction_versions',version_id)
    return Response(v['snapshot'],media_type='application/json',headers={'Content-Disposition':f'attachment; filename="{v["filename"]}"'})
@router.get('/exam-extraction-versions/{version_id}')
def get_version(version_id:str):
    with connect() as c:v=row(c,'exam_extraction_versions',version_id);return {'id':v['id'],'snapshot':json.loads(v['snapshot']),'stale':not version_current(c,version_id)}
@router.post('/exam-extractions/{extraction_id}/revise')
def revise(extraction_id:str,body:Rev):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');r=row(c,'exam_extractions',extraction_id);revision(r,body.revision);d=detail(c,r)
        if not d['read_only'] or d['stale']:raise HTTPException(409,'只可基于来源有效的已定稿文件继续修订')
        parent=next(v['id'] for v in d['versions'] if v['revision']==r['revision'])
        c.execute('INSERT INTO exam_extraction_history VALUES(?,?,?,?,?)',(uid(),extraction_id,r['revision'],packed(r),now()))
        c.execute('UPDATE exam_extractions SET revision=revision+1,parent_version=? WHERE id=?',(parent,extraction_id))
        return detail(c,row(c,'exam_extractions',extraction_id))
@router.post('/exam-extractions/{extraction_id}/retry')
def retry(extraction_id:str,body:Rev):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');r=row(c,'exam_extractions',extraction_id);run=row(c,'knowledge_runs',extraction_id);revision(run,body.revision)
        if run['status'] not in {'failed','interrupted'} or not source_current(c,r) or r['payload']:raise HTTPException(409,'仅可重试来源未变化、尚未完成的提取任务')
        c.execute("UPDATE knowledge_runs SET status='queued',error='',revision=revision+1,updated_at=? WHERE id=?",(now(),extraction_id));return detail(c,r)

class ImportFile(Strict):payload:dict
@router.post('/documents/{document_id}/exam-extractions/import',status_code=201)
def import_file(document_id:str,body:ImportFile):
    payload=body.payload
    if len(packed(payload))>50*1024*1024:raise HTTPException(422,'提取文件超过50MB')
    if payload.get('format')!='mathlet-exam-extraction' or payload.get('schema_version')!=1:raise HTTPException(422,'这不是整题提取文件；旧逐块核对文件请使用历史兼容入口')
    try:
        incoming=ExamBody.model_validate({'content_mode':payload.get('content_mode','with_answers'),'title':payload.get('title',''),'questions':[{k:q[k] for k in ExamQuestion.model_fields if k in q} for q in payload.get('questions',[])],'notes':payload.get('notes','')})
        old_blocks=payload['source']['blocks']
        if not isinstance(old_blocks,list) or any(not isinstance(b,dict) or not isinstance(b.get('id'),str) or not isinstance(b.get('ordinal'),int) or not isinstance(b.get('assets'),list) or any(not isinstance(a,dict) or not isinstance(a.get('id'),str) for a in b.get('assets',[])) for b in old_blocks):raise ValueError('来源结构无效')
    except (ValueError,TypeError,KeyError) as exc:raise HTTPException(422,'提取文件结构无效：'+str(exc)) from None
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');source=raw_source(c,document_id)
        if not source['original_hash'] or payload.get('source',{}).get('original_hash')!=source['original_hash']:raise HTTPException(422,'提取文件与当前原始试卷不匹配，请选择对应原文')
        existing=c.execute('SELECT * FROM exam_extraction_versions WHERE id=?',(payload.get('version_id'),)).fetchone()
        if existing and json.loads(existing['snapshot'])==payload:
            record=row(c,'exam_extractions',existing['extraction_id'])
            if record['document_id']!=document_id:raise HTTPException(422,'此提取版本属于另一份资料记录')
            return {'extraction':detail(c,record),'view_version_id':existing['id']}
        old=payload.get('source',{}).get('blocks',[]);byordinal={b['ordinal']:b for b in source['blocks']};blockmap={b['id']:byordinal[b['ordinal']]['id'] for b in old if b.get('ordinal') in byordinal}
        currentassets=[a for b in source['blocks'] for a in b['assets']];assetmap={}
        for b in old:
            for a in b.get('assets',[]):
                match=next((x for x in currentassets if x['hash'] and x['name']==a.get('name') and x['hash']==a.get('hash')),None)
                if match:assetmap[a['id']]=match['id']
        questions=[]
        for q in payload.get('questions',[]):
            clean={k:q[k] for k in ExamQuestion.model_fields if k in q}
            for k in ['image_ids','answer_image_ids']:
                if any(x not in assetmap for x in clean.get(k,[])):raise HTTPException(422,'导入文件中的配图与当前原文不匹配')
                clean[k]=[assetmap[x] for x in clean.get(k,[])]
            for k in ['question_spans','answer_spans']:clean[k]=[s|{'block_id':blockmap[s['block_id']]} for s in clean.get(k,[]) if s['block_id'] in blockmap]
            questions.append(clean)
        try:value=validate_body({'content_mode':payload.get('content_mode','with_answers'),'title':payload.get('title',''),'questions':questions,'notes':payload.get('notes','')},source)
        except ValueError as exc:raise HTTPException(422,str(exc)) from None
        # External edits can never import a teacher-approved flag or overwrite a local final.
        r=new_record(c,document_id,payload=value)
        return {'extraction':detail(c,r),'view_version_id':None}

@router.post('/exam-extraction-versions/{version_id}/revise',status_code=201)
def fork_version(version_id:str):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');v=row(c,'exam_extraction_versions',version_id);r=row(c,'exam_extractions',v['extraction_id'])
        if not source_current(c,r):raise HTTPException(409,'原文已变化，旧终稿保留；请从当前原文重新提取')
        frozen=json.loads(v['snapshot']);value={'content_mode':frozen.get('content_mode','with_answers'),'title':frozen['title'],'questions':[{k:q[k] for k in ExamQuestion.model_fields if k in q} for q in frozen['questions']],'notes':frozen['notes']}
        new=new_record(c,r['document_id'],payload=value)
        c.execute('UPDATE exam_extractions SET parent_version=? WHERE id=?',(version_id,new['id']))
        return detail(c,row(c,'exam_extractions',new['id']))

@router.get('/exam-extraction-versions')
def finalized_files():
    with connect() as c:
        rows=c.execute('SELECT v.*,d.name,d.id document_id FROM exam_document_heads h JOIN exam_extraction_versions v ON v.id=h.version_id JOIN documents d ON d.id=h.document_id ORDER BY v.created_at DESC').fetchall()
        return [{'id':v['id'],'document_id':v['document_id'],'document_name':v['name'],'title':json.loads(v['snapshot'])['title'],'filename':v['filename'],'stale':not version_current(c,v['id'])} for v in rows]
@router.post('/exam-extraction-versions/{version_id}/paper',status_code=201)
def open_paper(version_id:str):
    from .paper_research import project_json,knowledge_pool
    from .paper_models import PaperItem
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        if not version_current(c,version_id):raise HTTPException(409,'请选择当前原文对应的最新核对终稿')
        found=c.execute('SELECT project_id FROM exam_extraction_papers WHERE version_id=?',(version_id,)).fetchone()
        if found:return project_json(c,row(c,'paper_projects',found['project_id']))
        v=row(c,'exam_extraction_versions',version_id);f=json.loads(v['snapshot']);source=f['source'];project=uid()
        source=source|{'exam_extraction_version_id':version_id,'review':{'filename':f['filename']},'blocks':[b|{'verified':False} for b in source['blocks']]}
        c.execute('INSERT INTO paper_projects(id,document_id,title,source,knowledge,notes,created_at) VALUES(?,?,?,?,?,?,?)',(project,source['document_id'],f['title'],packed(source),packed(knowledge_pool(c)),packed(['已按完整题目核对定稿，直接进入知识推荐与研究，无需再逐块核对或分题。']),now()))
        for ordinal,q in enumerate(f['questions']):
            spans=q['question_spans'] or [{'block_id':source['blocks'][0]['id']}]
            has_answer=bool(q.get('answer_text','').strip() or q.get('answer_image_ids',[]))
            body=PaperItem(title=(f['title']+' · '+(q['number'] or str(ordinal+1)))[:160],number=q['number'],question_spans=spans,answer_spans=q.get('answer_spans',[]) if has_answer else [],asset_ids=q['image_ids'],answer_status='unchecked' if has_answer else 'absent',figure_status='described' if q['diagram_description'].strip() else 'pending' if q['image_ids'] else 'not_needed',diagram_description=q['diagram_description'],boundary_note=q['notes'],statement_override=q['question_text'],answer_override=q.get('answer_text','')).model_dump()
            c.execute('INSERT INTO paper_items(id,project_id,ordinal,payload,original_payload,question_id,question_version_id) VALUES(?,?,?,?,?,?,?)',(uid(),project,ordinal,packed(body),packed(body),q.get('research_question_id'),q.get('question_version_id')))
        c.execute('INSERT INTO exam_extraction_papers VALUES(?,?)',(version_id,project))
        return project_json(c,row(c,'paper_projects',project))
