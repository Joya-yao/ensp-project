// 备用推送：当 github.com:443 不通、但 api.github.com 可用时，
// 用 Git Data API 把本地文件写成一次提交并更新 main。
//
// 用法：GITHUB_TOKEN=... GITHUB_REPO=owner/repo node scripts/push_api.mjs "<commit message>" <file...>
import fs from "node:fs/promises";

const [, , message, ...files] = process.argv;
if (!message || files.length === 0) {
  console.error('usage: GITHUB_REPO=owner/repo node push_api.mjs "<message>" <file...>');
  process.exit(2);
}

const token = process.env.GITHUB_TOKEN;
if (!token) {
  console.error("GITHUB_TOKEN missing");
  process.exit(2);
}

const repo = process.env.GITHUB_REPO;
if (!repo || !repo.includes("/")) {
  console.error("GITHUB_REPO missing (expected owner/repo)");
  process.exit(2);
}
const base = "https://api.github.com";

async function api(path, init = {}) {
  const res = await fetch(base + path, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      "User-Agent": "dsh",
      "Content-Type": "application/json",
      ...(init.headers || {}),
    },
  });
  const text = await res.text();
  if (!res.ok) throw new Error(`${path} -> ${res.status} ${text}`);
  return text ? JSON.parse(text) : null;
}

const ref = await api(`/repos/${repo}/git/ref/heads/main`);
const headSha = ref.object.sha;
const headCommit = await api(`/repos/${repo}/git/commits/${headSha}`);

const tree = [];
for (const path of files) {
  tree.push({
    path: path.replaceAll("\\", "/"),
    mode: "100644",
    type: "blob",
    content: await fs.readFile(path, "utf8"),
  });
}

const newTree = await api(`/repos/${repo}/git/trees`, {
  method: "POST",
  body: JSON.stringify({ base_tree: headCommit.tree.sha, tree }),
});

const commit = await api(`/repos/${repo}/git/commits`, {
  method: "POST",
  body: JSON.stringify({
    message,
    tree: newTree.sha,
    parents: [headSha],
  }),
});

await api(`/repos/${repo}/git/refs/heads/main`, {
  method: "PATCH",
  body: JSON.stringify({ sha: commit.sha }),
});

console.log(`pushed ${commit.sha.slice(0, 7)} on ${repo}/main (${files.length} files)`);
console.log(`https://github.com/${repo}/commit/${commit.sha}`);
