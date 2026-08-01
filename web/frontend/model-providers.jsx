import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  QueryClient,
  QueryClientProvider,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { ConfirmDialog, ModalDialog } from "./components/dialog";
import {
  deleteModelProvider,
  fetchProviderModels,
  getModelProvider,
  listModelProviders,
  saveModelProvider,
  testProviderLatency,
  testProviderModel,
} from "./model-provider-api";

const toast = window.showToast;
const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 10_000, retry: 1 } },
});
const BODY_REFERENCES = {
  OPENAI_COMPATIBLE: {
    temperature: 0,
    top_p: 0.8,
    max_tokens: 1024,
    response_format: { type: "json_object" },
  },
  OPENAI_RESPONSES: {
    reasoning: { effort: "medium" },
    max_output_tokens: 1024,
    text: { format: { type: "json_object" } },
  },
  ANTHROPIC: {
    temperature: 0,
    top_p: 0.8,
    max_tokens: 1024,
    thinking: { type: "disabled" },
  },
};

function Icon({ name }) {
  return (
    <span
      aria-hidden="true"
      dangerouslySetInnerHTML={{ __html: window.icon(name) }}
    />
  );
}
function protocolLabel(value) {
  if (value === "OPENAI_RESPONSES") return "OpenAI Responses API";
  return value === "ANTHROPIC"
    ? "Anthropic Claude Messages"
    : "OpenAI Chat Completions";
}
function endpoint(protocol, baseUrl) {
  try {
    const url = new URL(baseUrl.trim());
    let path = url.pathname.replace(/\/+$/, "");
    ["/chat/completions", "/responses", "/messages"].some((suffix) => {
      if (!path.endsWith(suffix)) return false;
      path = path.slice(0, -suffix.length);
      return true;
    });
    if (protocol === "ANTHROPIC" && !/\/v[12]$/i.test(path)) path += "/v1";
    url.pathname = `${path}${protocol === "OPENAI_RESPONSES" ? "/responses" : protocol === "ANTHROPIC" ? "/messages" : "/chat/completions"}`;
    url.search = "";
    url.hash = "";
    return url.toString();
  } catch {
    return null;
  }
}
function providerName(provider) {
  return provider.name || "未命名供应商";
}

function Pagination({ total, page, pageSize, onPage, onSize }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const safePage = Math.min(page, pages);
  useEffect(() => {
    if (safePage !== page) onPage(safePage);
  }, [safePage, page, onPage]);
  return (
    <div
      className="global-list-footer management-list-footer"
      id="model-provider-pagination"
    >
      <div className="global-page-summary">
        <span>共 {total} 个供应商</span>
        <label>
          每页{" "}
          <select
            className="input global-page-size"
            aria-label="每页展示数量"
            value={pageSize}
            onChange={(e) => onSize(Number(e.target.value))}
          >
            {[10, 20, 50, 100].map((n) => (
              <option key={n}>{n}</option>
            ))}
          </select>
        </label>
      </div>
      <div className="global-pagination">
        <button
          type="button"
          aria-label="上一页"
          disabled={safePage <= 1}
          onClick={() => onPage(safePage - 1)}
        >
          <Icon name="previous" />
        </button>
        <span>
          {safePage} / {pages}
        </span>
        <button
          type="button"
          aria-label="下一页"
          disabled={safePage >= pages}
          onClick={() => onPage(safePage + 1)}
        >
          <Icon name="next" />
        </button>
      </div>
    </div>
  );
}

