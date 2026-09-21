const TASKS = [
  ["data_analysis", "销售与退款分析", "为什么2026年8月退款率上涨？", {}],
  ["knowledge_qa", "RAG 店铺政策 / FAQ", "退款政策是什么？", {}],
  ["goods_search", "商品搜索", "帮我找防水户外背包。", {}],
  ["goods_catalog", "商品目录", "现在店里都有哪些商品？", {}],
  ["stock_analysis", "库存与备货", "哪些商品库存不足，需要优先补货？", {}],
  ["competitor_watch", "竞品价格", "BAG-001 在 Temu 上最近卖多少钱？和我们比呢？", {}],
  ["order_query", "订单查询", "ORD-DEMO-001 现在什么状态？", {}],
  ["ad_query", "广告表现", "目前哪个广告活动 ROAS 最低？", {}],
  ["ad_optimize", "广告优化（需审批）", "帮我暂停表现最差的广告活动。", {}],
  ["data_check", "数据质量", "检查一下当前电商数据有没有异常。", {}],
  ["ops_report", "运营报告", "给我生成今天的运营报告。", {}],
  ["social_marketing", "社媒文案", "给 BAG-001 写一条 TikTok 推广文案。", {}],
  ["customer_service", "客服回复", "客户说 BAG-002 拉链坏了而且想退款，应该怎么回复？", {}],
  ["risk_control", "高风险订单（需审批）", "把 ORD-DEMO-RISK 标记为高风险订单。", {}]
];

let lastTaskBody = null;

const $ = (id) => document.getElementById(id);
const views = {
  task: $("taskView"),
  customer: $("customerView"),
  competitor: $("competitorView"),
  approval: $("approvalView"),
  system: $("systemView"),
  admin: $("adminView")
};
const titles = {
  task: "通用 Agent 任务",
  customer: "客服 / RAG",
  competitor: "竞品监控",
  approval: "人工审批",
  system: "系统状态",
  admin: "管理员控制台"
};

let editingProductSku = "";
let editingRagDocumentId = "";
let productCache = [];

function normalizedError(data) {
  const source = data?.detail && typeof data.detail === "object" ? data.detail : data || {};
  const fallbackMessage = typeof data?.detail === "string" ? data.detail : data?.error_msg || data?.error || "请求没有完成。";
  return {
    title: source.title || "暂时无法完成",
    message: source.message || fallbackMessage,
    nextAction: source.next_action || "请检查输入后重试；持续失败时请联系管理员。",
    taskId: source.task_id || "",
    code: source.error_code || "REQUEST_FAILED"
  };
}

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
  const error = ok ? null : normalizedError(data);
  $("responseTitle").textContent = ok ? "处理完成" : error.title;
  $("responseLatency").textContent = `${Math.round(latency)} ms`;
  $("responseStatus").textContent = ok ? "已完成" : "需要处理";
  $("responseStatus").className = `status ${ok ? "ok" : "bad"}`;
  $("responseJson").textContent = JSON.stringify(data, null, 2);
  $("responseJson").dataset.endpoint = title;

  const presentation = data?.presentation || {};
  const summary =
    error?.message ||
    presentation?.answer ||
    data?.summary ||
    data?.data?.summary ||
    data?.error_msg ||
    data?.detail ||
    data?.error ||
    (ok ? "请求执行成功。" : "请求执行失败。");
  $("summaryBox").textContent = typeof summary === "string" ? summary : JSON.stringify(summary);
  $("summaryBox").className = `summary-box${ok ? "" : " error"}`;
  renderPresentation(presentation, data, error);

  const approvalId = approvalFrom(data);
  if (approvalId) {
    $("approvalId").value = approvalId;
    $("taskApprovalId").value = approvalId;
  }
}

function addMessage(role, text) {
  const node = document.createElement("div");
  node.className = `message ${role}`;
  node.textContent = text;
  $("conversation").appendChild(node);
  node.scrollIntoView({behavior: "smooth", block: "nearest"});
}

