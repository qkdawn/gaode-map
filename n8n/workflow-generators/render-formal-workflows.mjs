import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const outputDirectory = resolve(process.argv[2] || 'runtime/n8n-formal-workflows');
const modules = [
  './urban-renewal-agent.workflow.mjs',
  './public-knowledge-base.workflow.mjs',
];

await mkdir(outputDirectory, { recursive: true });
for (const moduleName of modules) {
  const workflow = (await import(moduleName)).default;
  const fileName = `${workflow.id}.json`;
  await writeFile(resolve(outputDirectory, fileName), JSON.stringify(workflow, null, 2), 'utf8');
  console.log(resolve(outputDirectory, fileName));
}
