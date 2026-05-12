const http = require("node:http");
const { URL } = require("node:url");

const HOST = process.env.DEEPSEEK_MCP_HOST || "127.0.0.1";
const PORT = Number(process.env.DEEPSEEK_MCP_PORT || "8765");
const MCP_PATH = process.env.DEEPSEEK_MCP_PATH || "/mcp";
const HEALTH_PATH = process.env.DEEPSEEK_MCP_HEALTH_PATH || "/healthz";
const DEEPSEEK_API_URL =
  process.env.DEEPSEEK_API_URL || "https://api.deepseek.com/chat/completions";
const DEFAULT_MODEL = process.env.DEEPSEEK_DEFAULT_MODEL || "deepseek-v4-pro";
const DEFAULT_TIMEOUT_MS = Number(process.env.DEEPSEEK_TIMEOUT_MS || "180000");
const SERVER_NAME = "deepseek-local-mcp";
const SERVER_VERSION = "0.1.0";

function getApiKey() {
  return (
    process.env.DEEPSEEK_API_KEY ||
    process.env.DEEPSEEK_MCP_AUTH_TOKEN ||
    ""
  ).trim();
}

function sendJson(res, statusCode, payload) {
  res.writeHead(statusCode, {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
  });
  res.end(JSON.stringify(payload));
}

function sendRpcResult(res, id, result) {
  sendJson(res, 200, {
    jsonrpc: "2.0",
    id,
    result,
  });
}

function sendRpcError(res, id, code, message, data) {
  const payload = {
    jsonrpc: "2.0",
    id: id ?? null,
    error: {
      code,
      message,
    },
  };
  if (data !== undefined) {
    payload.error.data = data;
  }
  sendJson(res, 200, payload);
}

function readJsonBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => {
      try {
        const raw = Buffer.concat(chunks).toString("utf8");
        resolve(raw ? JSON.parse(raw) : {});
      } catch (error) {
        reject(error);
      }
    });
    req.on("error", reject);
  });
}

function buildToolDefinitions() {
  return [
    {
      name: "deepseek_chat",
      description:
        "Call DeepSeek chat completion directly. Use this as a worker model for drafting, critique, or subtask execution.",
      inputSchema: {
        type: "object",
        properties: {
          prompt: {
            type: "string",
            description: "The main user prompt sent to DeepSeek.",
          },
          system: {
            type: "string",
            description: "Optional system instruction for DeepSeek.",
          },
          model: {
            type: "string",
            description: `Optional DeepSeek model. Defaults to ${DEFAULT_MODEL}.`,
          },
          temperature: {
            type: "number",
            description: "Optional sampling temperature.",
          },
          max_tokens: {
            type: "integer",
            description: "Optional maximum completion tokens.",
          },
        },
        required: ["prompt"],
        additionalProperties: false,
      },
    },
  ];
}

function extractTextContent(messageContent) {
  if (typeof messageContent === "string") {
    return messageContent;
  }
  if (Array.isArray(messageContent)) {
    return messageContent
      .map((item) => {
        if (!item) return "";
        if (typeof item === "string") return item;
        if (item.type === "text" && typeof item.text === "string") return item.text;
        return "";
      })
      .filter(Boolean)
      .join("\n");
  }
  return "";
}

async function callDeepSeek(argumentsObject) {
  const apiKey = getApiKey();
  if (!apiKey) {
    throw new Error(
      "Missing DeepSeek API key. Set DEEPSEEK_API_KEY or DEEPSEEK_MCP_AUTH_TOKEN.",
    );
  }

  const prompt = String(argumentsObject.prompt || "").trim();
  if (!prompt) {
    throw new Error("Tool deepseek_chat requires a non-empty prompt.");
  }

  const messages = [];
  if (typeof argumentsObject.system === "string" && argumentsObject.system.trim()) {
    messages.push({
      role: "system",
      content: argumentsObject.system.trim(),
    });
  }
  messages.push({
    role: "user",
    content: prompt,
  });

  const requestBody = {
    model:
      typeof argumentsObject.model === "string" && argumentsObject.model.trim()
        ? argumentsObject.model.trim()
        : DEFAULT_MODEL,
    messages,
    stream: false,
  };

  if (typeof argumentsObject.temperature === "number") {
    requestBody.temperature = argumentsObject.temperature;
  }
  if (
    Number.isInteger(argumentsObject.max_tokens) &&
    argumentsObject.max_tokens > 0
  ) {
    requestBody.max_tokens = argumentsObject.max_tokens;
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), DEFAULT_TIMEOUT_MS);
  const startedAt = Date.now();

  try {
    const response = await fetch(DEEPSEEK_API_URL, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(requestBody),
      signal: controller.signal,
    });

    const rawText = await response.text();
    let payload = null;
    try {
      payload = rawText ? JSON.parse(rawText) : null;
    } catch (_error) {
      payload = null;
    }

    if (!response.ok) {
      const message =
        payload?.error?.message ||
        payload?.message ||
        rawText ||
        `DeepSeek API returned HTTP ${response.status}`;
      throw new Error(message);
    }

    const choice = payload?.choices?.[0];
    const content = extractTextContent(choice?.message?.content);
    if (!content) {
      throw new Error("DeepSeek API returned an empty completion.");
    }

    const elapsedMs = Date.now() - startedAt;
    return {
      text: content,
      meta: {
        model: payload?.model || requestBody.model,
        usage: payload?.usage || null,
        elapsed_ms: elapsedMs,
        finish_reason: choice?.finish_reason || null,
      },
    };
  } finally {
    clearTimeout(timer);
  }
}