function renderPresentation(presentation, raw, error = null) {
  const root = $("resultCards");
  root.replaceChildren();
  if (error) {
    const card = document.createElement("section"); card.className = "result-card error-card";
    const heading = document.createElement("h4"); heading.textContent = "你可以这样处理"; card.appendChild(heading);
    const action = document.createElement("p"); action.className = "next-action"; action.textContent = error.nextAction; card.appendChild(action);
    if (error.taskId) {
      const ref = document.createElement("p"); ref.className = "task-reference"; ref.textContent = `任务编号：${error.taskId}`; card.appendChild(ref);
    }
    root.appendChild(card);
    return;
  }
  const sections = [
    ["关键发现", presentation?.highlights],
    ["建议", presentation?.recommendations],
    ["注意", presentation?.warnings]
  ];
  sections.forEach(([title, values]) => {
    if (!Array.isArray(values) || !values.length) return;
    const card = document.createElement("section");
    card.className = "result-card";
    const heading = document.createElement("h4"); heading.textContent = title; card.appendChild(heading);
    const list = document.createElement("ul");
    values.forEach((value) => { const li = document.createElement("li"); li.textContent = String(value); list.appendChild(li); });
    card.appendChild(list); root.appendChild(card);
  });
  (presentation?.tables || []).forEach((table) => {
    if (!Array.isArray(table.rows) || !table.rows.length) return;
    const card = document.createElement("section"); card.className = "result-card wide";
    const heading = document.createElement("h4"); heading.textContent = table.title || "数据"; card.appendChild(heading);
    const wrap = document.createElement("div"); wrap.className = "table-wrap";
    const grid = document.createElement("table");
    const keys = Object.keys(table.rows[0]);
    const thead = document.createElement("thead"); const hr = document.createElement("tr");
    keys.forEach((key) => { const th = document.createElement("th"); th.textContent = key; hr.appendChild(th); });
    thead.appendChild(hr); grid.appendChild(thead);
    const tbody = document.createElement("tbody");
    table.rows.slice(0, 50).forEach((row) => { const tr = document.createElement("tr"); keys.forEach((key) => { const td = document.createElement("td"); const value = row[key]; td.textContent = typeof value === "object" ? JSON.stringify(value) : String(value ?? ""); tr.appendChild(td); }); tbody.appendChild(tr); });
    grid.appendChild(tbody); wrap.appendChild(grid); card.appendChild(wrap); root.appendChild(card);
  });
  if (presentation?.evidence_summary) {
    const badge = document.createElement("div"); badge.className = "evidence-badge"; badge.textContent = `证据：${presentation.evidence_summary}`; root.appendChild(badge);
  }
  const approvalId = approvalFrom(raw);
  if (approvalId) {
    const card = document.createElement("section"); card.className = "result-card approval-card";
    const heading = document.createElement("h4"); heading.textContent = "需要人工审批"; card.appendChild(heading);
    const note = document.createElement("p"); note.textContent = `目标：${presentation?.approval?.target || "受保护操作"}。审批前不会执行写入。`; card.appendChild(note);
    const button = document.createElement("button"); button.className = "button primary"; button.textContent = "批准并重试";
    button.addEventListener("click", () => approveAndRetry(approvalId)); card.appendChild(button); root.appendChild(card);
  }
}

async function apiFetch(path, options = {}, display = true) {
  const started = performance.now();
  try {
    const response = await fetch(path, options);
    const raw = await response.text();
    let data;
    try { data = raw ? JSON.parse(raw) : {}; }
    catch { data = {raw}; }
    const semanticSuccess = data?.success !== false;
    if (display) renderResponse(path, data, performance.now() - started, response.ok && semanticSuccess);
    return {response, data};
  } catch (error) {
    const data = {error: String(error)};
    if (display) renderResponse(path, data, performance.now() - started, false);
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
  $("taskType").value = "";
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
    if (button.dataset.view === "admin") loadAdmin();
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
    lastTaskBody = body;
    addMessage("user", query);
    const result = await apiFetch("/api/v1/tasks", {
      method: "POST",
      headers: authHeaders(extra),
      body: JSON.stringify(body)
    });
    const friendly = result.response?.ok
      ? result.data?.presentation?.answer || result.data?.summary || "任务已处理。"
      : `${normalizedError(result.data).message}\n${normalizedError(result.data).nextAction}`;
    addMessage("assistant", friendly);
  } catch (error) {
    renderResponse("任务参数错误", {error: String(error)}, 0, false);
  }
});

