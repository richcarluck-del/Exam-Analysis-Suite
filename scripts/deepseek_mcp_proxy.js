const http = require("node:http");
const { Readable } = require("node:stream");
const { URL } = require("node:url");

const PORT = Number(process.env.DEEPSEEK_MCP_PROXY_PORT || "8765");
const TARGET_BASE = process.env.DEEPSEEK_MCP_TARGET || "https://deepseek-mcp.ragweld.com";
const AUTH_TOKEN = process.env.DEEPSEEK_MCP_AUTH_TOKEN || "";

if (!AUTH_TOKEN) {
  console.error("Missing DEEPSEEK_MCP_AUTH_TOKEN.");
  process.exit(1);
}

function buildTargetUrl(req) {
  const incoming = new URL(req.url || "/mcp", `http://127.0.0.1:${PORT}`);
  return new URL(incoming.pathname + incoming.search, TARGET_BASE);
}

function filterHeaders(headers) {
  const next = {};
  for (const [key, value] of Object.entries(headers)) {
    if (value == null) continue;
    const lower = key.toLowerCase();
    if (lower === "host" || lower === "content-length") continue;
    next[key] = value;
  }
  next["Authorization"] = `Bearer ${AUTH_TOKEN}`;
  return next;
}

const server = http.createServer(async (req, res) => {
  if (req.url === "/healthz") {
    res.writeHead(200, { "content-type": "application/json; charset=utf-8" });
    res.end(JSON.stringify({ ok: true, target: TARGET_BASE, port: PORT }));
    return;
  }

  const targetUrl = buildTargetUrl(req);
  const method = req.method || "GET";
  const init = {
    method,
    headers: filterHeaders(req.headers),
  };
  if (!["GET", "HEAD"].includes(method)) {
    init.body = req;
    init.duplex = "half";
  }

  try {
    const upstream = await fetch(targetUrl, init);
    const responseHeaders = {};
    upstream.headers.forEach((value, key) => {
      if (key.toLowerCase() === "content-length") return;
      responseHeaders[key] = value;
    });
    res.writeHead(upstream.status, responseHeaders);
    if (!upstream.body) {
      res.end();
      return;
    }
    Readable.fromWeb(upstream.body).pipe(res);
  } catch (error) {
    res.writeHead(502, { "content-type": "application/json; charset=utf-8" });
    res.end(
      JSON.stringify({
        error: "proxy_upstream_failed",
        message: error instanceof Error ? error.message : String(error),
      }),
    );
  }
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`DeepSeek MCP proxy listening on http://127.0.0.1:${PORT}/mcp`);
});
