import {
  assertFormalWorkflow,
  localizeComponent,
  mergeGraph,
  readComponent,
  replaceNodeWithFragment,
  sticky,
} from './workflow-builder.mjs';

const [webhookSource, ingestSource, publishSource, embeddingSource] = await Promise.all([
  readComponent('kb-ingest-webhook.json'),
  readComponent('kb-ingest-source.json'),
  readComponent('kb-publish-source.json'),
  readComponent('embedding.json'),
]);

const embeddingNames = {
  'Build Embedding Request': '构建分块向量请求',
  'Generate Embeddings': '生成分块向量',
  'Validate Embeddings': '校验分块向量',
};
const publishNames = {
  'Validate Parsed Source': '规范化公共资料分块',
  'Embed Source Chunks': '生成公共资料分块向量',
  'Attach Chunk Embeddings': '合并分块向量',
  'Publish Source Transaction': '事务发布公共资料',
  'Return Publish Result': '整理公共资料发布结果',
};
const ingestNames = {
  'Normalize Ingestion Request': '构建公共资料解析请求',
  'Parse And Build Source Chunks': '解析公共资料原文',
  'Publish Parsed Source': '发布公共资料及分块',
};
const webhookNames = {
  'Receive KB Ingest Request': '接收公共资料',
  'Normalize KB Identity': '校验公共资料身份与权限',
  'KB Request Is Valid': '公共资料请求有效？',
  'Return KB Validation Error': '返回公共资料校验错误',
  'Ingest And Publish Document': '解析并发布公共资料',
  'Return KB Publish Result': '返回公共资料发布结果',
};

const graph = { nodes: [], connections: {} };
const webhook = localizeComponent(webhookSource, {
  names: webhookNames,
  idPrefix: 'public-kb-entry',
  anchor: [120, 280],
  triggerName: '__没有触发器__',
});
mergeGraph(graph, webhook);

const ingest = localizeComponent(ingestSource, {
  names: ingestNames,
  idPrefix: 'public-kb-parse',
  anchor: [1080, 220],
  triggerName: 'When Called By Application',
});
replaceNodeWithFragment(graph, '解析并发布公共资料', ingest);

const publish = localizeComponent(publishSource, {
  names: publishNames,
  idPrefix: 'public-kb-publish',
  anchor: [1800, 220],
  triggerName: 'When Called By Agent',
});
replaceNodeWithFragment(graph, '发布公共资料及分块', publish);

const embedding = localizeComponent(embeddingSource, {
  names: embeddingNames,
  idPrefix: 'public-kb-embedding',
  anchor: [2520, 220],
  triggerName: 'When Called By RAG',
});
replaceNodeWithFragment(graph, '生成公共资料分块向量', embedding);

const identityNode = graph.nodes.find((node) => node.name === '校验公共资料身份与权限');
identityNode.parameters.jsCode = `const request = $input.first()?.json ?? {};
const body = request.body && typeof request.body === 'object' ? request.body : request;
const headers = request.headers && typeof request.headers === 'object' ? request.headers : {};
const tenantId = String(headers['x-tenant-id'] ?? headers['X-Tenant-Id'] ?? '').trim();
const documentId = String(body.document_id ?? '').trim();
const accessGroups = [...new Set(String(headers['x-access-groups'] ?? headers['X-Access-Groups'] ?? '').split(',').map((item) => item.trim()).filter(Boolean))];
const sourceType = String(body.source_type ?? 'knowledge_base').trim() || 'knowledge_base';
const allowedSourceTypes = new Set(['knowledge_base', 'policy', 'planning_guidance', 'case_study', 'statistics', 'research']);
const visibility = body.visibility === 'public' ? 'public' : 'restricted';
const errors = [];
if (!tenantId) errors.push('x-tenant-id is required');
if (!documentId) errors.push('document_id is required');
if (!allowedSourceTypes.has(sourceType)) errors.push('source_type must describe public knowledge material');
if (sourceType === 'project_document' || sourceType === 'test_fixture') errors.push('project documents and test fixtures cannot enter the public knowledge base');
if (visibility === 'restricted' && accessGroups.length === 0) errors.push('restricted documents require x-access-groups');
return [{ json: {
  valid: errors.length === 0, errors, document_id: documentId, tenant_id: tenantId, visibility, access_groups: accessGroups,
  source_type: sourceType, source_url: String(body.source_url ?? '').trim(),
  decision_steps: Array.isArray(body.decision_steps) ? body.decision_steps : [],
  project_types: Array.isArray(body.project_types) ? body.project_types : [],
  geography: Array.isArray(body.geography) ? body.geography : [],
  metadata: body.metadata && typeof body.metadata === 'object' && !Array.isArray(body.metadata) ? body.metadata : {},
} }];`;

const parseRequestNode = graph.nodes.find((node) => node.name === '构建公共资料解析请求');
parseRequestNode.parameters.jsCode = parseRequestNode.parameters.jsCode
  .replaceAll("'project_document'", "'knowledge_base'")
  .replace("if (!documentId) throw new Error('document_id is required');", "if (!documentId) throw new Error('document_id is required');\nif (['project_document', 'test_fixture'].includes(String(input.source_type ?? ''))) throw new Error('public knowledge source_type is required');");

graph.nodes.push(
  sticky('资料接入说明', '## 公共资料接入\n校验租户、权限和公共来源类型。项目原文不会进入此流程。', [80, 80], [900, 620], 'public-kb-note-entry'),
  sticky('解析与向量说明', '## 原文解析与向量化\n保留来源、页码、章节和版本信息，统一生成 768 维向量。', [1040, 80], [2200, 620], 'public-kb-note-vector'),
  sticky('发布说明', '## 事务发布\n文档与分块在同一事务内幂等更新。', [3280, 80], [900, 620], 'public-kb-note-publish'),
);

export default assertFormalWorkflow({
  id: 'urbanRenewalPublicKnowledgeBase',
  name: '城市更新公共知识库',
  active: true,
  nodes: graph.nodes,
  connections: graph.connections,
  settings: { executionOrder: 'v1' },
  versionId: '8f2087a7-dac6-4f8e-9dc8-648583352768',
  meta: { templateCredsSetupCompleted: true },
  tags: [],
});