$("clearTask").addEventListener("click", () => {
  $("taskQuery").value = "";
  $("taskPayload").value = "{}";
  $("taskApprovalId").value = "";
  $("conversation").innerHTML = '<div class="message assistant">新对话已开始，请直接描述你的需求。</div>';
});

async function approveAndRetry(id) {
  const approved = await apiFetch(`/api/v1/approvals/${encodeURIComponent(id)}/approve`, {method: "POST", headers: authHeaders()});
  if (!approved.response?.ok || !lastTaskBody) return;
  const retried = await apiFetch("/api/v1/tasks", {method: "POST", headers: authHeaders({"X-Approval-Id": id}), body: JSON.stringify(lastTaskBody)});
  addMessage("assistant", retried.data?.presentation?.answer || retried.data?.summary || "已重试审批操作。");
}

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

function adminNotice(message, kind = "success") {
  const node = $("adminNotice");
  node.textContent = message;
  node.className = `notice ${kind}`;
}

function clearAdminNotice() {
  $("adminNotice").className = "notice hidden";
}

function cell(text, className = "") {
  const node = document.createElement("td");
  node.textContent = String(text ?? "");
  if (className) node.className = className;
  return node;
}

function actionButton(label, handler, danger = false) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `button small ${danger ? "danger" : "secondary"}`;
  button.textContent = label;
  button.addEventListener("click", handler);
  return button;
}

function renderAdminStats(data) {
  const labels = [
    ["products", "商品"], ["orders", "订单"], ["low_stock_products", "低库存"],
    ["rag_documents", "RAG 文档"], ["rag_chunks", `知识分块 · ${data.retrieval_mode || "none"}`]
  ];
  const root = $("adminStats"); root.replaceChildren();
  labels.forEach(([key, label]) => {
    const card = document.createElement("div"); card.className = "stat-card";
    const value = document.createElement("strong"); value.textContent = String(data[key] ?? 0);
    const caption = document.createElement("span"); caption.textContent = label;
    card.append(value, caption); root.appendChild(card);
  });
}

function renderProducts(items) {
  productCache = items;
  const root = $("productRows"); root.replaceChildren();
  if (!items.length) {
    const row = document.createElement("tr"); const empty = cell("没有匹配的商品。", "empty-cell"); empty.colSpan = 8; row.appendChild(empty); root.appendChild(row); return;
  }
  items.forEach((item) => {
    const row = document.createElement("tr");
    row.append(cell(item.sku), cell(item.title_zh || item.title_en), cell(item.category), cell(`$${Number(item.price).toFixed(2)}`));
    row.append(cell(item.stock_num, item.stock_num <= item.reorder_level ? "stock-low" : ""), cell(item.reorder_level), cell(item.status));
    const actions = cell(""); actions.className = "row-actions";
    actions.append(actionButton("编辑", () => editProduct(item)), actionButton("删除", () => removeProduct(item.sku), true));
    row.appendChild(actions); root.appendChild(row);
  });
}

function renderRagDocuments(items) {
  const root = $("ragRows"); root.replaceChildren();
  if (!items.length) {
    const row = document.createElement("tr"); const empty = cell("没有匹配的知识文档。", "empty-cell"); empty.colSpan = 7; row.appendChild(empty); root.appendChild(row); return;
  }
  items.forEach((item) => {
    const row = document.createElement("tr");
    row.append(cell(item.title), cell(item.category), cell(item.language), cell(item.chunks));
    const mode = cell(item.vector_chunks ? "向量 + 关键词" : "关键词");
    row.append(mode, cell(item.preview));
    const actions = cell(""); actions.className = "row-actions";
    actions.append(actionButton("查看/编辑", () => editRag(item.document_id)), actionButton("删除", () => removeRag(item.document_id), true));
    row.appendChild(actions); root.appendChild(row);
  });
}