function ProviderList({ onEdit }) {
  const client = useQueryClient();
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [deleting, setDeleting] = useState(null);
  const providersQuery = useQuery({
    queryKey: ["model-providers"],
    queryFn: listModelProviders,
  });
  useEffect(() => {
    if (providersQuery.error)
      toast(`加载模型供应商失败：${providersQuery.error.message}`, "error");
  }, [providersQuery.error]);
  const providers = providersQuery.data || [];
  const filtered = useMemo(
    () =>
      providers.filter((provider) =>
        [
          provider.name,
          provider.website_url,
          provider.base_url,
          provider.protocol,
          ...(provider.models || []),
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase()
          .includes(query),
      ),
    [providers, query],
  );
  const rows = filtered.slice((page - 1) * pageSize, page * pageSize);
  const remove = useMutation({
    mutationFn: deleteModelProvider,
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["model-providers"] });
      toast("模型供应商已删除", "success");
    },
    onError: (error) => toast(`删除模型供应商失败: ${error.message}`, "error"),
  });
  function confirmDelete(provider) {
    setDeleting(provider);
  }
  return (
    <section
      className="execution-page model-provider-page"
      aria-labelledby="model-provider-title"
    >
      <header className="execution-page-header management-page-header">
        <div className="management-page-title">
          <h1 id="model-provider-title">供应商管理</h1>
          <span className="management-page-description">
            配置模型接入与连接
          </span>
        </div>
        <span className="execution-count" id="model-provider-count">
          {providers.length} 个供应商
        </span>
      </header>
      <div
        className="toolbar execution-toolbar management-list-toolbar"
        id="model-provider-toolbar"
      >
        <button
          className="btn btn-primary"
          id="btn-model-provider-add"
          type="button"
          onClick={() => onEdit(null)}
        >
          <Icon name="add" />
          新建供应商
        </button>
        <button
          className="btn"
          id="btn-model-provider-refresh"
          type="button"
          onClick={() => providersQuery.refetch()}
        >
          <Icon name="refresh" />
          刷新
        </button>
        <span className="toolbar-sep" />
        <input
          className="input toolbar-search"
          id="model-provider-search"
          type="search"
          placeholder="搜索供应商、地址或模型..."
          aria-label="搜索模型供应商"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value.trim().toLowerCase());
            setPage(1);
          }}
        />
      </div>
      <div className="table-wrap execution-table-wrap management-list-wrap">
        <table className="table execution-table management-list-table model-provider-table">
          <thead>
            <tr>
              <th>供应商</th>
              <th>接口地址</th>
              <th>协议</th>
              <th>模型</th>
              <th>更新时间</th>
              <th className="management-list-actions-head">操作</th>
            </tr>
          </thead>
          <tbody id="model-provider-list-body">
            {!rows.length ? (
              <tr>
                <td colSpan="6">
                  <div className="execution-empty">
                    <strong>
                      {providers.length
                        ? "没有匹配的模型供应商"
                        : providersQuery.isPending
                          ? "正在加载模型供应商"
                          : "尚未添加模型供应商"}
                    </strong>
                  </div>
                </td>
              </tr>
            ) : (
              rows.map((provider) => (
                <tr key={provider.id}>
                  <td
                    className="management-list-primary"
                    title={providerName(provider)}
                  >
                    <button
                      className="execution-name-button"
                      type="button"
                      onClick={() => onEdit(provider.id)}
                    >
                      {providerName(provider)}
                    </button>
                    {provider.website_url && (
                      <a
                        className="model-provider-website"
                        href={provider.website_url}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        官网
                      </a>
                    )}
                  </td>
                  <td className="management-list-text">
                    <span
                      className="model-provider-url"
                      title={provider.base_url}
                    >
                      {provider.base_url}
                    </span>
                  </td>
                  <td>
                    <span
                      className={`model-provider-protocol is-${provider.protocol.toLowerCase()}`}
                    >
                      {protocolLabel(provider.protocol)}
                    </span>
                  </td>
                  <td>
                    <div className="model-provider-model-preview">
                      {(provider.models || []).slice(0, 2).map((model) => (
                        <span className="model-provider-mini-model" key={model}>
                          {model}
                        </span>
                      ))}
                      {(provider.models || []).length > 2 && (
                        <span className="model-provider-more">
                          +{provider.models.length - 2}
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="management-list-time">
                    {window.formatDateTime(provider.updated_at)}
                  </td>
                  <td className="management-list-actions-cell">
                    <div className="management-list-row-actions execution-row-actions">
                      <button
                        className="btn-icon"
                        type="button"
                        title="删除模型供应商"
                        aria-label="删除模型供应商"
                        onClick={() => confirmDelete(provider)}
                      >
                        <Icon name="trash" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <Pagination
        total={filtered.length}
        page={page}
        pageSize={pageSize}
        onPage={setPage}
        onSize={(n) => {
          setPageSize(n);
          setPage(1);
        }}
      />
      <ConfirmDialog
        open={Boolean(deleting)}
        title="删除模型供应商"
        confirmLabel="删除"
        danger
        busy={remove.isPending}
        onClose={() => setDeleting(null)}
        onConfirm={async () => {
          try {
            await remove.mutateAsync(deleting.id);
            return true;
          } catch {
            return false;
          }
        }}
      >
        <p>
          确定删除“<strong>{deleting ? providerName(deleting) : ""}</strong>
          ”吗？
        </p>
        <p className="execution-confirm-note">
          删除后无法恢复，已保存的工作流不会被修改。
        </p>
      </ConfirmDialog>
    </section>
  );
}

const emptyForm = {
  name: "",
  website_url: "",
  api_key: "",
  base_url: "",
  protocol: "OPENAI_COMPATIBLE",
  proxy_mode: "SYSTEM",
  proxy_url: "",
  proxy_username: "",
  proxy_password: "",
  verify_ssl: true,
};
function connectionPayload(form) {
  return {
    api_key: form.api_key,
    base_url: form.base_url.trim(),
    protocol: form.protocol,
    proxy_mode: form.proxy_mode,
    proxy_url:
      form.proxy_mode === "CUSTOM" ? form.proxy_url.trim() || null : null,
    proxy_username:
      form.proxy_mode === "CUSTOM" ? form.proxy_username.trim() || null : null,
    proxy_password:
      form.proxy_mode === "CUSTOM" ? form.proxy_password || null : null,
    verify_ssl: form.verify_ssl,
  };
}
function validate(form) {
  if (!form.api_key.trim()) return "API Key 不能为空";
  try {
    const parsed = new URL(form.base_url);
    if (!/^https?:$/.test(parsed.protocol)) throw new Error();
  } catch {
    return "BASE_URL 必须是有效的 HTTP 或 HTTPS 地址";
  }
  if (form.proxy_mode === "CUSTOM" && !form.proxy_url.trim())
    return "自定义代理模式必须填写代理 URL";
  return null;
}

function ModelConfigModal({ model, protocol, value, onSave, onClose }) {
  const [contextWindow, setContextWindow] = useState(
    value.context_window || "",
  );
  const [maxOutput, setMaxOutput] = useState(value.max_output_tokens || "");
  const [body, setBody] = useState(
    value.default_body && Object.keys(value.default_body).length
      ? JSON.stringify(value.default_body, null, 2)
      : "",
  );
  function save() {
    try {
      const parsed = JSON.parse(body || "{}");
      if (!parsed || Array.isArray(parsed) || typeof parsed !== "object")
        throw new Error("默认 Body 必须是 JSON 对象");
      const positive = (raw, label) => {
        if (!raw) return null;
        const n = Number(raw);
        if (!Number.isInteger(n) || n < 1)
          throw new Error(`${label}必须是大于 0 的整数`);
        return n;
      };
      onSave({
        context_window: positive(contextWindow, "上下文窗口"),
        max_output_tokens: positive(maxOutput, "最大输出 Token"),
        default_body: parsed,
      });
    } catch (error) {
      toast(
        error instanceof SyntaxError
          ? "默认 Body 不是合法 JSON"
          : error.message,
        "error",
      );
    }
  }
  return (
    <ModalDialog
      title={`模型配置 · ${model}`}
      className="model-provider-config-modal"
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-secondary" type="button" onClick={onClose}>
            <Icon name="close" />
            取消
          </button>
          <button
            className="btn btn-primary"
            id="model-config-save"
            type="button"
            onClick={save}
          >
            <Icon name="save" />
            保存
          </button>
        </>
      }
    >
      <div className="model-provider-config-body">
        <label className="model-provider-field">
          <span>
            上下文窗口 <small>仅元数据</small>
          </span>
          <input
            className="input"
            id="model-config-context-window"
            type="number"
            min="1"
            value={contextWindow}
            onChange={(e) => setContextWindow(e.target.value)}
          />
        </label>
        <label className="model-provider-field">
          <span>
            最大输出 Token <small>仅元数据</small>
          </span>
          <input
            className="input"
            id="model-config-max-output"
            type="number"
            min="1"
            value={maxOutput}
            onChange={(e) => setMaxOutput(e.target.value)}
          />
        </label>
        <div className="model-provider-field model-provider-config-json">
          <div className="model-provider-config-json-header">
            <span>
              默认 Body JSON <small>运行时可被节点高级参数覆盖</small>
            </span>
            <button
              className="model-provider-json-beautify"
              id="model-config-default-body-beautify"
              type="button"
              aria-label="格式化默认 Body JSON"
              onClick={() => {
                try {
                  setBody(JSON.stringify(JSON.parse(body), null, 2));
                } catch {
                  toast("默认 Body 不是合法 JSON", "error");
                }
              }}
            >
              <Icon name="braces" />
              格式化
            </button>
          </div>
          <textarea
            className="input"
            id="model-config-default-body"
            spellCheck="false"
            placeholder={JSON.stringify(BODY_REFERENCES[protocol], null, 2)}
            value={body}
            onChange={(e) => setBody(e.target.value)}
          />
        </div>
      </div>
    </ModalDialog>
  );
}

function ProviderEditor({ providerId, onBack }) {
  const client = useQueryClient();
  const detail = useQuery({
    queryKey: ["model-provider", providerId],
    queryFn: () => getModelProvider(providerId),
    enabled: Boolean(providerId),
  });
  const [form, setForm] = useState(emptyForm);
  const [persistedProtocol, setPersistedProtocol] =
    useState("OPENAI_COMPATIBLE");
  const [selected, setSelected] = useState([]);
  const [configs, setConfigs] = useState({});
  const [tests, setTests] = useState({});
  const [discovered, setDiscovered] = useState([]);
  const [chooser, setChooser] = useState(false);
  const [manual, setManual] = useState("");
  const [discoveredValue, setDiscoveredValue] = useState("");
  const [status, setStatus] = useState({
    state: "",
    title: "等待测试",
    latency: "--",
  });
  const [configModel, setConfigModel] = useState(null);
  const [protocolConfirm, setProtocolConfirm] = useState(null);
  const [keyVisible, setKeyVisible] = useState(false);
  useEffect(() => {
    if (!providerId) {
      setForm(emptyForm);
      return;
    }
    if (detail.data) {
      const p = detail.data;
      setForm({
        ...emptyForm,
        ...p,
        name: p.name || "",
        website_url: p.website_url || "",
        proxy_url: p.proxy_url || "",
        proxy_username: p.proxy_username || "",
        proxy_password: p.proxy_password || "",
      });
      setPersistedProtocol(p.protocol);
      setSelected([...(p.models || [])]);
      setConfigs(structuredClone(p.model_configs || {}));
    }
  }, [providerId, detail.data]);
  const saveMutation = useMutation({
    mutationFn: (body) => saveModelProvider(providerId, body),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["model-providers"] });
      toast(providerId ? "模型供应商已更新" : "模型供应商已创建", "success");
      onBack();
    },
    onError: (e) => toast(`保存模型供应商失败: ${e.message}`, "error"),
  });
  const latencyMutation = useMutation({
    mutationFn: () => testProviderLatency(connectionPayload(form)),
    onMutate: () =>
      setStatus({ state: "idle", title: "正在访问接口地址", latency: "--" }),
    onSuccess: (r) => {
      setStatus({
        state: "success",
        title: `可达 · HTTP ${r.status_code}`,
        latency: `${r.latency_ms} ms`,
      });
      toast(`测速完成：${r.latency_ms} ms`, "success");
    },
    onError: (e) => {
      setStatus({ state: "error", title: "连接失败", latency: "--" });
      toast(e.message, "error");
    },
  });
  const modelsMutation = useMutation({
    mutationFn: () => fetchProviderModels(connectionPayload(form)),
    onMutate: () =>
      setStatus({ state: "idle", title: "正在探测模型协议", latency: "--" }),
    onSuccess: (r) => {
      setDiscovered(r.models || []);
      setStatus({
        state: "success",
        title: "模型列表已获取",
        latency: `${r.latency_ms} ms`,
      });
      toast(`已获取 ${(r.models || []).length} 个模型`, "success");
    },
    onError: (e) => {
      setDiscovered([]);
      setStatus({ state: "error", title: "可手工添加模型", latency: "--" });
      toast(e.message, "error");
    },
  });
  function set(name, value) {
    setForm((old) => ({ ...old, [name]: value }));
  }
  function valid() {
    const error = validate(form);
    if (error) {
      toast(error, "error");
      return false;
    }
    return true;
  }
  function addModel() {
    const model = (manual || discoveredValue).trim();
    if (!model) return toast("请选择或输入模型名称", "error");
    if (selected.includes(model)) return toast("该模型已经添加", "error");
    setSelected((old) => [...old, model]);
    setManual("");
    setDiscoveredValue("");
    toast(`已添加模型 ${model}`, "success");
  }
  async function testModel(model) {
    if (!valid()) return;
    try {
      const result = await testProviderModel({
        ...connectionPayload(form),
        model_name: model,
        default_body: configs[model]?.default_body || {},
      });
      setTests((old) => ({ ...old, [model]: result }));
      toast(
        `${model}${result.available ? " 可用" : " 不可用"}`,
        result.available ? "success" : "error",
      );
    } catch (e) {
      setTests((old) => ({
        ...old,
        [model]: { available: false, error: e.message },
      }));
      toast(`${model} 不可用 · ${e.message}`, "error");
    }
  }
  function save() {
    if (!valid()) return;
    if (!selected.length) return toast("至少添加一个模型", "error");
    const changed = Boolean(providerId) && form.protocol !== persistedProtocol;
    const body = {
      name: form.name.trim() || null,
      website_url: form.website_url.trim() || null,
      ...connectionPayload(form),
      model_endpoint: endpoint(form.protocol, form.base_url),
      models: [...selected],
      model_configs: changed ? {} : structuredClone(configs),
    };
    if (changed) {
      setProtocolConfirm(body);
    } else saveMutation.mutate(body);
  }
  if (providerId && detail.isPending)
    return <div className="loading">正在读取模型供应商…</div>;
  return (
    <section
      className="model-provider-editor"
      aria-labelledby="model-provider-editor-title"
    >
      <header className="model-provider-editor-header">
        <button
          className="btn btn-sm"
          id="model-provider-back"
          type="button"
          onClick={onBack}
        >
          <Icon name="back" />
          返回
        </button>
        <div className="model-provider-editor-heading">
          <h1 id="model-provider-editor-title">
            {providerId ? "编辑模型供应商" : "新建模型供应商"}
          </h1>
        </div>
        <button
          id="model-provider-save"
          type="button"
          className="btn btn-primary model-provider-header-save"
          disabled={saveMutation.isPending}
          onClick={save}
        >
          <Icon name="save" />
          保存
        </button>
      </header>
      <section
        className="model-provider-editor-section model-provider-connection-section"
        aria-labelledby="model-provider-connection-title"
      >
        <header className="model-provider-section-heading">
          <div>
            <h2 id="model-provider-connection-title">基础配置</h2>
            <span>凭证与网络设置</span>
          </div>
        </header>
        <form
          id="model-provider-form"
          className="model-provider-form"
          onSubmit={(e) => e.preventDefault()}
        >
          <label className="model-provider-field">
            <span>
              供应商名称 <small>选填</small>
            </span>
            <input
              className="input"
              id="model-provider-name"
              maxLength="120"
              value={form.name}
              onChange={(e) => set("name", e.target.value)}
            />
          </label>
          <label className="model-provider-field">
            <span>
              官网链接 <small>选填</small>
            </span>
            <input
              className="input"
              id="model-provider-website"
              type="url"
              value={form.website_url}
              onChange={(e) => set("website_url", e.target.value)}
            />
          </label>
          <label className="model-provider-field">
            <span>
              API Key <b>*</b>
            </span>
            <span className="model-provider-key-wrap">
              <input
                className="input"
                id="model-provider-api-key"
                type={keyVisible ? "text" : "password"}
                autoComplete="off"
                required
                value={form.api_key}
                onChange={(e) => set("api_key", e.target.value)}
              />
              <button
                id="model-provider-key-toggle"
                className="model-provider-key-toggle"
                type="button"
                aria-label={keyVisible ? "隐藏 API Key" : "显示 API Key"}
                onClick={() => setKeyVisible(!keyVisible)}
              >
                <Icon name={keyVisible ? "eye-off" : "eye"} />
              </button>
            </span>
          </label>
          <label className="model-provider-field">
            <span>
              接口地址 <b>*</b>
            </span>
            <input
              className="input"
              id="model-provider-base-url"
              type="url"
              required
              value={form.base_url}
              onChange={(e) => set("base_url", e.target.value)}
            />
          </label>
          <div className="model-provider-field model-provider-protocol-setting">
            <span>
              <label htmlFor="model-provider-protocol">
                协议 <b>*</b>
              </label>
              <details className="model-provider-proxy-help model-provider-protocol-help">
                <summary aria-label="查看协议选择帮助">?</summary>
                <div className="model-provider-proxy-help-panel" role="tooltip">
                  <strong>如何选择协议？</strong>
                  <section>
                    <b>OpenAI Chat Completions</b>
                    <span>多数 OpenAI 兼容服务使用。</span>
                  </section>
                  <section>
                    <b>OpenAI Responses API</b>
                    <span>仅在文档明确支持 /responses 时选择。</span>
                  </section>
                  <section>
                    <b>Anthropic Claude Messages</b>
                    <span>文档出现 /v1/messages 时选择。</span>
                  </section>
                </div>
              </details>
            </span>
            <select
              className="input"
              id="model-provider-protocol"
              value={form.protocol}
              onChange={(e) => {
                set("protocol", e.target.value);
                toast(
                  e.target.value === persistedProtocol
                    ? "已恢复原协议，当前模型配置将继续保留"
                    : "协议已切换，保存后将清空旧协议的模型配置和测试状态",
                  "success",
                );
              }}
            >
              <option value="OPENAI_COMPATIBLE">OpenAI Chat Completions</option>
              <option value="OPENAI_RESPONSES">OpenAI Responses API</option>
              <option value="ANTHROPIC">Anthropic Claude Messages</option>
            </select>
          </div>
          <div className="model-provider-field model-provider-proxy-setting">
            <span>
              代理模式 <b>*</b>
            </span>
            <div className="model-provider-proxy-control">
              <select
                className="input"
                id="model-provider-proxy-mode"
                value={form.proxy_mode}
                onChange={(e) => set("proxy_mode", e.target.value)}
              >
                <option value="SYSTEM">系统代理</option>
                <option value="DIRECT">直连</option>
                <option value="CUSTOM">自定义</option>
              </select>
              <label className="model-provider-switch model-provider-ssl-setting">
                <input
                  id="model-provider-verify-ssl"
                  type="checkbox"
                  role="switch"
                  checked={form.verify_ssl}
                  onChange={(e) => set("verify_ssl", e.target.checked)}
                />
                <span
                  className="model-provider-switch-track"
                  aria-hidden="true"
                />
                <span>SSL 证书校验</span>
              </label>
            </div>
          </div>
          {form.proxy_mode === "CUSTOM" && (
            <section
              className="model-provider-proxy-fields"
              id="model-provider-proxy-fields"
            >
              <label className="model-provider-field">
                <span>
                  代理地址 <b>*</b>
                </span>
                <input
                  className="input"
                  id="model-provider-proxy-url"
                  value={form.proxy_url}
                  onChange={(e) => set("proxy_url", e.target.value)}
                />
              </label>
              <label className="model-provider-field">
                <span>
                  代理用户名 <small>选填</small>
                </span>
                <input
                  className="input"
                  id="model-provider-proxy-username"
                  value={form.proxy_username}
                  onChange={(e) => set("proxy_username", e.target.value)}
                />
              </label>
              <label className="model-provider-field">
                <span>
                  代理密码 <small>选填</small>
                </span>
                <input
                  className="input"
                  id="model-provider-proxy-password"
                  type="password"
                  value={form.proxy_password}
                  onChange={(e) => set("proxy_password", e.target.value)}
                />
              </label>
            </section>
          )}
        </form>
      </section>
      <section className="model-provider-editor-section model-provider-validation-section">
        <header className="model-provider-section-heading">
          <h2>连接验证</h2>
          <div className="model-provider-actions">
            <button
              id="model-provider-latency"
              type="button"
              className={`btn ${latencyMutation.isPending ? "is-busy" : ""}`}
              disabled={latencyMutation.isPending}
              onClick={() => valid() && latencyMutation.mutate()}
            >
              <Icon name={latencyMutation.isPending ? "refresh" : "gauge"} />
              {latencyMutation.isPending ? "测速中" : "测速"}
            </button>
            <button
              id="model-provider-fetch"
              type="button"
              className={`btn btn-primary ${modelsMutation.isPending ? "is-busy" : ""}`}
              disabled={modelsMutation.isPending}
              onClick={() => valid() && modelsMutation.mutate()}
            >
              <Icon name="refresh" />
              {modelsMutation.isPending ? "获取中" : "获取模型"}
            </button>
            <button
              id="model-provider-add-model"
              type="button"
              className="btn"
              onClick={() => setChooser(!chooser)}
            >
              <Icon name="add" />
              添加模型
            </button>
          </div>
        </header>
        <section
          className="model-provider-status"
          data-state={status.state}
          aria-label="连接状态"
        >
          <div className="model-provider-status-main">
            <span className="model-provider-status-mark" />
            <div>
              <span>连接状态</span>
              <strong>{status.title}</strong>
            </div>
          </div>
          <div className="model-provider-metric">
            <span>访问延迟</span>
            <strong>{status.latency}</strong>
          </div>
          <div className="model-provider-metric model-provider-metric-wide">
            <span>推理端点</span>
            <small>
              {endpoint(form.protocol, form.base_url) || "请填写接口地址"}
            </small>
          </div>
          <div className="model-provider-metric">
            <span>发现模型</span>
            <strong>{discovered.length}</strong>
          </div>
        </section>
      </section>
      <section className="model-provider-editor-section model-provider-models-section">
        <section
          id="model-provider-chooser"
          className={`model-provider-chooser ${chooser ? "" : "is-hidden"}`}
        >
          <label>
            <span>已发现模型</span>
            <select
              className="input"
              id="model-provider-discovered"
              disabled={!discovered.length}
              value={discoveredValue}
              onChange={(e) => setDiscoveredValue(e.target.value)}
            >
              <option value="">
                {discovered.length ? "选择一个模型" : "暂无可选模型"}
              </option>
              {discovered.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.owned_by ? `${m.id} · ${m.owned_by}` : m.id}
                </option>
              ))}
            </select>
          </label>
          <span className="model-provider-chooser-or">或</span>
          <label>
            <span>手工模型名称</span>
            <input
              className="input"
              id="model-provider-manual"
              value={manual}
              onChange={(e) => setManual(e.target.value)}
            />
          </label>
          <button
            id="model-provider-confirm-model"
            type="button"
            className="btn btn-primary"
            onClick={addModel}
          >
            <Icon name="add" />
            确认添加
          </button>
        </section>
        <section className="model-provider-selected">
          <header>
            <h2>已添加模型</h2>
            <span>{selected.length} 个</span>
          </header>
          <div id="model-provider-selected-list">
            {!selected.length ? (
              <div className="model-provider-empty">暂无已添加模型</div>
            ) : (
              selected.map((model) => {
                const config = configs[model] || {};
                const test = tests[model];
                const metadata =
                  [
                    config.context_window && `上下文 ${config.context_window}`,
                    config.max_output_tokens &&
                      `最大输出 ${config.max_output_tokens}`,
                  ]
                    .filter(Boolean)
                    .join(" · ") || protocolLabel(form.protocol);
                return (
                  <div className="model-provider-selected-row" key={model}>
                    <span className="model-provider-model-mark">M</span>
                    <strong>{model}</strong>
                    <span>{metadata}</span>
                    <button
                      className={`model-provider-test-button ${test ? (test.available ? "is-success" : "is-error") : ""}`}
                      type="button"
                      aria-label={`测试 ${model}`}
                      onClick={() => testModel(model)}
                    >
                      <Icon name="play" />
                    </button>
                    <button
                      className="model-provider-config-button"
                      type="button"
                      aria-label={`配置 ${model}`}
                      onClick={() => setConfigModel(model)}
                    >
                      <Icon name="settings" />
                    </button>
                    <button
                      className="model-provider-remove-button"
                      type="button"
                      aria-label={`移除 ${model}`}
                      onClick={() => {
                        setSelected((old) => old.filter((x) => x !== model));
                        setConfigs((old) => {
                          const next = { ...old };
                          delete next[model];
                          return next;
                        });
                      }}
                    >
                      <Icon name="trash" />
                    </button>
                  </div>
                );
              })
            )}
          </div>
        </section>
      </section>
      {configModel && (
        <ModelConfigModal
          model={configModel}
          protocol={form.protocol}
          value={configs[configModel] || {}}
          onClose={() => setConfigModel(null)}
          onSave={(value) => {
            setConfigs((old) => ({ ...old, [configModel]: value }));
            setConfigModel(null);
            toast("模型配置已更新，保存供应商后生效", "success");
          }}
        />
      )}
      <ConfirmDialog
        open={Boolean(protocolConfirm)}
        title="保存协议变更"
        confirmLabel="确认保存"
        busy={saveMutation.isPending}
        onClose={() => setProtocolConfirm(null)}
        onConfirm={async () => {
          try {
            await saveMutation.mutateAsync(protocolConfirm);
            return true;
          } catch {
            return false;
          }
        }}
      >
        <p>
          保存后，模型默认 Body 和测试状态将被清空，推理端点会按新协议更新。
        </p>
        <p className="execution-confirm-note">
          供应商名称、地址和鉴权信息会保留。
        </p>
      </ConfirmDialog>
    </section>
  );
}

function App() {
  const [editing, setEditing] = useState(undefined);
  return editing === undefined ? (
    <ProviderList onEdit={setEditing} />
  ) : (
    <ProviderEditor providerId={editing} onBack={() => setEditing(undefined)} />
  );
}
let root = null;
function mount() {
  window.currentView = "model-providers";
  if (root) {
    root.unmount();
    root = null;
  }
  window.contentArea.innerHTML = '<div id="model-provider-app-root"></div>';
  root = createRoot(document.getElementById("model-provider-app-root"));
  root.render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  );
}
function unmount() {
  if (root) {
    root.unmount();
    root = null;
  }
}
window.ModelProviderManagement = { mount, unmount };
window.viewModelProviders = mount;
