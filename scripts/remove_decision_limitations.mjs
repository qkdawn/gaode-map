import fs from 'node:fs';

const path = 'n8n/workflows/30-analysis-decision-step.json';
const workflow = JSON.parse(fs.readFileSync(path, 'utf8'));
const request = workflow.nodes.find((node) => node.name === 'Build Structured Decision Request');
const validator = workflow.nodes.find((node) => node.name === 'Validate Decision Output');

request.parameters.jsCode = request.parameters.jsCode
  .replace("  limitations: Array.isArray(value?.limitations) ? value.limitations.slice(0, 4) : [],\n", '')
  .replace("    limitations: { type: 'array', items: { type: 'string' } },\n", '')
  .replace("'step', 'decision_summary', 'findings', 'evidence_used', 'limitations'", "'step', 'decision_summary', 'findings', 'evidence_used'")
  .replace("  '只使用提供的项目资料和检索到的来源；无法判断时写入 limitations，不要编造事实。',", "  '只使用提供的项目资料和检索到的来源，不要编造事实。',");

validator.parameters.jsCode = validator.parameters.jsCode.replace("output.limitations = Array.isArray(output.limitations) ? output.limitations.map(String).filter(Boolean) : [];\n", '');
fs.writeFileSync(path, JSON.stringify(workflow, null, 2) + '\n', 'utf8');