async function loadProducts() {
  const query = encodeURIComponent($("productSearch").value.trim());
  const result = await apiFetch(`/api/v1/admin/products?query=${query}&limit=100`, {headers: authHeaders()}, false);
  if (!result.response?.ok) throw result.data;
  renderProducts(result.data.items || []);
}

async function loadRagDocuments() {
  const query = encodeURIComponent($("ragSearch").value.trim());
  const result = await apiFetch(`/api/v1/admin/rag/documents?query=${query}`, {headers: authHeaders()}, false);
  if (!result.response?.ok) throw result.data;
  renderRagDocuments(result.data.items || []);
}

async function loadAdmin() {
  clearAdminNotice();
  try {
    const identity = await apiFetch("/api/v1/admin/me", {headers: authHeaders()}, false);
    if (!identity.response?.ok) throw identity.data;
    const overview = await apiFetch("/api/v1/admin/overview", {headers: authHeaders()}, false);
    if (!overview.response?.ok) throw overview.data;
    renderAdminStats(overview.data);
    await Promise.all([loadProducts(), loadRagDocuments()]);
    adminNotice(`管理员 ${identity.data.user_id} · 店铺 ${identity.data.store_id}`, "success");
  } catch (data) {
    const error = normalizedError(data);
    adminNotice(`${error.message} ${error.nextAction}`, "error");
    $("adminStats").replaceChildren();
  }
}

function resetProductForm() {
  editingProductSku = "";
  $("productForm").reset();
  $("productCategory").value = "general";
  $("productStock").value = "0";
  $("productReorder").value = "20";
  $("productStatus").value = "active";
  $("productSku").disabled = false;
  $("productFormTitle").textContent = "新增商品";
}

function editProduct(item) {
  editingProductSku = item.sku;
  $("productForm").classList.remove("hidden");
  $("productFormTitle").textContent = `编辑 ${item.sku}`;
  $("productSku").value = item.sku; $("productSku").disabled = true;
  $("productTitleZh").value = item.title_zh || ""; $("productTitleEn").value = item.title_en || "";
  $("productCategory").value = item.category || "general"; $("productPrice").value = item.price;
  $("productCost").value = item.cost_price ?? ""; $("productStock").value = item.stock_num;
  $("productReorder").value = item.reorder_level; $("productStatus").value = item.status || "active";
  $("productSupplier").value = item.supplier || ""; $("productTags").value = (item.tags || []).join(", ");
  $("productDescription").value = item.description || "";
  $("productForm").scrollIntoView({behavior: "smooth", block: "center"});
}

function productPayload() {
  return {
    sku: $("productSku").value.trim(), title_zh: $("productTitleZh").value.trim(), title_en: $("productTitleEn").value.trim(),
    category: $("productCategory").value.trim() || "general", price: Number($("productPrice").value),
    cost_price: $("productCost").value === "" ? null : Number($("productCost").value), stock_num: Number($("productStock").value),
    reorder_level: Number($("productReorder").value), status: $("productStatus").value, supplier: $("productSupplier").value.trim(),
    tags: $("productTags").value.split(",").map((tag) => tag.trim()).filter(Boolean), description: $("productDescription").value.trim()
  };
}

async function removeProduct(sku) {
  if (!window.confirm(`确定删除商品 ${sku}？该操作无法从页面撤销。`)) return;
  const result = await apiFetch(`/api/v1/admin/products/${encodeURIComponent(sku)}`, {method: "DELETE", headers: authHeaders()}, false);
  if (!result.response?.ok) return adminNotice(`${normalizedError(result.data).message} ${normalizedError(result.data).nextAction}`, "error");
  adminNotice(result.data.message || "商品已删除。", "success"); await loadProducts();
}

function resetRagForm() {
  editingRagDocumentId = ""; $("ragForm").reset(); $("ragLanguage").value = "zh"; $("ragCategory").value = "general";
  $("ragSku").value = "GENERAL"; $("ragEffectiveDate").value = new Date().toISOString().slice(0, 10);
  $("ragDocumentId").disabled = false; $("ragFormTitle").textContent = "新增知识文档";
}

