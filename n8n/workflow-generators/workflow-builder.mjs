import { readFile } from 'node:fs/promises';

const componentRoot = new URL('../workflow-components/', import.meta.url);

export async function readComponent(fileName) {
  return JSON.parse(await readFile(new URL(fileName, componentRoot), 'utf8'));
}

export function clone(value) {
  return structuredClone(value);
}

function replaceNames(value, names) {
  if (Array.isArray(value)) return value.map((item) => replaceNames(item, names));
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [names[key] ?? key, replaceNames(item, names)]));
  }
  if (typeof value !== 'string') return value;
  let result = value;
  for (const [from, to] of Object.entries(names).sort((a, b) => b[0].length - a[0].length)) {
    result = result.replaceAll(from, to);
  }
  return result;
}

export function localizeComponent(workflow, { names, idPrefix, anchor = [0, 0], triggerName }) {
  const source = clone(workflow);
  const retained = source.nodes.filter((node) => node.name !== triggerName);
  const minX = Math.min(...retained.map((node) => Number(node.position?.[0] ?? 0)));
  const minY = Math.min(...retained.map((node) => Number(node.position?.[1] ?? 0)));
  const nodes = retained.map((node, index) => {
    const renamed = replaceNames(node, names);
    return {
      ...renamed,
      id: `${idPrefix}-${String(index + 1).padStart(2, '0')}`,
      name: names[node.name] ?? node.name,
      position: [anchor[0] + Number(node.position[0]) - minX, anchor[1] + Number(node.position[1]) - minY],
    };
  });
  const connections = replaceNames(source.connections, names);
  const triggerOutputs = connections[triggerName]?.main?.flat() ?? [];
  delete connections[triggerName];
  const entries = triggerOutputs.map((edge) => edge.node);
  const terminals = nodes
    .map((node) => node.name)
    .filter((name) => !(connections[name]?.main ?? []).some((output) => Array.isArray(output) && output.length));
  return { nodes, connections, entries, terminals };
}

export function mergeGraph(target, fragment) {
  target.nodes.push(...fragment.nodes);
  Object.assign(target.connections, fragment.connections);
}

export function connect(target, from, to, output = 0) {
  const main = target.connections[from]?.main ?? [];
  while (main.length <= output) main.push([]);
  main[output] = [...(main[output] ?? []), { node: to, type: 'main', index: 0 }];
  target.connections[from] = { ...(target.connections[from] ?? {}), main };
}

export function replaceNodeWithFragment(target, nodeName, fragment) {
  const incoming = [];
  for (const [source, definition] of Object.entries(target.connections)) {
    for (const output of definition.main ?? []) {
      for (const edge of output ?? []) {
        if (edge.node === nodeName) incoming.push({ edge, source });
      }
    }
  }
  const outgoing = (target.connections[nodeName]?.main ?? []).flat().map((edge) => edge.node);
  target.nodes = target.nodes.filter((node) => node.name !== nodeName);
  delete target.connections[nodeName];
  for (const { edge } of incoming) edge.node = fragment.entries[0];
  mergeGraph(target, fragment);
  for (const terminal of fragment.terminals) {
    for (const successor of outgoing) connect(target, terminal, successor);
  }
}

export function codeNode(name, jsCode, position, id) {
  return {
    parameters: { mode: 'runOnceForAllItems', jsCode },
    id,
    name,
    type: 'n8n-nodes-base.code',
    typeVersion: 2,
    position,
  };
}

export function postgresNode(name, query, queryReplacement, position, id) {
  return {
    parameters: { operation: 'executeQuery', query, options: { queryReplacement } },
    id,
    name,
    type: 'n8n-nodes-base.postgres',
    typeVersion: 2.7,
    position,
    credentials: { postgres: { id: 'rag-postgres', name: 'RAG PostgreSQL' } },
  };
}

export function sticky(name, content, position, size, id) {
  return {
    parameters: { content, height: size[1], width: size[0], color: 7 },
    id,
    name,
    type: 'n8n-nodes-base.stickyNote',
    typeVersion: 1,
    position,
  };
}

export function assertFormalWorkflow(workflow) {
  const names = workflow.nodes.map((node) => node.name);
  if (new Set(names).size !== names.length) throw new Error(`${workflow.name}: duplicate node names`);
  if (workflow.nodes.some((node) => node.type === 'n8n-nodes-base.executeWorkflow')) {
    throw new Error(`${workflow.name}: sub-workflow node is forbidden`);
  }
  if (names.some((name) => /^(AN|KB|LLM|EMB|RAG)-\d+/i.test(name))) {
    throw new Error(`${workflow.name}: technical node prefix is forbidden`);
  }
  const known = new Set(names);
  for (const [source, definition] of Object.entries(workflow.connections)) {
    if (!known.has(source)) throw new Error(`${workflow.name}: dangling connection source ${source}`);
    for (const output of definition.main ?? []) {
      for (const edge of output ?? []) {
        if (!known.has(edge.node)) throw new Error(`${workflow.name}: dangling connection target ${edge.node}`);
      }
    }
  }
  return workflow;
}
