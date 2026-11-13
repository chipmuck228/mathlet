"""End-to-end closed loop with ten synthetic knowledge entries, not the user's local finals."""
import json
import pytest
from test_knowledge import client
from test_editorial import prepared,save as save_knowledge
from test_planning import upload
from mathlet.db import connect,uid,now,init_db
from mathlet.knowledge import packed
from mathlet import knowledge_worker as worker

KNOWLEDGE=[
('二元一次方程','含有两个未知数且含未知数项的次数均为1的整式方程。','例如 ax+by=c 中 a、b均不为0。'),
('二元一次方程的解','使方程两边相等的一组未知数的值，是方程的一个解。','将两个未知数的值同时代入判断。'),
('二元一次方程组','由两个含有两个未知数的一次方程组成的方程组，是本节研究对象。','讨论同一组未知数。'),
('方程组的解','使方程组中各个方程同时成立的一组未知数的值是方程组的解。','必须同时满足所有方程。'),
('代入消元法','将一个方程中的某个未知数用另一个未知数表示，代入另一个方程，实现消元。','变形需保持等价；除以的系数不为0。'),
('加减消元法','将两个方程适当变形后相加或相减，消去一个未知数。','需使要消去的未知数系数相同或互为相反数。'),
('等式性质','等式两边加上或减去同一个数或整式，结果仍是等式。','两边同时进行相同运算。'),
('建立等量关系','从题意中找出数量之间的相等关系，再用含未知数的式子表示。','方程必须忠实表达题目条件。'),
('实际意义检验','方程组的代数解还需满足题目中的实际限制。','例如人数为非负整数。'),
('解的代回检验','将求得的一组未知数值代回方程组中的每一个方程检验。','每个方程都应成立。')]

def ready(client,monkeypatch):
    unit,run=prepared(client,monkeypatch)
    # Ten synthetic entries are explicitly fixed via the same whole-manuscript review endpoint.
    with connect() as c:
        existing=[r['id'] for r in c.execute('SELECT id FROM knowledge_candidates WHERE run_id=? ORDER BY rowid',(run['id'],))]
        c.execute('UPDATE knowledge_units SET title=? WHERE id=?',('二元一次方程组（合成测试）',unit['id']))
        for n,(name,statement,conditions) in enumerate(KNOWLEDGE):
            body={'name':name,'kind':'concept' if n<4 else 'method','statement':statement,'conditions':conditions,'formula':'','positive_example':'方程组 x+y=5，x-y=1 的解为 x=3，y=2。','misconception':'只满足其中一个方程不一定是方程组的解。','mastery':'能解释使用条件并检验结果。','method_steps':statement if n>=4 else '','uncertainty':''}
            if n<len(existing):c.execute("UPDATE knowledge_candidates SET body=?,knowledge_id=? WHERE id=?",(packed(body),'synthetic-'+str(n),existing[n]))
            else:c.execute("INSERT INTO knowledge_candidates(id,run_id,knowledge_id,body,original_body,scope) VALUES(?,?,?,?,?,'core')",(uid(),run['id'],'synthetic-'+str(n),packed(body),packed(body)))
    version=client.post('/api/editor/runs/'+run['id']+'/finalize',json={'revision':run['revision'],'confirmed':True});assert version.status_code==201,version.text
    version=version.json()
    doc=upload(client,['合成练习，非中考真题：已知 x+y=5，x-y=1，求x、y。','合成练习，非中考真题：已知 x+y=7，x-y=1，求x、y。'],'mock')
    blocks=client.get('/api/documents/'+doc+'/blocks').json();questions=[]
    for n,b in enumerate(blocks):
        client.put('/api/blocks/'+b['id'],json={'revision':b['revision'],'text':b['text'],'verified':True})
        q=client.post('/api/research/questions',json={'title':'合成方程组练习'+str(n+1),'statement':b['text'],'question_block_ids':[b['id']],'answer_status':'unchecked','reference_answer':'UNREVIEWED-ANSWER-DO-NOT-SEND'}).json()
        q=client.post('/api/research/questions/'+q['id']+'/confirm',json={'revision':q['revision'],'reviewer':'合成测试教师','note':'核对完整转录，未核验参考答案','confirmed':True});assert q.status_code==200,q.text
        questions.append(q.json())
    return version,questions,blocks,run

