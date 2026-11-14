"""Bounded model inputs, retaining exact offsets into the full original."""
from .paper_research import locate

BATCH_CHARS=24000
BATCH_BLOCKS=180

class AnchorError(ValueError):pass

def batches(source):
    pieces=[]
    for b in source['blocks']:
        text=b['text']
        if not text.strip() and not b['assets']:continue
        for offset in range(0,max(1,len(text)),BATCH_CHARS):
            part=text[offset:offset+BATCH_CHARS]
            pieces.append(b|{'id':b['id'] if len(text)<=BATCH_CHARS else b['id']+'@'+str(offset),'text':part,'source_block_id':b['id'],'source_offset':offset})
    result=[];batch=[];size=0
    for p in pieces:
        if batch and (size+len(p['text'])>BATCH_CHARS or len(batch)>=BATCH_BLOCKS):result.append(batch);batch=[];size=0
        batch.append(p);size+=len(p['text'])
    if batch:result.append(batch)
    return result

def original_span(span,piece,original):
    value=span.model_dump();text=piece['text'];offset=piece['source_offset']
    try:
        start=locate(text,value['start_anchor'],value['start_occurrence']) if value['start_anchor'] else 0
        end=locate(text,value['end_anchor'],value['end_occurrence'])+len(value['end_anchor']) if value['end_anchor'] else len(text)
    except ValueError as exc:raise AnchorError(str(exc)) from None
    if end<=start:
        # Models sometimes count the end anchor from the question instead of the block.
        # Recover only when there is exactly one eligible occurrence after this start.
        anchor=value['end_anchor'];position=text.find(anchor,start) if anchor else -1
        if position<0 or text.find(anchor,position+1)>=0:
            raise AnchorError('题目起止位置不明确：结束文字位于起点之前，或有多个可能的结束位置')
        end=position+len(anchor)
    if end<=start:raise AnchorError('题目原文定位范围为空')
    start+=offset;end+=offset;full=original['text']
    def anchor_at(pos,length):
        anchor=full[pos:pos+length];found=-1;n=0
        while True:
            found=full.find(anchor,found+1)
            if found==pos:return anchor,n
            if found<0:raise ValueError('题目原文定位映射失败')
            n+=1
    sa,sn=anchor_at(start,min(80,end-start));ea,en=anchor_at(max(start,end-80),min(80,end-start))
    return {'block_id':original['id'],'start_anchor':sa,'end_anchor':ea,'start_occurrence':sn,'end_occurrence':en}

def coalesce(spans,originals):
    result=[]
    for span in spans:
        if result and result[-1]['block_id']==span['block_id']:
            previous=result[-1];text=originals[span['block_id']]['text']
            end=locate(text,previous['end_anchor'],previous['end_occurrence'])+len(previous['end_anchor'])
            start=locate(text,span['start_anchor'],span['start_occurrence'])
            if end==start:
                previous.update(end_anchor=span['end_anchor'],end_occurrence=span['end_occurrence']);continue
        result.append(dict(span))
    return result