async function editRag(documentId) {
  const result = await apiFetch(`/api/v1/admin/rag/documents/${encodeURIComponent(documentId)}`, {headers: authHeaders()}, false);
  if (!result.response?.ok) return adminNotice(normalizedError(result.data).message, "error");
  const item = result.data; editingRagDocumentId = documentId; $("ragForm").classList.remove("hidden");
  $("ragFormTitle").textContent = `编辑 ${documentId}`; $("ragDocumentId").value = documentId; $("ragDocumentId").disabled = true;
  $("ragTitle").value = item.title || ""; $("ragCategory").value = item.category || "general"; $("ragLanguage").value = item.language || "zh";
  $("ragSku").value = item.sku || "GENERAL"; $("ragEffectiveDate").value = item.effective_date || ""; $("ragContent").value = item.content || "";
  $("ragForm").scrollIntoView({behavior: "smooth", block: "center"});
}

async function removeRag(documentId) {
  if (!window.confirm(`确定删除知识文档 ${documentId}？`)) return;
  const result = await apiFetch(`/api/v1/admin/rag/documents/${encodeURIComponent(documentId)}`, {method: "DELETE", headers: authHeaders()}, false);
  if (!result.response?.ok) return adminNotice(`${normalizedError(result.data).message} ${normalizedError(result.data).nextAction}`, "error");
  adminNotice(result.data.message || "知识文档已删除。", "success"); await loadRagDocuments();
}

$("refreshAdmin").addEventListener("click", loadAdmin);
$("searchProducts").addEventListener("click", () => loadProducts().catch((data) => adminNotice(normalizedError(data).message, "error")));
$("searchRag").addEventListener("click", () => loadRagDocuments().catch((data) => adminNotice(normalizedError(data).message, "error")));
$("newProduct").addEventListener("click", () => { resetProductForm(); $("productForm").classList.remove("hidden"); });
$("closeProductForm").addEventListener("click", () => $("productForm").classList.add("hidden"));
$("newRag").addEventListener("click", () => { resetRagForm(); $("ragForm").classList.remove("hidden"); });
$("closeRagForm").addEventListener("click", () => $("ragForm").classList.add("hidden"));

$("productForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const method = editingProductSku ? "PUT" : "POST";
  const path = editingProductSku ? `/api/v1/admin/products/${encodeURIComponent(editingProductSku)}` : "/api/v1/admin/products";
  const result = await apiFetch(path, {method, headers: authHeaders(), body: JSON.stringify(productPayload())}, false);
  if (!result.response?.ok) return adminNotice(`${normalizedError(result.data).message} ${normalizedError(result.data).nextAction}`, "error");
  adminNotice(result.data.message || "商品已保存。", "success"); $("productForm").classList.add("hidden"); await loadAdmin();
});

$("ragForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {
    document_id: editingRagDocumentId ? null : ($("ragDocumentId").value.trim() || null), title: $("ragTitle").value.trim(),
    category: $("ragCategory").value.trim() || "general", language: $("ragLanguage").value.trim() || "zh", sku: $("ragSku").value.trim() || "GENERAL",
    effective_date: $("ragEffectiveDate").value || new Date().toISOString().slice(0, 10), content: $("ragContent").value.trim()
  };
  const method = editingRagDocumentId ? "PUT" : "POST";
  const path = editingRagDocumentId ? `/api/v1/admin/rag/documents/${encodeURIComponent(editingRagDocumentId)}` : "/api/v1/admin/rag/documents";
  const result = await apiFetch(path, {method, headers: authHeaders(), body: JSON.stringify(payload)}, false);
  if (!result.response?.ok) return adminNotice(`${normalizedError(result.data).message} ${normalizedError(result.data).nextAction}`, "error");
  adminNotice(result.data.message || "知识文档已保存。", "success"); $("ragForm").classList.add("hidden"); await loadAdmin();
});

$("loadHealth").addEventListener("click", () => apiFetch("/health"));
$("loadReady").addEventListener("click", () => apiFetch("/health/ready"));
$("loadAgents").addEventListener("click", () => apiFetch("/api/v1/agents", {headers: authHeaders()}));
$("loadRagStatus").addEventListener("click", () => apiFetch("/api/v1/system/rag/status", {headers: authHeaders()}));

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
