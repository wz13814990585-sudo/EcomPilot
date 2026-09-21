const TASKS = [
  ["data_analysis", "Text-to-SQL / 企业数据分析", "为什么 8 月退款率上涨？", {}],
  ["knowledge_qa", "RAG 店铺政策 / FAQ", "退款政策是什么？", {}],
  ["goods_search", "商品搜索", "搜索防水户外背包", {"sku":"SKU-BAG-001"}],
  ["goods_catalog", "商品目录", "列出全部商品", {}],
  ["stock_analysis", "库存与备货分析", "SKU-BAG-001 需要备货多少天", {"sku":"SKU-BAG-001","predict_days":14}],
  ["competitor_watch", "竞品价格分析", "比较 SKU-BAG-001 与 Temu 的价格", {"sku":"SKU-BAG-001","competitor":"Temu"}],
  ["order_query", "订单查询 / Business API", "查询订单 ORD-20260301-001", {"order_no":"ORD-20260301-001"}],
  ["ad_query", "广告数据查询", "查询广告投放数据", {}],
  ["ad_optimize", "广告优化", "优化当前广告投放", {}],
  ["data_check", "数据完整性检查", "执行数据完整性检查", {}],
  ["ops_report", "运营报告", "生成今日运营日报", {}],
  ["social_marketing", "社媒营销内容", "生成一条户外背包 TikTok 文案", {}],
  ["customer_service", "客服回复", "帮我回复咨询退款的客户", {}],
  ["risk_control", "高风险写操作 / 审批", "对订单 ORD-20260301-001 执行风险标记", {"order_no":"ORD-20260301-001"}]
];

const $ = (id) => document.getElementById(id);
const views = {
  task: $("taskView"),
  customer: $("customerView"),
  competitor: $("competitorView"),
  approval: $("approvalView"),
  system: $("systemView")
};
const titles = {
  task: "通用 Agent 任务",
  customer: "客服 / RAG",
  competitor: "竞品监控",
  approval: "人工审批",
  system: "系统状态"
};

function authHeaders(extra = {}) {
  const mode = sessionStorage.getItem("agent_auth_mode") || $("authMode").value;
  const credential = sessionStorage.getItem("agent_credential") || $("credential").value.trim();
  const headers = {"Content-Type": "application/json", ...extra};
  if (credential) {
    if (mode === "jwt") headers.Authorization = `Bearer ${credential}`;
    else headers["X-API-Key"] = credential;
  }
  return headers;
}

function currentCredential() {
  $("authMode").value = sessionStorage.getItem("agent_auth_mode") || "api_key";
  $("credential").value = sessionStorage.getItem("agent_credential") || "";
}

function approvalFrom(data) {
  if (!data || typeof data !== "object") return "";
  if (typeof data.approval_id === "string" && data.approval_id) return data.approval_id;
  for (const value of Object.values(data)) {
    if (value && typeof value === "object") {
      const found = approvalFrom(value);
      if (found) return found;
    }
  }
  return "";
}

function renderResponse(title, data, latency, ok) {
  $("responseTitle").textContent = title;
  $("responseLatency").textContent = `${Math.round(latency)} ms`;
  $("responseStatus").textContent = ok ? "SUCCESS" : "FAILED";
  $("responseStatus").className = `status ${ok ? "ok" : "bad"}`;
  $("responseJson").textContent = JSON.stringify(data, null, 2);

  const summary =
    data?.summary ||
    data?.data?.summary ||
    data?.error_msg ||
    data?.detail ||
    data?.error ||
    (ok ? "请求执行成功。" : "请求执行失败。");
  $("summaryBox").textContent = typeof summary === "string" ? summary : JSON.stringify(summary);

  const approvalId = approvalFrom(data);
  if (approvalId) {
    $("approvalId").value = approvalId;
    $("taskApprovalId").value = approvalId;
  }
}

async function apiFetch(path, options = {}) {
  const started = performance.now();
  try {
    const response = await fetch(path, options);
    const raw = await response.text();
    let data;
    try { data = raw ? JSON.parse(raw) : {}; }
    catch { data = {raw}; }
    const semanticSuccess = data?.success !== false;
    renderResponse(path, data, performance.now() - started, response.ok && semanticSuccess);
    return {response, data};
  } catch (error) {
    const data = {error: String(error)};
    renderResponse(path, data, performance.now() - started, false);
    return {response: null, data};
  }
}

function jsonPayload() {
  const raw = $("taskPayload").value.trim() || "{}";
  const parsed = JSON.parse(raw);
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error("Payload 必须是 JSON object");
  }
  return parsed;
}

function usePreset(taskType) {
  const item = TASKS.find((entry) => entry[0] === taskType) || TASKS[0];
  $("taskType").value = item[0];
  $("taskQuery").value = item[2];
  $("taskPayload").value = JSON.stringify(item[3], null, 2);
}

