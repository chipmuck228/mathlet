import type {Block} from '@/lib/api'
export type KnowledgeItem={ref:string;title:string;unit_title:string;scope:string;body:Record<string,string>}
export type Knowledge={items:KnowledgeItem[];inherited_relations:unknown[];advisory_relations?:unknown[];version_ids:string[]}
export type QuestionBody={selected_assets?:string[]|null;source_ranges?:{block_id:string;role:string;start:number;end:number}[];title:string;question_block_ids:string[];answer_block_ids:string[];statement:string;answer_status:string;reference_answer:string;figure_status:string;diagram_description:string;region:string;year:string;number:string;notes:string}
export type FrozenQuestion=QuestionBody&{assets:{url?:string;data_url?:string;name:string}[];sources:{id:string;document_id:string;document_name:string;locator:string;text:string;category:string;verified:boolean}[]}
export type Question={id:string;revision:number;confirmed:boolean;stale:boolean;version_id:string|null;payload:FrozenQuestion}
export type Output={id:string;revision:number;body:Record<string,unknown>;original_body:Record<string,unknown>;checks:{approach_id:string;category:string;message:string}[];final_version:{id:string}|null;final_blockers:string[]}
export type ResearchRun={id:string;revision:number;title:string;status:string;stale:boolean;error:string;created_at:string;parent_version:string|null;model:{model:string};task:{context_id:string;question_version_id:string;workflow?:string};outputs:Output[];knowledge:Knowledge;question:FrozenQuestion;calls:{step:string;status:string;error:string;reserved_tokens:number}[]}
export type ResearchSummary=Pick<ResearchRun,'id'|'revision'|'title'|'status'|'stale'|'error'|'created_at'|'parent_version'>&{outputs:{id:string;revision:number;final_version:{id:string}|null}[]}
export type ResearchVersion={id:string;output_id:string;revision:number;created_at:string;snapshot:{analysis:Record<string,unknown>;checks:Output['checks'];question:FrozenQuestion;knowledge:Knowledge;run_id:string;run_revision?:number;input:ResearchRun['task'];model:{model:string}}}
export type Discussion={id:string;output_id:string;version_id:string|null;status:string;error:string;response:string;model:{model:string};payload:{instruction:string;output_revision:number;source_version:string|null;uses_unsaved_body:boolean}}
export const initialQuestion:QuestionBody={selected_assets:null,source_ranges:[],title:'',question_block_ids:[],answer_block_ids:[],statement:'',answer_status:'absent',reference_answer:'',figure_status:'not_needed',diagram_description:'',region:'',year:'',number:'',notes:''}
export const researchLabels:Record<string,string>={given_conditions:'已知条件',goals:'所求目标',thinking_operations:'思考操作',problem_types:'题目分类',classification_reason:'分类依据',assessed_points:'考察什么',name:'名称',knowledge_refs:'涉及知识',evidence:'题目中的依据',knowledge_breakdown:'知识分解',ref:'知识',role:'在本题中的作用',conditions:'成立条件',approaches:'可行解题思路',id:'路径编号',title:'标题',trigger:'什么条件提示使用此思路',steps:'推理步骤',action:'这一步做什么',reason:'为什么成立',conclusion:'结论',checks:'怎样检验',limitations:'适用限制',recognition_cues:'识别线索',common_mistakes:'易错点',variation_prompts:'迁移与变式建议',scope_notes:'范围与拓展说明',missing_information:'尚缺信息'}
export function mathBlock(id:string,text:string,label:string,revision=1):Block{return {id,document_id:'',locator:label,text,preview:'',assets:[],warnings:[],verified:false,revision}}

export function orderedResearchKeys(body:Record<string,unknown>):string[]{
 const first=['given_conditions','goals','problem_types','classification_reason','assessed_points','knowledge_breakdown','thinking_operations','approaches','recognition_cues','common_mistakes','variation_prompts','scope_notes','missing_information']
 return [...first.filter(k=>k in body),...Object.keys(body).filter(k=>!first.includes(k))]
}