def case_for(payload):
    ref=payload['knowledge']['items'][5]['ref'];q=payload['question'];large='x+y=7' in q['statement'];total=7 if large else 5;x=4 if large else 3;y=3 if large else 2
    analysis={'given_conditions':[f'x+y={total}','x-y=1'],'goals':['求x、y'],'thinking_operations':['消元与代回检验'],'problem_types':['已知方程组求解'],'classification_reason':'两个未知量需同时满足两个一次方程',
        'assessed_points':[{'name':'加减消元','knowledge_refs':[ref],'evidence':'两个方程中y的系数互为相反数'}],
        'knowledge_breakdown':[{'ref':ref,'role':'消去y并求解','conditions':'y的系数互为相反数'}],
        'approaches':[{'id':'add','title':'两式相加消去y','trigger':'y的系数互为相反数','steps':[{'action':f'两式相加得2x={total+1}，所以x={x}；代回第一式得y={y}。','reason':'同一组解使两式同时成立，两式相加可消去y','knowledge_refs':[ref]}],'conclusion':f'x={x}，y={y}','checks':f'{x}+{y}={total}，{x}-{y}=1。','limitations':'需保持等价变形并代回全部方程'}],
        'recognition_cues':['未知数系数互为相反数'],'common_mistakes':['方程相加时漏掉常数项'],'variation_prompts':['若系数不互为相反数，先怎样变形？'],'scope_notes':[],'missing_information':[]}
    mapping={'id':'map-1','quote':f'x+y={total}，x-y=1','knowledge_ref':ref,'why':'两个方程中y的系数互为相反数，可以消去y','operation':'对比系数，选择消元对象','conditions':'同一组未知数同时满足两个方程','approach_id':'add','step_index':0}
    return {'question_version_id':payload['question_version_id'],'relevance':'primary','relevance_reason':'直接考察用加减消元求方程组的解','analysis':analysis,'applications':[mapping],
        'training':[{'phase':phase,'prompt':prompt,'mapping_ids':['map-1'],'hints':['先观察两个方程中y的系数。','考虑把两个方程相加。'],'expected_reasoning':'比较系数后选择消元，再检验两个方程。','checkpoints':['两个方程是否同时成立？']} for phase,prompt in zip(['read','relate','plan','solve','check'],['写出已知条件和所求目标。','哪些知识可以解释两个方程的联系？','为什么相加比直接代入更方便？','独立完成方程组的求解。','把解代回两个方程，并解释为什么只检验一个方程不够。'])], 'knowledge_gaps':[]}
def model(config,system,payload,tokens):
    assert 'UNREVIEWED-ANSWER-DO-NOT-SEND' not in json.dumps(payload)
    assert 'data:image' not in json.dumps(payload)
    if 'candidate' in payload:return json.dumps({'issues':['教师需核查提示是否过早给出消元方向。']}),None
    return json.dumps(case_for(payload)),None

def start(client,v,qs,key='teaching-request-test'):
    r=client.post('/api/teaching/runs',json={'knowledge_version_id':v['id'],'question_version_ids':[q['version_id'] for q in qs],'request_key':key});assert r.status_code==201,r.text
    return r.json()
def get(client,r):return client.get('/api/teaching/runs/'+r['id']).json()
def finish(client,r):return client.post('/api/teaching/runs/'+r['id']+'/finalize',json={'run_revision':r['revision'],'revision':r['manuscript']['revision'],'confirmed':True})
def save(client,r,body):return client.put('/api/teaching/runs/'+r['id'],json={'run_revision':r['revision'],'revision':r['manuscript']['revision'],'body':body})
def complete(client,monkeypatch):
    v,qs,blocks,base=ready(client,monkeypatch);r=start(client,v,qs);monkeypatch.setattr(worker,'generate',model);assert worker.run_one_knowledge();r=get(client,r)
    assert r['status']=='completed',r['error']
    return r,v,qs,blocks,base


def test_ten_knowledge_two_questions_to_reviewed_offline_reader_with_immutable_revision(client,monkeypatch):
    r,v,qs,blocks,base=complete(client,monkeypatch)
    assert len(r['knowledge']['items'])==10 and len(r['manuscript']['coverage'])==10
    assert len(r['calls'])==4 and all(x['status']=='succeeded' for x in r['calls'])
    assert len([x for x in r['manuscript']['coverage'] if x['applications']])==1
    assert not r['manuscript']['read_only'] and not r['manuscript']['blockers']
    preview=client.get('/api/teaching/runs/'+r['id']+'/preview');assert preview.status_code==200
    assert '未审定草稿' in preview.text and '为什么想到这些知识' in preview.text and '完整真题解析' in preview.text
    final=finish(client,r);assert final.status_code==201,final.text
    fid=final.json()['id'];url='/api/teaching/versions/'+fid+'/download';original=client.get(url).content
    assert '加减消元法' in original.decode() and '未审定草稿' not in original.decode() and '<script' not in original.decode()
    assert 'UNREVIEWED-ANSWER-DO-NOT-SEND' not in original.decode()
    assert b'href="#knowledge-6"' in original
    frozen=client.get('/api/teaching/versions/'+fid+'/json').json();assert frozen['teacher_confirmed'] and len(frozen['knowledge']['items'])==10
    r=get(client,r);assert save(client,r,r['manuscript']['payload']).status_code==409
    fork=client.post('/api/teaching/versions/'+fid+'/revise').json();assert fork['manuscript']['parent_version']==fid and not fork['calls']
    new=fork['manuscript']['payload'];new['title']='教师修订版';changed=save(client,fork,new);assert changed.status_code==200,changed.text
    assert save(client,fork,new).status_code==409
    init_db();assert client.get(url).content==original
    b=blocks[0];client.put('/api/blocks/'+b['id'],json={'revision':2,'text':b['text']+'来源变化','verified':True})
    assert get(client,fork)['stale'] and finish(client,changed.json()).status_code==409
    assert client.get(url).content==original