function setupCapabilities() {
  const grid = $("capabilityGrid");
  grid.innerHTML = "";
  TASKS.forEach(([type, label]) => {
    const node = document.createElement("button");
    node.type = "button";
    node.className = "capability";
    node.innerHTML = `<strong>${type}</strong><span>${label}</span>`;
    node.addEventListener("click", () => usePreset(type));
    grid.appendChild(node);
  });
}

document.querySelectorAll(".nav-item").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".nav-item").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    Object.values(views).forEach((view) => view.classList.remove("active"));
    views[button.dataset.view].classList.add("active");
    $("viewTitle").textContent = titles[button.dataset.view];
  });
});

$("saveCredential").addEventListener("click", () => {
  sessionStorage.setItem("agent_auth_mode", $("authMode").value);
  sessionStorage.setItem("agent_credential", $("credential").value.trim());
  $("responseTitle").textContent = "凭证已应用";
  $("summaryBox").textContent = "后续 API 请求会使用当前凭证。";
});

$("loadPreset").addEventListener("click", () => {
  const type = $("taskType").value || "data_analysis";
  usePreset(type);
});

$("sendTask").addEventListener("click", async () => {
  try {
    const query = $("taskQuery").value.trim();
    if (!query) throw new Error("Query 不能为空");
    const body = {query, payload: jsonPayload()};
    if ($("taskType").value) body.task_type = $("taskType").value;
    if ($("priority").value !== "") body.priority = Number($("priority").value);
    if ($("taskTimeout").value) body.timeout = Number($("taskTimeout").value);
    const extra = {};
    if ($("taskApprovalId").value.trim()) {
      extra["X-Approval-Id"] = $("taskApprovalId").value.trim();
    }
    await apiFetch("/api/v1/tasks", {
      method: "POST",
      headers: authHeaders(extra),
      body: JSON.stringify(body)
    });
  } catch (error) {
    renderResponse("任务参数错误", {error: String(error)}, 0, false);
  }
});

$("clearTask").addEventListener("click", () => {
  $("taskQuery").value = "";
  $("taskPayload").value = "{}";
  $("taskApprovalId").value = "";
});

$("sendCustomer").addEventListener("click", async () => {
  const body = {
    query: $("customerQuery").value.trim(),
    lang: $("customerLang").value.trim() || "zh",
    use_rag: $("useRag").checked,
    use_taobao: $("useTaobao").checked
  };
  if ($("sessionId").value.trim()) body.session_id = $("sessionId").value.trim();
  if ($("orderNo").value.trim()) body.order_no = $("orderNo").value.trim();
  await apiFetch("/api/v1/customer/chat", {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify(body)
  });
});

$("sendCompetitor").addEventListener("click", async () => {
  const body = {via_master: $("viaMaster").checked};
  if ($("competitorQuery").value.trim()) body.query = $("competitorQuery").value.trim();
  if ($("competitorSku").value.trim()) body.sku = $("competitorSku").value.trim();
  if ($("competitorName").value.trim()) body.competitor = $("competitorName").value.trim();
  if ($("competitorPrice").value) body.compete_price = Number($("competitorPrice").value);
  if ($("competitorTimeout").value) body.timeout = Number($("competitorTimeout").value);
  await apiFetch("/api/v1/warn/competitor", {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify(body)
  });
});

$("approveButton").addEventListener("click", async () => {
  const id = $("approvalId").value.trim();
  if (!id) return renderResponse("审批参数错误", {error: "Approval ID 不能为空"}, 0, false);
  await apiFetch(`/api/v1/approvals/${encodeURIComponent(id)}/approve`, {
    method: "POST",
    headers: authHeaders()
  });
});

$("copyApprovalToTask").addEventListener("click", () => {
  $("taskApprovalId").value = $("approvalId").value.trim();
  document.querySelector('[data-view="task"]').click();
});

$("loadHealth").addEventListener("click", () => apiFetch("/health"));
$("loadReady").addEventListener("click", () => apiFetch("/health/ready"));
$("loadAgents").addEventListener("click", () => apiFetch("/api/v1/agents", {headers: authHeaders()}));

async function checkHealth() {
  const started = performance.now();
  try {
    const response = await fetch("/health/ready");
    const data = await response.json();
    const ok = response.ok && data.ready !== false && data.status === "ready";
    $("healthDot").className = `dot ${ok ? "ok" : "bad"}`;
    $("healthText").textContent = ok ? "Runtime Ready" : "Not Ready";
    renderResponse("/health/ready", data, performance.now() - started, ok);
  } catch (error) {
    $("healthDot").className = "dot bad";
    $("healthText").textContent = "Unavailable";
  }
}

$("checkHealth").addEventListener("click", checkHealth);

currentCredential();
setupCapabilities();
usePreset("data_analysis");
checkHealth();
