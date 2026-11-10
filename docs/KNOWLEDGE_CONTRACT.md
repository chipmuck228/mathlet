# 知识生产数据与审核契约 v1

实现：knowledge_models.py、knowledge.py、knowledge_worker.py、model_provider.py。知识条目机器可读Schema见 schemas/knowledge-body.schema.json。

## 身份与修订

KnowledgeUnit：生成范围，title/chapters/target/notes/revision，可选内容规划来源。只允许显式输入及已确认规划带入，不推断教材版次或课标覆盖。

KnowledgeRun：输入范围快照、input_revision、模型非密钥配置、prompt_version、执行状态、catalog、selected_ids、检查意见。阶段1所有模型条目的依据为model_prior，教师补充为teacher_authored；不能伪装成检索证据。

Catalog知识ID由服务端生成，不采用模型自编ID；同一清单的编辑及其衍生批次保留知识ID。每次展开／新批次的候选有独立candidate ID。新清单不自动语义合并，避免同名误合并。

KnowledgeCandidate：body、不可变original_body、scope、review_state、revision、reviewer、review_note。每次人工保存及审核前保留旧行到历史表，便于比较。模型只INSERT，不更新已有候选。

KnowledgeCall：step、实际请求（不含认证头）、原始输出、状态、输出预算预留、实际usage或unknown、错误。原始输入是数据，不是更高优先级指令；本阶段不授予模型工具、文件系统或发布能力。

KnowledgeVersion：固定当前候选批次修订的已确认内容、审核人与排除决定、输入与模型信息。重复固定同一修订返回同一版本；下载不实时重算。

## 三个独立维度

执行：queued → running → awaiting_selection → queued → running → completed；失败为failed，重启中断为interrupted。只允许人工恢复失败或中断；复用成功检查点。completed不表示数学正确。

内容审核：pending／returned／approved。修改内容、范围或审核说明后回到pending。批量审核先校验全部范围、归属、修订、内容及声明，再原子提交；任一冲突整批拒绝。

适用范围：pending／core／connection／extension／excluded。scope不等于数学判断；excluded可表示正确但不适合当前目标。不得用难度或题库频率自动认证超纲。

独立依据：当前支持模型已有知识与教师补充；official_coverage_verified固定false。真实来源引用、课标核验、知识关系及单题路径为后续阶段对象，不让空字段冒充已具备。

## 变化传播

修改KnowledgeUnit令旧任务stale，禁止继续展开、重试应用、编辑确认和固定当前版本；原输出保留可读。关联Plan未确认、原件变更引起规划失效或规划修订变化同样使其stale。

人工保存递增candidate修订及run修订；只撤销该条目的确认。确认或退回递增修订。已固定版本不变；未选中条目不随组操作批准。

阶段1知识尚未作为Draft依赖，不修改既有Draft批准或Release快照。未来接入时必须新增依赖映射与逐级过期，不以当前知识确认替代旧草稿审核。

## 检查与数学审阅

Pydantic限制字段与长度、知识类型和输出形状；每批ID必须与清单一致。检查必需内容、方法步骤、公式支持范围和未解决问题；模型另一次调用可提出语义疑问。无疑问不等于证明正确。有模型疑问的纳入项需教师处理说明，内容自身未解决问题需处理后才能确认。

完整题目、原始答案、AI推导、解题路径、关系网络、学生掌握度及全册覆盖率不在本阶段自动产生。

## 执行预算

每次外部调用前持久记录尝试及最大输出预留；失败、截断和中断也计入。请求次数及输出预留达到上限即停止；usage缺失保持null。此限制不等于账单金额上限。生成不会自动接收原文件或开启后台持续调用。

配置保存在忽略的data目录，不进入Git。外部地址必须HTTPS，本机HTTP可用；禁止含账号、查询参数的base URL，不将认证信息跟随重定向。新任务固定服务与模型，配置不同则暂停，不偷偷改投服务。API校验错误也不回显API Key。