def test_mapping_rejects_fabricated_quotes_wrong_step_and_foreign_knowledge(client,monkeypatch):
    r,_,_,_,_=complete(client,monkeypatch)
    for field,value in [('quote','不是原文'),('knowledge_ref','foreign-ref'),('step_index',8),('approach_id','missing')]:
        b=json.loads(json.dumps(r['manuscript']['payload']));b['cases'][0]['applications'][0][field]=value
        result=save(client,r,b);assert result.status_code==422,result.text
    b=json.loads(json.dumps(r['manuscript']['payload']));b['cases'][0]['training'][0]['mapping_ids']=['missing']
    assert save(client,r,b).status_code==422
    b=json.loads(json.dumps(r['manuscript']['payload']));b['cases'][0]['training'].reverse()
    assert save(client,r,b).status_code==422
    assert get(client,r)['manuscript']['revision']==1


def test_no_match_does_not_force_knowledge_tags_or_invent_student_training(client,monkeypatch):
    r,_,_,_,_=complete(client,monkeypatch);b=r['manuscript']['payload']
    for case in b['cases']:case.update(relevance='none',analysis=None,applications=[],training=[],relevance_reason='本轮选题未提供与该小节联系的充分依据。')
    changed=save(client,r,b);assert changed.status_code==200,changed.text
    assert '没有匹配' in changed.json()['manuscript']['blockers'][0]
    assert finish(client,changed.json()).status_code==422


def test_task_idempotence_source_mutation_during_call_and_checkpoint_retry(client,monkeypatch):
    v,qs,blocks,_=ready(client,monkeypatch);r=start(client,v,qs);assert start(client,v,qs)['id']==r['id']
    calls=[];fail=True
    def interrupted(config,system,payload,tokens):
        nonlocal fail
        calls.append((payload.get('question_version_id'),bool('candidate' in payload)))
        if 'candidate' not in payload and payload['question_version_id']==qs[1]['version_id'] and fail:fail=False;raise ValueError('模拟第二题中断')
        return model(config,system,payload,tokens)
    monkeypatch.setattr(worker,'generate',interrupted);worker.run_one_knowledge();r=get(client,r)
    assert r['status']=='failed' and not r['manuscript']
    retried=client.post('/api/teaching/runs/'+r['id']+'/retry',json={'revision':r['revision']});assert retried.status_code==200,retried.text
    worker.run_one_knowledge();r=get(client,r);assert r['status']=='completed',r['error']
    assert len([x for x in calls if x==(qs[0]['version_id'],False)])==1
    r2=start(client,v,qs,'new-request-after-success')
    def mutate(*args):
        value=model(*args);b=blocks[0];client.put('/api/blocks/'+b['id'],json={'revision':2,'text':b['text']+'来源改动','verified':True});return value
    monkeypatch.setattr(worker,'generate',mutate);worker.run_one_knowledge();r2=get(client,r2)
    assert r2['status']=='failed' and r2['stale'] and not r2['manuscript']


def test_reuses_a_current_research_final_and_preserves_html_safety(client,monkeypatch):
    v,qs,_,_=ready(client,monkeypatch)
    def research_model(config,system,payload,tokens):
        if 'candidates' in payload:return json.dumps({'issues':[]}),None
        return json.dumps(case_for(payload|{'question_version_id':qs[0]['version_id']})['analysis']),None
    monkeypatch.setattr(worker,'generate',research_model)
    created=client.post('/api/research-editor/runs',json={'version_ids':[v['id']],'question_version_id':qs[0]['version_id'],'request_key':'reuse-research-before-teaching'});assert created.status_code==201,created.text
    worker.run_one_knowledge();research=client.get('/api/research-editor/runs/'+created.json()['id']).json();assert research['status']=='completed',research['error']
    out=research['outputs'][0];final=client.post('/api/research-editor/runs/'+research['id']+'/outputs/'+out['id']+'/finalize',json={'run_revision':research['revision'],'revision':out['revision'],'confirmed':True});assert final.status_code==201,final.text
    r=start(client,v,qs)
    assert r['task']['reused_analysis']=={qs[0]['version_id']:final.json()['id']}
    sent=[]
    def capture(config,system,payload,tokens):sent.append(payload);return model(config,system,payload,tokens)
    monkeypatch.setattr(worker,'generate',capture);worker.run_one_knowledge();r=get(client,r);assert r['status']=='completed',r['error']
    assert sent[0]['existing_research']['teacher_reviewed']
    b=r['manuscript']['payload'];b['cases'][0]['training'][0]['prompt']='<script>alert(1)</script>'
    r=save(client,r,b).json();f=finish(client,r);assert f.status_code==201,f.text
    html=client.get('/api/teaching/versions/'+f.json()['id']+'/download').text
    assert '<script>' not in html and '&lt;script&gt;' in html
