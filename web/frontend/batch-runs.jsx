import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  QueryClient,
  QueryClientProvider,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";

import {
  cancelBatch,
  deleteBatch,
  getBatch,
  getBatchCopyName,
  listBatchHistory,
  listBatches,
  loadBatchResources,
  previewBatch,
  saveBatch,
  saveBatchSchedule,
  startBatch,
} from "./batch-api";
import { ConfirmDialog, ModalDialog } from "./components/dialog";
import { Pagination } from "./components/pagination";

const toast = window.showToast;
const client = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 3000 } },
});
const scheduleDefaults = {
  enabled: true,
  cadence: "DAILY",
  run_at: "",
  run_time: "09:00",
  weekdays: ["1", "2", "3", "4", "5"],
  month_day: 1,
  timezone: "Asia/Shanghai",
  overlap_policy: "SKIP",
};
const types = [
  "string",
  "number",
  "integer",
  "boolean",
  "object",
  "array",
  "null",
];
const operators = [
  ["EQ", "等于"],
  ["NE", "不等于"],
  ["CONTAINS", "包含"],
  ["REGEX", "正则"],
  ["EXISTS", "存在"],
  ["NOT_EMPTY", "不为空"],
  ["GT", "大于"],
  ["GTE", "大于等于"],
  ["LT", "小于"],
  ["LTE", "小于等于"],
  ["JSON_EQUAL", "JSON 相等"],
];
const batchConfigSchema = z.object({
  name: z
    .string()
    .trim()
    .min(1, "请输入任务名称")
    .max(200, "任务名称不能超过 200 个字符"),
  test_set_id: z.string().min(1, "请选择测试集"),
  workflow_id: z.string().min(1, "请选择工作流"),
  case_concurrency: z
    .number("并发数必须是数字")
    .int("并发数必须是整数")
    .min(1, "并发数不能小于 1")
    .max(32, "并发数不能大于 32"),
  failure_retry_count: z
    .number("失败重试必须是数字")
    .int("失败重试必须是整数")
    .min(0, "失败重试不能小于 0")
    .max(10, "失败重试不能大于 10"),
  call_order: z.enum(["SEQUENTIAL", "REVERSE", "RANDOM"]),
  case_display_column: z.string(),
  rule_display_column: z.string(),
});
function Icon({ name }) {
  return (
    <span
      aria-hidden="true"
      dangerouslySetInnerHTML={{ __html: window.icon(name) }}
    />
  );
}
function active(batch) {
  return ["RUNNING", "STOPPING"].includes(batch.status);
}

function batchPollingInterval(batches) {
  const activeBatches = (batches || []).filter(active);
  if (!activeBatches.length) return false;
  const oldestStartedAt = Math.min(
    ...activeBatches.map((batch) => {
      const timestamp = Date.parse(batch.started_at || "");
      return Number.isFinite(timestamp) ? timestamp : Date.now();
    }),
  );
  const runningFor = Date.now() - oldestStartedAt;
  if (runningFor < 30_000) return 1_000;
  if (runningFor < 180_000) return 2_500;
  return 5_000;
}
function editable(batch) {
  const c = batch.configuration || {},
    d = batch.input?.display_columns || {};
  return {
    name: c.name || batch.name || "",
    test_set_id: c.test_set_id || batch.input?.test_set_id || "",
    workflow_id: c.workflow_id || batch.workflow?.id || "",
    variables: c.variables || batch.variables || [],
    evaluation_rules: c.evaluation_rules || batch.evaluation_rules || [],
    case_concurrency: c.case_concurrency || batch.case_concurrency || 1,
    failure_retry_count:
      c.failure_retry_count ?? batch.failure_retry_count ?? 0,
    call_order: c.call_order || batch.input?.call_order?.mode || "SEQUENTIAL",
    case_display_column: c.case_display_column || d.case || "",
    rule_display_column: c.rule_display_column ?? d.rule ?? "",
  };
}
function Progress({ batch }) {
  const s = batch.summary || {},
    done = (+s.success || 0) + (+s.failed || 0),
    total = +batch.total_cases || 0,
    p = total ? Math.round((done * 100) / total) : 0;
  return (
    <div className={`batch-progress ${active(batch) ? "is-active" : ""}`}>
      <div>
        <span style={{ width: `${p}%` }} />
      </div>
      <small>
        {done} / {total}
      </small>
    </div>
  );
}
function Rate({ batch }) {
  const s = batch.summary || {},
    pass = +s.success || 0,
    executed = pass + (+s.failed || 0);
  if (!executed) return <span className="batch-pass-rate is-empty">—</span>;
  const rate = (pass * 100) / executed,
    tone = rate > 90 ? "good" : rate >= 60 ? "warning" : "bad";
  return (
    <span className={`batch-pass-rate is-${tone}`}>
      {Math.round(rate * 10) / 10}%
    </span>
  );
}
function Modal({ className = "", ...props }) {
  return (
    <ModalDialog {...props} className={`execution-modal ${className}`.trim()} />
  );
}

