import { demand } from './core.mjs';

export class GitHub {
  constructor(token) { demand(token, 'Set GH_TOKEN (the existing shared key).'); this.token = token; }
  async request(path, body, method = body === undefined ? 'GET' : 'POST') {
    const r = await fetch(`https://api.github.com/${path}`, { method, headers: { authorization: `Bearer ${this.token}`, accept: 'application/vnd.github+json', 'content-type': 'application/json', 'user-agent': 'agent-coordination' }, ...(body === undefined ? {} : { body: JSON.stringify(body) }), signal: AbortSignal.timeout(30000) });
    demand(r.ok, `GitHub ${method} ${path.split('?')[0]} returned ${r.status}; no state was assumed.`);
    const value = await r.text(); return value ? JSON.parse(value) : null;
  }
  async pages(path, key = null) {
    const result = [];
    for (let page = 1; page <= 30; page++) {
      const data = await this.request(`${path}${path.includes('?') ? '&' : '?'}per_page=100&page=${page}`);
      const rows = key ? data[key] : data;
      demand(Array.isArray(rows), 'Unexpected GitHub page response.');
      result.push(...rows);
      if (rows.length < 100) return result;
    }
    throw new Error('Pagination limit reached; inventory is incomplete.');
  }
  async graphql(query, variables) {
    const r = await this.request('graphql', { query, variables });
    demand(!r.errors, 'Project/dependency query failed; check access instead of assuming readiness.');
    return r.data;
  }
  async ancestor(repository, from, to) {
    const r = await this.request(`repos/${repository}/compare/${from}...${to}`);
    demand(['ahead', 'identical'].includes(r.status), 'Pinned commit is not an ancestor of the selected main/head revision.');
  }
  async snapshot(repository, number) {
    const pr = await this.request(`repos/${repository}/pulls/${number}`);
    const { parseTask } = await import('./core.mjs');
    const task = parseTask(pr.body);
    const [issue, comments, files, competing] = await Promise.all([
      this.request(`repos/${repository}/issues/${task.issueNumber}`),
      this.pages(`repos/${repository}/issues/${task.issueNumber}/comments`),
      this.pages(`repos/${repository}/pulls/${number}/files`),
      this.pages(`repos/${repository}/pulls?state=open`),
    ]);
    return { repository, pr, issue, comments, files, competing };
  }
  async unchanged(repository, number, expected) {
    const pr = await this.request(`repos/${repository}/pulls/${number}`);
    demand(pr.head.sha === expected.head.sha && pr.body === expected.body && pr.base.sha === expected.base.sha && pr.state === expected.state, 'PR changed during validation; rerun checks.');
    return pr;
  }
}

export const projectId = 'PVT_kwHOE6vsfM4BouSk';
export async function projectItem(api, repository, issueNumber) {
  const [owner, name] = repository.split('/');
  const data = await api.graphql(`query($owner:String!,$name:String!,$n:Int!,$project:ID!,$after:String){repository(owner:$owner,name:$name){issue(number:$n){blockedBy(first:100){nodes{url state}pageInfo{hasNextPage}}}}node(id:$project){... on ProjectV2{items(first:100,after:$after){nodes{id content{... on Issue{url}}fieldValues(first:30){nodes{... on ProjectV2ItemFieldSingleSelectValue{name field{... on ProjectV2SingleSelectField{name}}}}}}pageInfo{hasNextPage endCursor}}fields(first:50){nodes{... on ProjectV2SingleSelectField{id name options{id name}}}}}}}`, { owner, name, n: issueNumber, project: projectId, after: null });
  const issue = data.repository?.issue;
  demand(issue && !issue.blockedBy.pageInfo.hasNextPage, 'Dependency inventory is unavailable or incomplete.');
  const project = data.node;
  let connection = project.items;
  const url = `https://github.com/${repository}/issues/${issueNumber}`;
  let item;
  while (true) {
    item = connection.nodes.find(n => n.content?.url === url);
    if (item || !connection.pageInfo.hasNextPage) break;
    const next = await api.graphql('query($id:ID!,$after:String){node(id:$id){... on ProjectV2{items(first:100,after:$after){nodes{id content{... on Issue{url}}fieldValues(first:30){nodes{... on ProjectV2ItemFieldSingleSelectValue{name field{... on ProjectV2SingleSelectField{name}}}}}}pageInfo{hasNextPage endCursor}}}}}', { id: projectId, after: connection.pageInfo.endCursor });
    connection = next.node.items;
  }
  if (!item) return { item: null, dependencies: issue.blockedBy.nodes };
  const values = Object.fromEntries(item.fieldValues.nodes.filter(n => n.field).map(n => [n.field.name, n.name]));
  return { item: { id: item.id, readiness: values.Readiness, status: values.Status }, dependencies: issue.blockedBy.nodes, fields: project.fields.nodes };
}

export async function setStatus(api, context, name) {
  const f = context.fields.find(f => f.name === 'Status');
  const option = f?.options.find(o => o.name === name);
  demand(option && context.item, 'Project Status field or issue item is missing.');
  await api.graphql('mutation($input:UpdateProjectV2ItemFieldValueInput!){updateProjectV2ItemFieldValue(input:$input){projectV2Item{id}}}', { input: { projectId, itemId: context.item.id, fieldId: f.id, value: { singleSelectOptionId: option.id } } });
}
