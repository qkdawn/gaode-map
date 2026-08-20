import { chmod, mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';

const credentialTarget = '/tmp/gaode-n8n-credentials.json';
const workflowTarget = '/tmp/gaode-n8n-workflows';

if (process.argv.includes('--cleanup')) {
  await rm(credentialTarget, { force: true });
  await rm(workflowTarget, { force: true, recursive: true });
  process.exit(0);
}

let stdin = '';
for await (const chunk of process.stdin) {
  stdin += chunk;
}

function parseJson(value, label) {
  try {
    return JSON.parse(String(value || '{}').replace(/^\uFEFF/, ''));
  } catch {
    throw new Error(`Invalid JSON in ${label}`);
  }
}

parseJson(stdin, 'bootstrap runtime');
const replacements = {
  __RAG_DB_NAME__: process.env.RAG_DB_NAME,
  __RAG_DB_USER__: process.env.RAG_DB_USER,
  __RAG_DB_PASSWORD__: process.env.RAG_DB_PASSWORD,
  __DOCUMENT_API_BASE_URL__: String(process.env.DOCUMENT_API_BASE_URL || '').replace(/\/$/, ''),
  __SPATIAL_API_BASE_URL__: String(process.env.SPATIAL_API_BASE_URL || '').replace(/\/$/, ''),
  __SPATIAL_MCP_URL__: String(process.env.SPATIAL_MCP_URL || '').replace(/\/$/, ''),
  __EMBEDDING_API_BASE_URL__: String(process.env.EMBEDDING_API_BASE_URL || 'http://host.docker.internal:11435').replace(/\/$/, ''),
  __EMBEDDING_MODEL__: process.env.EMBEDDING_MODEL || 'jinaai/jina-embeddings-v2-base-zh',
  __EMBEDDING_DIMENSIONS__: process.env.EMBEDDING_DIMENSIONS || '768',
  __N8N_WEBHOOK_API_KEY__: process.env.N8N_WEBHOOK_API_KEY,
};

for (const [placeholder, value] of Object.entries(replacements)) {
  if (!value) {
    throw new Error(`Missing required bootstrap value for ${placeholder}`);
  }
}

function replacePlaceholders(value) {
  if (Array.isArray(value)) {
    return value.map(replacePlaceholders);
  }
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, replacePlaceholders(item)]),
    );
  }
  if (typeof value !== 'string') {
    return value;
  }
  let rendered = value;
  for (const [placeholder, replacement] of Object.entries(replacements)) {
    rendered = rendered.replaceAll(placeholder, replacement);
  }
  return rendered;
}

const credentialFiles = await readdir('/bootstrap/credentials');
const credentials = [];
for (const fileName of credentialFiles.filter((name) => name.endsWith('.json')).sort()) {
  const source = parseJson(
    await readFile(`/bootstrap/credentials/${fileName}`, 'utf8'),
    `credential ${fileName}`,
  );
  credentials.push(...replacePlaceholders(source));
}
await writeFile(credentialTarget, JSON.stringify(credentials, null, 2), {
  encoding: 'utf8',
  mode: 0o600,
});
await chmod(credentialTarget, 0o600);

await rm(workflowTarget, { force: true, recursive: true });
await mkdir(workflowTarget, { mode: 0o700, recursive: true });
const workflowFiles = await readdir('/bootstrap/workflows');
for (const fileName of workflowFiles.filter((name) => name.endsWith('.json')).sort()) {
  const source = parseJson(
    await readFile(`/bootstrap/workflows/${fileName}`, 'utf8'),
    `workflow ${fileName}`,
  );
  const targetPath = `${workflowTarget}/${fileName}`;
  await writeFile(targetPath, JSON.stringify(replacePlaceholders(source), null, 2), {
    encoding: 'utf8',
    mode: 0o600,
  });
  await chmod(targetPath, 0o600);
}

const generatorDirectory = '/bootstrap/workflow-generators';
const generatorFiles = await readdir(generatorDirectory);
for (const fileName of generatorFiles.filter((name) => name.endsWith('.workflow.mjs')).sort()) {
  const moduleUrl = `${pathToFileURL(`${generatorDirectory}/${fileName}`).href}?bootstrap=${Date.now()}`;
  const generated = (await import(moduleUrl)).default;
  const workflows = Array.isArray(generated) ? generated : [generated];
  for (const workflow of workflows) {
    if (!workflow || typeof workflow !== 'object' || !workflow.id || !workflow.name) {
      throw new Error(`Invalid generated workflow from ${fileName}`);
    }
    const targetPath = `${workflowTarget}/${fileName.replace(/\.mjs$/, '')}-${workflow.id}.json`;
    await writeFile(targetPath, JSON.stringify(replacePlaceholders(workflow), null, 2), {
      encoding: 'utf8',
      mode: 0o600,
    });
    await chmod(targetPath, 0o600);
  }
}