function HistoryModal({ batch, onClose }) {
  const history = useQuery({
    queryKey: ["batch-history", batch.id],
    queryFn: () => listBatchHistory(batch.id),
  });
  const rows = history.data || [];
  return (
    <Modal
      title={`${batch.name} · 执行历史`}
      className="is-batch-history"
      onClose={onClose}
    >
      {history.isPending ? (
        <div className="loading">正在读取执行历史…</div>
      ) : history.error ? (
        <div className="batch-history-empty" role="alert">
          <strong>执行历史加载失败</strong>
          <span>{history.error.message}</span>
          <button
            className="btn btn-sm"
            type="button"
            onClick={() => history.refetch()}
          >
            重新加载
          </button>
        </div>
      ) : !rows.length ? (
        <div className="batch-history-empty">
          <strong>暂无执行历史</strong>
          <span>任务完整执行或停止后，这里会保留最近 10 次记录。</span>
        </div>
      ) : (
        <>
          <div className="batch-history-intro">
            <strong>最近 {rows.length} 次完整执行</strong>
            <span>手动执行单条用例不会单独生成历史。</span>
          </div>
          <div className="table-wrap batch-history-table-wrap">
            <table className="table execution-table batch-history-table">
              <thead>
                <tr>
                  <th>测试集</th>
                  <th>工作流</th>
                  <th>执行进度</th>
                  <th>通过率</th>
                  <th>启动时间</th>
                  <th>结束时间</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((item, index) => {
                  const summary = {
                    success: item.passed_cases,
                    failed: Math.max(
                      0,
                      item.executed_cases - item.passed_cases,
                    ),
                  };
                  const historyBatch = {
                    total_cases: item.total_cases,
                    summary,
                  };
                  return (
                    <tr key={`${item.started_at || "history"}-${index}`}>
                      <td className="batch-table-text">{item.test_set_name}</td>
                      <td className="batch-table-text">{item.workflow_name}</td>
                      <td>
                        <Progress batch={historyBatch} />
                      </td>
                      <td>
                        <Rate batch={historyBatch} />
                      </td>
                      <td className="batch-time-cell">
                        {window.formatDateTime(item.started_at) || "—"}
                      </td>
                      <td className="batch-time-cell">
                        {window.formatDateTime(item.finished_at) || "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Modal>
  );
}
function VariableRows({ rows, setRows, headers }) {
  function change(i, key, value) {
    setRows(
      rows.map((r, n) =>
        n === i
          ? { ...r, [key]: value, ...(key === "source" ? { value: "" } : {}) }
          : r,
      ),
    );
  }
  return (
    <div className="batch-variable-table" id="batch-variables">
      {!rows.length ? (
        <div className="batch-variable-empty">尚未配置变量</div>
      ) : (
        <>
          <div className="batch-variable-head">
            <span>#</span>
            <span>来源</span>
            <span>Key</span>
            <span>Value</span>
            <span>类型</span>
            <span />
          </div>
          {rows.map((r, i) => (
            <div className="batch-variable-row" key={i}>
              <span>{i + 1}</span>
              <select
                className="input"
                data-variable-source
                aria-label={`变量 ${i + 1} 来源`}
                value={r.source}
                onChange={(e) => change(i, "source", e.target.value)}
              >
                <option value="TEST_SET">测试集字段</option>
                <option value="CUSTOM">自定义</option>
              </select>
              <input
                className="input"
                data-variable-key
                aria-label={`变量 ${i + 1} Key`}
                value={r.key}
                onChange={(e) => change(i, "key", e.target.value)}
                placeholder="例如 question"
              />
              {r.source === "TEST_SET" ? (
                <select
                  className="input"
                  data-variable-value
                  aria-label={`变量 ${i + 1} 测试集字段`}
                  value={r.value}
                  onChange={(e) => change(i, "value", e.target.value)}
                >
                  {headers.map((h) => (
                    <option key={h}>{h}</option>
                  ))}
                </select>
              ) : (
                <input
                  className="input"
                  data-variable-value
                  aria-label={`变量 ${i + 1} 自定义值`}
                  value={r.value}
                  disabled={r.type === "null"}
                  onChange={(e) => change(i, "value", e.target.value)}
                />
              )}
              <select
                className="input"
                data-variable-type
                aria-label={`变量 ${i + 1} 类型`}
                value={r.type}
                onChange={(e) => change(i, "type", e.target.value)}
              >
                {types.map((t) => (
                  <option key={t}>{t}</option>
                ))}
              </select>
              <button
                className="btn-icon"
                type="button"
                aria-label="删除变量"
                onClick={() => setRows(rows.filter((_, n) => n !== i))}
              >
                <Icon name="trash" />
              </button>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
function RuleRows({ rows, setRows }) {
  function change(i, key, value) {
    setRows(rows.map((r, n) => (n === i ? { ...r, [key]: value } : r)));
  }
  return (
    <div className="batch-evaluation-table" id="batch-evaluation-rules">
      {!rows.length ? (
        <div className="batch-evaluation-empty">暂无校验规则</div>
      ) : (
        <>
          <div className="batch-evaluation-head">
            <span>#</span>
            <span>校验项</span>
            <span>路径</span>
            <span>运算符</span>
            <span>预期值</span>
            <span>类型</span>
            <span />
          </div>
          {rows.map((r, i) => (
            <div className="batch-evaluation-rule" key={i}>
              <span>{i + 1}</span>
              <input
                className="input"
                aria-label={`校验规则 ${i + 1} 名称`}
                value={r.name || ""}
                onChange={(e) => change(i, "name", e.target.value)}
                placeholder="选填"
              />
              <input
                className="input"
                data-rule-result-path
                aria-label={`校验规则 ${i + 1} 结果路径`}
                value={String(r.result_path || "").replace(/^context\./, "")}
                onChange={(e) => change(i, "result_path", e.target.value)}
                placeholder="例如 action_match"
              />
              <select
                className="input"
                aria-label={`校验规则 ${i + 1} 运算符`}
                value={r.operator}
                onChange={(e) => change(i, "operator", e.target.value)}
              >
                {operators.map(([v, l]) => (
                  <option value={v} key={v}>
                    {l}
                  </option>
                ))}
              </select>
              <input
                className="input"
                aria-label={`校验规则 ${i + 1} 预期值`}
                value={r.operator === "NOT_EMPTY" ? "" : r.expected_value || ""}
                disabled={r.operator === "NOT_EMPTY"}
                onChange={(e) => change(i, "expected_value", e.target.value)}
              />
              <select
                className="input"
                aria-label={`校验规则 ${i + 1} 类型`}
                value={r.type || "string"}
                disabled={r.operator === "NOT_EMPTY"}
                onChange={(e) => change(i, "type", e.target.value)}
              >
                {types.map((t) => (
                  <option key={t}>{t}</option>
                ))}
              </select>
              <button
                className="btn-icon"
                type="button"
                aria-label={`删除校验规则 ${i + 1}`}
                onClick={() => setRows(rows.filter((_, n) => n !== i))}
              >
                <Icon name="trash" />
              </button>
            </div>
          ))}
        </>
      )}
    </div>
  );
}

function ConfigModal({ mode, batch, onClose, onSaved }) {
  const original = batch ? editable(batch) : null;
  const {
    register,
    watch,
    setValue,
    handleSubmit,
    formState: { errors },
  } = useForm({
    resolver: zodResolver(batchConfigSchema),
    defaultValues: original || {
      name: "",
      test_set_id: "",
      workflow_id: "",
      case_concurrency: 4,
      failure_retry_count: 0,
      call_order: "SEQUENTIAL",
      case_display_column: "",
      rule_display_column: "",
    },
  });
  const form = watch();
  const [variables, setVariables] = useState(original?.variables || []),
    [rules, setRules] = useState(original?.evaluation_rules || []);
  const resources = useQuery({
    queryKey: ["batch-resources"],
    queryFn: loadBatchResources,
  });
  const preview = useQuery({
    queryKey: ["batch-preview", form.test_set_id],
    queryFn: () => previewBatch(form.test_set_id),
    enabled: Boolean(form.test_set_id),
  });
  useEffect(() => {
    if (!form.test_set_id && resources.data?.sets?.length)
      setValue("test_set_id", resources.data.sets[0].id);
    if (!form.workflow_id && resources.data?.flows?.length)
      setValue(
        "workflow_id",
        resources.data.flows[0].workflow?.id || resources.data.flows[0].id,
      );
  }, [resources.data, form.test_set_id, form.workflow_id, setValue]);
  useEffect(() => {
    const h = preview.data?.headers || [];
    if (!original && h.length && !variables.length)
      setVariables([
        { source: "TEST_SET", key: h[0], value: h[0], type: "string" },
      ]);
    if (h.length && !form.case_display_column)
      setValue("case_display_column", h[0]);
  }, [
    preview.data,
    form.case_display_column,
    original,
    setValue,
    variables.length,
  ]);
  const save = useMutation({
    mutationFn: (body) => saveBatch(mode === "edit" ? batch.id : null, body),
    onSuccess: () => {
      toast(
        mode === "edit" ? "任务已保存，下次执行时生效" : "任务已创建",
        "success",
      );
      onSaved();
    },
    onError: (e) => toast(e.message, "error"),
  });
  const submit = handleSubmit(
    (validatedForm) => {
      try {
        if (!variables.length) throw new Error("请至少配置一个变量注入");
        const vars = variables.map((r, i) => {
          if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(r.key.trim()))
            throw new Error(`变量 ${i + 1} 的 Key 格式无效`);
          if (!r.value && r.type !== "null")
            throw new Error(`变量 ${i + 1} 的 Value 不能为空`);
          return {
            source: r.source,
            key: r.key.trim(),
            value: r.type === "null" ? "null" : r.value,
            type: r.type,
          };
        });
        const evaluation_rules = rules.map((r, i) => {
          if (!String(r.result_path || "").trim())
            throw new Error(`校验规则 ${i + 1} 的路径不能为空`);
          return {
            name: String(r.name || "").trim(),
            result_path: r.result_path.trim(),
            operator: r.operator,
            expected_value:
              r.operator === "NOT_EMPTY"
                ? ""
                : r.type === "null"
                  ? "null"
                  : r.expected_value,
            type: r.operator === "NOT_EMPTY" ? "string" : r.type,
          };
        });
        save.mutate({
          ...validatedForm,
          description: "",
          variables: vars,
          evaluation_rules,
        });
      } catch (e) {
        toast(e.message, "error");
      }
    },
    () => {},
  );
  const headers = preview.data?.headers || [];
  return (
    <Modal
      title={
        mode === "edit" ? "编辑任务" : mode === "copy" ? "拷贝任务" : "新建任务"
      }
      className="is-batch-config"
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>
            取消
          </button>
          <button
            className="btn btn-primary"
            disabled={
              save.isPending || resources.isPending || preview.isPending
            }
            onClick={submit}
          >
            保存
          </button>
        </>
      }
    >
      <section className="batch-config-card" aria-label="基础配置">
        <div className="batch-create-grid">
          <label>
            <span>任务名称</span>
            <input
              className="input"
              id="batch-name"
              aria-invalid={Boolean(errors.name)}
              aria-describedby={errors.name ? "batch-name-error" : undefined}
              {...register("name")}
            />
            {errors.name ? (
              <small
                className="batch-field-error"
                id="batch-name-error"
                role="alert"
              >
                {errors.name.message}
              </small>
            ) : null}
          </label>
          <label>
            <span>失败重试</span>
            <input
              className="input"
              id="batch-failure-retry-count"
              type="number"
              min="0"
              max="10"
              aria-invalid={Boolean(errors.failure_retry_count)}
              aria-describedby={
                errors.failure_retry_count
                  ? "batch-failure-retry-count-error"
                  : undefined
              }
              {...register("failure_retry_count", { valueAsNumber: true })}
            />
            {errors.failure_retry_count ? (
              <small
                className="batch-field-error"
                id="batch-failure-retry-count-error"
                role="alert"
              >
                {errors.failure_retry_count.message}
              </small>
            ) : null}
          </label>
          <label>
            <span>测试集</span>
            <select
              className="input"
              id="batch-test-set"
              aria-invalid={Boolean(errors.test_set_id)}
              aria-describedby={
                errors.test_set_id ? "batch-test-set-error" : undefined
              }
              {...register("test_set_id", {
                onChange: () => {
                  setValue("case_display_column", "");
                  setValue("rule_display_column", "");
                  setVariables([]);
                },
              })}
            >
              {(resources.data?.sets || []).map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
            {errors.test_set_id ? (
              <small
                className="batch-field-error"
                id="batch-test-set-error"
                role="alert"
              >
                {errors.test_set_id.message}
              </small>
            ) : null}
          </label>
          <label>
            <span>工作流</span>
            <select
              className="input"
              id="batch-workflow"
              aria-invalid={Boolean(errors.workflow_id)}
              aria-describedby={
                errors.workflow_id ? "batch-workflow-error" : undefined
              }
              {...register("workflow_id")}
            >
              {(resources.data?.flows || []).map((w) => {
                const x = w.workflow || w;
                return (
                  <option key={x.id} value={x.id}>
                    {x.name}
                  </option>
                );
              })}
            </select>
            {errors.workflow_id ? (
              <small
                className="batch-field-error"
                id="batch-workflow-error"
                role="alert"
              >
                {errors.workflow_id.message}
              </small>
            ) : null}
          </label>
          <label>
            <span>用例显示列</span>
            <select
              className="input"
              id="batch-case-display-column"
              {...register("case_display_column")}
            >
              {headers.map((h) => (
                <option key={h}>{h}</option>
              ))}
            </select>
          </label>
          <label>
            <span>规则显示列</span>
            <select
              className="input"
              id="batch-rule-display-column"
              {...register("rule_display_column")}
            >
              <option value="">不选择</option>
              {headers.map((h) => (
                <option key={h}>{h}</option>
              ))}
            </select>
          </label>
          <label>
            <span>执行顺序</span>
            <select
              className="input"
              id="batch-call-order"
              {...register("call_order")}
            >
              <option value="SEQUENTIAL">顺序</option>
              <option value="REVERSE">逆序</option>
              <option value="RANDOM">随机</option>
            </select>
          </label>
          <label>
            <span>并发数</span>
            <input
              className="input"
              id="batch-concurrency"
              type="number"
              min="1"
              max="32"
              aria-invalid={Boolean(errors.case_concurrency)}
              aria-describedby={
                errors.case_concurrency ? "batch-concurrency-error" : undefined
              }
              {...register("case_concurrency", { valueAsNumber: true })}
            />
            {errors.case_concurrency ? (
              <small
                className="batch-field-error"
                id="batch-concurrency-error"
                role="alert"
              >
                {errors.case_concurrency.message}
              </small>
            ) : null}
          </label>
        </div>
      </section>
      <section className="batch-variable-injection">
        <header>
          <div className="batch-section-heading">
            <strong>变量注入</strong>
            <span>注入到工作流 Context</span>
          </div>
          <button
            className="btn btn-sm"
            id="batch-variable-add"
            onClick={() =>
              setVariables([
                {
                  source: "TEST_SET",
                  key: "",
                  value: headers[0] || "",
                  type: "string",
                },
                ...variables,
              ])
            }
          >
            <Icon name="add" />
            添加变量
          </button>
        </header>
        <VariableRows
          rows={variables}
          setRows={setVariables}
          headers={headers}
        />
      </section>
      <section className="batch-evaluation">
        <header>
          <div className="batch-section-heading">
            <strong>结果校验</strong>
            <span>从工作流 Context 中获取变量</span>
          </div>
          <button
            className="btn btn-sm"
            id="batch-rule-add"
            onClick={() =>
              setRules([
                {
                  name: "",
                  result_path: "",
                  operator: "EQ",
                  expected_value: "",
                  type: "string",
                },
                ...rules,
              ])
            }
          >
            <Icon name="add" />
            添加规则
          </button>
        </header>
        <RuleRows rows={rules} setRows={setRules} />
      </section>
    </Modal>
  );
}

function ScheduleModal({ batch, onClose, onSaved }) {
  const [value, setValue] = useState({
    ...scheduleDefaults,
    ...batch.schedule,
    weekdays: [...(batch.schedule?.weekdays || scheduleDefaults.weekdays)],
  });
  const save = useMutation({
    mutationFn: () => {
      // 剥离后端返回的只读字段（batch_id/next_run_at/...），仅提交可写字段
      const {
        batch_id: _batchId,
        next_run_at: _nextRunAt,
        last_run_at: _lastRunAt,
        last_error: _lastError,
        created_at: _createdAt,
        updated_at: _updatedAt,
        ...body
      } = value;
      return saveBatchSchedule(batch.id, body);
    },
    onSuccess: () => {
      toast("定时任务设置已保存", "success");
      onSaved();
    },
    onError: (e) => toast(e.message, "error"),
  });
  const weekdays = [
    ["1", "一"],
    ["2", "二"],
    ["3", "三"],
    ["4", "四"],
    ["5", "五"],
    ["6", "六"],
    ["0", "日"],
  ];
  return (
    <Modal
      title="定时任务设置"
      className="is-batch-schedule"
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>
            取消
          </button>
          <button className="btn btn-primary" onClick={() => save.mutate()}>
            保存
          </button>
        </>
      }
    >
      <div className="batch-schedule-intro">
        <strong>{batch.name}</strong>
        <span>{value.enabled ? "定时任务已启用" : "定时任务已关闭"}</span>
      </div>
      <label className="batch-schedule-enabled">
        <input
          id="batch-schedule-enabled"
          type="checkbox"
          checked={value.enabled}
          onChange={(e) => setValue({ ...value, enabled: e.target.checked })}
        />
        <span>
          <strong>启用定时任务</strong>
        </span>
      </label>
      <fieldset disabled={!value.enabled}>
        <div className="batch-schedule-grid">
          <label>
            <span>调度方式</span>
            <select
              className="input"
              id="batch-schedule-cadence"
              value={value.cadence}
              onChange={(e) => setValue({ ...value, cadence: e.target.value })}
            >
              <option value="ONCE">仅执行一次</option>
              <option value="DAILY">每天</option>
              <option value="WEEKLY">每周</option>
              <option value="MONTHLY">每月</option>
            </select>
          </label>
          <label>
            <span>时区</span>
            <select
              className="input"
              value={value.timezone}
              onChange={(e) => setValue({ ...value, timezone: e.target.value })}
            >
              {[
                "Asia/Shanghai",
                "UTC",
                "Asia/Tokyo",
                "Europe/London",
                "America/Los_Angeles",
              ].map((x) => (
                <option key={x}>{x}</option>
              ))}
            </select>
          </label>
          {value.cadence === "ONCE" ? (
            <label>
              <span>执行时间</span>
              <input
                className="input"
                type="datetime-local"
                value={value.run_at}
                onChange={(e) => setValue({ ...value, run_at: e.target.value })}
              />
            </label>
          ) : (
            <label>
              <span>执行时间</span>
              <input
                className="input"
                type="time"
                value={value.run_time}
                onChange={(e) =>
                  setValue({ ...value, run_time: e.target.value })
                }
              />
            </label>
          )}
          {value.cadence === "WEEKLY" && (
            <div className="batch-schedule-weekdays">
              <span>执行星期</span>
              <div>
                {weekdays.map(([v, l]) => (
                  <label key={v}>
                    <input
                      type="checkbox"
                      value={v}
                      checked={value.weekdays.includes(v)}
                      onChange={(e) =>
                        setValue({
                          ...value,
                          weekdays: e.target.checked
                            ? [...value.weekdays, v]
                            : value.weekdays.filter((x) => x !== v),
                        })
                      }
                    />
                    <span>周{l}</span>
                  </label>
                ))}
              </div>
            </div>
          )}
          {value.cadence === "MONTHLY" && (
            <label>
              <span>每月日期</span>
              <input
                className="input"
                type="number"
                min="1"
                max="31"
                value={value.month_day}
                onChange={(e) =>
                  setValue({ ...value, month_day: +e.target.value })
                }
              />
            </label>
          )}
          <label>
            <span>任务重叠</span>
            <select
              className="input"
              disabled={value.cadence === "ONCE"}
              title={value.cadence === "ONCE" ? "仅执行一次时无重叠概念" : undefined}
              value={value.overlap_policy}
              onChange={(e) =>
                setValue({ ...value, overlap_policy: e.target.value })
              }
            >
              <option value="SKIP">跳过本次执行</option>
              <option value="QUEUE">等待上次任务结束</option>
            </select>
          </label>
        </div>
      </fieldset>
    </Modal>
  );
}

const BATCH_TERMINAL = new Set([
  "SUCCESS",
  "COMPLETED_WITH_ERRORS",
  "STOPPED",
  "INTERRUPTED",
]);

function requestNotificationPermission() {
  if (!("Notification" in window)) return;
  if (Notification.permission === "default") Notification.requestPermission();
}

function notifyBatch(batch) {
  if (!("Notification" in window)) return;
  if (Notification.permission !== "granted") return;
  const s = batch.summary || {},
    total = +batch.total_cases || 0,
    pass = +s.success || 0,
    fail = +s.failed || 0;
  let body;
  if (batch.status === "SUCCESS") {
    body = `任务 ${batch.name} 完成：${pass}/${total} PASS`;
  } else if (batch.status === "COMPLETED_WITH_ERRORS") {
    body = `任务 ${batch.name} 完成：${pass}/${total} PASS，${fail} FAIL`;
  } else if (batch.status === "STOPPED") {
    body = `任务 ${batch.name} 已停止`;
  } else {
    body = `任务 ${batch.name} 异常中断`;
  }
  try {
    const n = new Notification("EvalFlow", { body, tag: batch.id });
    n.onclick = () => {
      window.focus();
      n.close();
    };
  } catch (_) {
    /* 静默跳过 */
  }
}

function App() {
  const qc = useQueryClient(),
    [page, setPage] = useState(1),
    [size, setSize] = useState(10),
    [modal, setModal] = useState(null);
  const batches = useQuery({
    queryKey: ["batch-runs"],
    queryFn: listBatches,
    refetchInterval: (q) => batchPollingInterval(q.state.data),
  });
  useEffect(() => {
    if (batches.error) toast(`加载任务失败：${batches.error.message}`, "error");
  }, [batches.error]);
  const prevStatuses = React.useRef(new Map());
  useEffect(() => {
    const list = batches.data;
    if (!list || !list.length) return;
    const next = new Map();
    for (const b of list) {
      next.set(b.id, b.status);
      const prev = prevStatuses.current.get(b.id);
      if (prev && active({ status: prev }) && BATCH_TERMINAL.has(b.status)) {
        notifyBatch(b);
      }
    }
    prevStatuses.current = next;
  }, [batches.data]);
  const data = batches.data || [],
    rows = data.slice((page - 1) * size, page * size);
  const refresh = () => qc.invalidateQueries({ queryKey: ["batch-runs"] });
  const command = useMutation({
    mutationFn: ({ id, action, body }) => {
      if (action === "delete") return deleteBatch(id);
      if (action === "cancel") return cancelBatch(id);
      if (action === "start") return startBatch(id, body || { mode: "FULL" });
      throw new Error(`不支持的任务操作: ${action}`);
    },
    onMutate: ({ action }) => {
      if (action === "start") requestNotificationPermission();
    },
    onSuccess: refresh,
    onError: (e) => toast(e.message, "error"),
  });
  async function copy(batch) {
    try {
      const [name, detail] = await Promise.all([
        getBatchCopyName(batch.id),
        getBatch(batch.id),
      ]);
      const copyBatch = {
        ...detail,
        configuration: { ...editable(detail), name },
      };
      setModal({ type: "config", mode: "copy", batch: copyBatch });
    } catch (e) {
      toast(e.message, "error");
    }
  }
  function remove(batch) {
    setModal({ type: "delete", batch });
  }
  return (
    <section
      className="execution-page batch-page"
      aria-labelledby="batch-title"
    >
      <header className="execution-page-header management-page-header">
        <div className="management-page-title">
          <h1 id="batch-title">任务调度</h1>
          <span className="management-page-description">
            执行任务并追踪结果
          </span>
        </div>
        <span className="execution-count" id="batch-count">
          {data.length} 个任务
        </span>
      </header>
      <div className="toolbar execution-toolbar management-list-toolbar">
        <button
          className="btn btn-primary"
          id="btn-batch-add"
          onClick={() => setModal({ type: "config", mode: "create" })}
        >
          <Icon name="add" />
          新建任务
        </button>
        <button
          className="btn"
          id="btn-batch-refresh"
          onClick={() => batches.refetch()}
        >
          <Icon name="refresh" />
          刷新
        </button>
      </div>
      <div className="table-wrap execution-table-wrap management-list-wrap">
        <table className="table execution-table management-list-table batch-table">
          <thead>
            <tr>
              <th>任务</th>
              <th>测试集</th>
              <th>工作流</th>
              <th>执行进度</th>
              <th>通过率</th>
              <th>启动时间</th>
              <th>结束时间</th>
              <th className="management-list-actions-head batch-actions-head">
                操作
              </th>
            </tr>
          </thead>
          <tbody id="batch-list-body">
            {!rows.length ? (
              <tr>
                <td colSpan="8">
                  <div className="execution-empty">
                    <strong>
                      {batches.isPending ? "正在加载任务" : "尚未创建任务"}
                    </strong>
                  </div>
                </td>
              </tr>
            ) : (
              rows.map((batch) => (
                <tr key={batch.id}>
                  <td className="management-list-primary batch-table-primary">
                    <button
                      className="execution-name-button"
                      onClick={() => {
                        unmount();
                        window.viewBatchDetail(batch.id);
                      }}
                    >
                      {batch.name}
                    </button>
                  </td>
                  <td className="management-list-text batch-table-text">
                    {batch.input?.test_set_name}
                  </td>
                  <td className="management-list-text batch-table-text">
                    {batch.workflow?.name}
                  </td>
                  <td>
                    <Progress batch={batch} />
                  </td>
                  <td>
                    <Rate batch={batch} />
                  </td>
                  <td className="management-list-time batch-time-cell">
                    {window.formatDateTime(batch.started_at) || "—"}
                  </td>
                  <td className="management-list-time batch-time-cell">
                    {window.formatDateTime(batch.finished_at) || "—"}
                  </td>
                  <td className="management-list-actions-cell batch-actions-cell">
                    <div className="management-list-row-actions batch-row-actions">
                      {batch.status === "RUNNING" ? (
                        <button
                          className="btn-icon"
                          aria-label="停止任务"
                          onClick={() =>
                            command.mutate({ id: batch.id, action: "cancel" })
                          }
                        >
                          <Icon name="stop" />
                        </button>
                      ) : (
                        <button
                          className="btn-icon"
                          aria-label="启动任务"
                          onClick={() => setModal({ type: "start", batch })}
                        >
                          <Icon name="play" />
                        </button>
                      )}
                      <button
                        className="btn-icon"
                        aria-label="查看执行历史"
                        onClick={() => setModal({ type: "history", batch })}
                      >
                        <Icon name="history" />
                      </button>
                      <button
                        className="btn-icon"
                        aria-label="编辑任务"
                        onClick={() =>
                          setModal({ type: "config", mode: "edit", batch })
                        }
                      >
                        <Icon name="edit" />
                      </button>
                      <button
                        className={`btn-icon ${batch.schedule?.enabled ? "is-scheduled" : ""}`}
                        aria-label="定时任务设置"
                        onClick={() => setModal({ type: "schedule", batch })}
                      >
                        <Icon name="alarm-clock" />
                      </button>
                      <button
                        className="btn-icon"
                        aria-label="拷贝任务"
                        onClick={() => copy(batch)}
                      >
                        <Icon name="copy" />
                      </button>
                      <button
                        className="btn-icon"
                        disabled={active(batch)}
                        aria-label="删除任务"
                        onClick={() => remove(batch)}
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
        total={data.length}
        page={page}
        pageSize={size}
        onPage={setPage}
        onSize={setSize}
        id="batch-pagination"
        countLabel="个任务"
      />
      {modal?.type === "config" && (
        <ConfigModal
          mode={modal.mode}
          batch={modal.batch}
          onClose={() => setModal(null)}
          onSaved={() => {
            setModal(null);
            refresh();
          }}
        />
      )}
      {modal?.type === "schedule" && (
        <ScheduleModal
          batch={modal.batch}
          onClose={() => setModal(null)}
          onSaved={() => {
            setModal(null);
            refresh();
          }}
        />
      )}
      {modal?.type === "start" && (
        <StartModal
          batch={modal.batch}
          onClose={() => setModal(null)}
          onStart={(mode) =>
            command
              .mutateAsync({
                id: modal.batch.id,
                action: "start",
                body: { mode },
              })
              .then(() => {
                setModal(null);
                toast("任务已启动", "success");
              })
          }
        />
      )}
      {modal?.type === "history" && (
        <HistoryModal batch={modal.batch} onClose={() => setModal(null)} />
      )}
      {modal?.type === "delete" && (
        <ConfirmDialog
          open
          title="删除任务"
          confirmLabel="删除"
          danger
          busy={command.isPending}
          onClose={() => setModal(null)}
          onConfirm={async () => {
            try {
              await command.mutateAsync({
                id: modal.batch.id,
                action: "delete",
              });
              toast("任务已删除", "success");
              return true;
            } catch {
              return false;
            }
          }}
        >
          <p>
            确定删除“<strong>{modal.batch.name}</strong>”及其全部执行记录吗？
          </p>
          <p className="execution-confirm-note">删除后无法恢复。</p>
        </ConfirmDialog>
      )}
    </section>
  );
}
function StartModal({ batch, onClose, onStart }) {
  const [mode, setMode] = useState("FULL"),
    [busy, setBusy] = useState(false);
  return (
    <Modal
      title="选择执行方式"
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>
            取消
          </button>
          <button
            className="btn btn-primary"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await onStart(mode);
              } finally {
                setBusy(false);
              }
            }}
          >
            启动
          </button>
        </>
      }
    >
      <div className="batch-start-options" role="radiogroup">
        {[
          ["FULL", "全量执行"],
          ["RESUME", "断点续跑"],
          ["RETRY_FAILED", "失败重跑"],
        ].map(([v, l]) => (
          <label key={v}>
            <input
              type="radio"
              name="batch-start-mode"
              value={v}
              checked={mode === v}
              onChange={() => setMode(v)}
            />
            <span>
              <strong>{l}</strong>
            </span>
          </label>
        ))}
      </div>
    </Modal>
  );
}
let root = null;
function mount() {
  window.currentView = "batch-runs";
  unmount();
  window.contentArea.innerHTML = '<div id="batch-run-app-root"></div>';
  root = createRoot(document.getElementById("batch-run-app-root"));
  root.render(
    <QueryClientProvider client={client}>
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
window.BatchRunManagement = { mount, unmount };
window.viewBatchRuns = mount;