async function handleRpcRequest(req, res) {
  let payload;
  try {
    payload = await readJsonBody(req);
  } catch (error) {
    sendJson(res, 400, {
      error: "invalid_json",
      message: error instanceof Error ? error.message : String(error),
    });
    return;
  }

  const id = payload?.id ?? null;
  const method = payload?.method;
  const params = payload?.params || {};

  if (payload?.jsonrpc !== "2.0" || typeof method !== "string") {
    sendRpcError(res, id, -32600, "Invalid Request");
    return;
  }

  try {
    if (method === "initialize") {
      sendRpcResult(res, id, {
        protocolVersion:
          typeof params.protocolVersion === "string"
            ? params.protocolVersion
            : "2024-11-05",
        capabilities: {
          tools: {},
        },
        serverInfo: {
          name: SERVER_NAME,
          version: SERVER_VERSION,
        },
      });
      return;
    }

    if (method === "notifications/initialized") {
      res.writeHead(204);
      res.end();
      return;
    }

    if (method === "ping") {
      sendRpcResult(res, id, {});
      return;
    }

    if (method === "tools/list") {
      sendRpcResult(res, id, {
        tools: buildToolDefinitions(),
      });
      return;
    }

    if (method === "tools/call") {
      if (params.name !== "deepseek_chat") {
        sendRpcError(res, id, -32602, `Unknown tool: ${params.name}`);
        return;
      }

      const result = await callDeepSeek(params.arguments || {});
      sendRpcResult(res, id, {
        content: [
          {
            type: "text",
            text: result.text,
          },
        ],
        structuredContent: {
          meta: result.meta,
        },
        isError: false,
      });
      return;
    }

    if (method === "resources/list") {
      sendRpcResult(res, id, { resources: [] });
      return;
    }

    if (method === "prompts/list") {
      sendRpcResult(res, id, { prompts: [] });
      return;
    }

    sendRpcError(res, id, -32601, `Method not found: ${method}`);
  } catch (error) {
    sendRpcResult(res, id, {
      content: [
        {
          type: "text",
          text: error instanceof Error ? error.message : String(error),
        },
      ],
      isError: true,
    });
  }
}

const server = http.createServer(async (req, res) => {
  const incomingUrl = new URL(req.url || "/", `http://${HOST}:${PORT}`);

  if (incomingUrl.pathname === HEALTH_PATH) {
    sendJson(res, 200, {
      ok: true,
      server: SERVER_NAME,
      version: SERVER_VERSION,
      deepseek_api_url: DEEPSEEK_API_URL,
      has_api_key: Boolean(getApiKey()),
    });
    return;
  }

  if (incomingUrl.pathname !== MCP_PATH) {
    sendJson(res, 404, {
      error: "not_found",
      message: `Expected ${MCP_PATH} or ${HEALTH_PATH}.`,
    });
    return;
  }

  if (req.method !== "POST") {
    sendJson(res, 405, {
      error: "method_not_allowed",
      message: "MCP endpoint expects POST JSON-RPC requests.",
    });
    return;
  }

  await handleRpcRequest(req, res);
});

server.listen(PORT, HOST, () => {
  console.log(`DeepSeek local MCP bridge listening on http://${HOST}:${PORT}${MCP_PATH}`);
});
