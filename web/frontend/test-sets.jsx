import React, { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { ArrowLeft, ChevronLeft, ChevronRight, CircleCheck, Eraser, FileText, FileUp, Info, LayoutGrid, Pencil, Plus, RefreshCw, Save, Search, Settings2, Trash2, X } from "lucide-react";
import { Workbook } from "@fortune-sheet/react";
import * as XLSX from "xlsx";
import "@fortune-sheet/react/dist/index.css";
import "./test-sets.css";

const PAGE_SIZE = 20;
const CASE_PAGE_SIZE = 20;
const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];
let testSetListCache = null;

async function request(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: options.body ? { "Content-Type": "application/json", ...(options.headers || {}) } : options.headers,
  });
  const text = await response.text();
  let payload = null;
  if (text) {
    try { payload = JSON.parse(text); } catch (_error) { payload = null; }
  }
  if (!response.ok) {
    const detail = payload?.detail;
    throw new Error(typeof detail === "string" ? detail : text || response.statusText);
  }
  return payload;
}

function toast(message, type = "success") {
  if (typeof window.showToast === "function") window.showToast(message, type);
}

const MODAL_FOCUSABLE = 'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

function useModalAccessibility(onClose) {
  const dialogRef = useRef(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const dialog = dialogRef.current;
    const returnFocus = document.activeElement;
    if (!dialog) return undefined;
    const focusable = () => Array.from(dialog.querySelectorAll(MODAL_FOCUSABLE)).filter((element) => element.offsetParent !== null);
    (focusable()[0] || dialog).focus();
    function handleKeyDown(event) {
      if (event.key === "Escape") {
        event.preventDefault();
        closeRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const elements = focusable();
      if (!elements.length) { event.preventDefault(); dialog.focus(); return; }
      const first = elements[0];
      const last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
    dialog.addEventListener("keydown", handleKeyDown);
    return () => {
      dialog.removeEventListener("keydown", handleKeyDown);
      if (returnFocus?.isConnected) returnFocus.focus();
    };
  }, []);
  return dialogRef;
}

function makeId(prefix) {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 9)}`;
}

function displayValue(cell) {
  if (!cell) return "";
  const value = cell.w ?? cell.v;
  if (value == null) return "";
  if (value instanceof Date) return value.toISOString();
  return String(value);
}

function readSheet(sheet, sheetName, index) {
  const range = sheet["!ref"] ? XLSX.utils.decode_range(sheet["!ref"]) : { s: { r: 0, c: 0 }, e: { r: 0, c: 0 } };
  const rows = Math.max(1, range.e.r + 1);
  const columns = Math.max(1, range.e.c + 1);
  const matrix = Array.from({ length: rows }, () => Array(columns).fill(""));
  const celldata = [];
  for (let row = 0; row < rows; row += 1) {
    for (let column = 0; column < columns; column += 1) {
      const value = displayValue(sheet[XLSX.utils.encode_cell({ r: row, c: column })]);
      matrix[row][column] = value;
      if (value !== "") celldata.push({ r: row, c: column, v: { v: value, m: value } });
    }
  }
  return {
    id: `sheet-${index}-${makeId("s")}`,
    name: sheetName,
    order: index,
    row: Math.max(rows, 30),
    column: Math.max(columns, 12),
    celldata,
    config: { columnlen: Object.fromEntries(Array.from({ length: columns }, (_, column) => [column, column === 0 ? 130 : 190])) },
    sourceMatrix: matrix,
  };
}

async function readWorkbook(file) {
  if (!/\.xlsx$/i.test(file.name)) throw new Error("仅支持 .xlsx 文件");
  const workbook = XLSX.read(await file.arrayBuffer(), { type: "array", cellDates: true });
  if (!workbook.SheetNames.length) throw new Error("Excel 中没有可读取的 Sheet");
  return {
    id: makeId("source"),
    name: file.name,
    size: file.size,
    sheets: workbook.SheetNames.map((name, index) => readSheet(workbook.Sheets[name], name, index)),
  };
}

function columnLetters(index) {
  let result = "";
  let value = index + 1;
  while (value > 0) {
    value -= 1;
    result = String.fromCharCode(65 + (value % 26)) + result;
    value = Math.floor(value / 26);
  }
  return result;
}

function rangeLabel(range) {
  return `${columnLetters(range.column[0])}${range.row[0] + 1}:${columnLetters(range.column[1])}${range.row[1] + 1}`;
}

function formatBytes(bytes) {
  if (!bytes) return "0 KB";
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatDateTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  const pad = (part) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function truncate(value, limit) {
  const text = String(value || "");
  return text.length <= limit ? text : `${text.slice(0, Math.max(0, limit - 1))}…`;
}

function normalizedRange(range) {
  return {
    row: [Math.min(...range.row), Math.max(...range.row)],
    column: [Math.min(...range.column), Math.max(...range.column)],
  };
}

function isBlankCaseValues(values, columns) {
  return columns.every((column) => !String(values?.[column] ?? "").trim());
}

function filterBlankCases(cases, columns) {
  return cases.filter((item) => !isBlankCaseValues(item.values, columns));
}

function buildDataset(selections, mode) {
  if (!selections.length) return { columns: [], cases: [] };
  if (mode === "cells") {
    const columns = ["col_1"];
    return {
      columns,
      cases: filterBlankCases(selections.flatMap((selection) => selection.rows.flatMap((row) => row.values.map((value) => ({ values: { col_1: value } })))), columns),
    };
  }
  const columnCount = Math.max(...selections.map((selection) => selection.columnCount));
  const columns = Array.from({ length: columnCount }, (_, index) => `col_${index + 1}`);
  const casesByRow = new Map();
  selections.forEach((selection) => {
    selection.rows.forEach((row) => {
      const key = `${selection.sourceId}|${selection.sheetId}|${row.rowIndex}`;
      if (!casesByRow.has(key)) casesByRow.set(key, { values: {} });
      row.values.forEach((value, index) => { casesByRow.get(key).values[`col_${index + 1}`] = value; });
    });
  });
  const cases = Array.from(casesByRow.values()).map((item) => ({
    values: Object.fromEntries(columns.map((column) => [column, item.values[column] || ""])),
  }));
  return { columns, cases: filterBlankCases(cases, columns) };
}

const Spreadsheet = forwardRef(function Spreadsheet({ source, onSheetChange, onSelectionChange }, forwardedRef) {
  const workbookRef = useRef(null);
  const data = useMemo(() => source?.sheets.map(({ sourceMatrix, ...sheet }) => sheet) || [], [source]);
  useImperativeHandle(forwardedRef, () => ({
    getSelections() { return workbookRef.current?.getSelection?.() || []; },
    getActiveSheet() { return workbookRef.current?.getSheet?.() || null; },
  }));
  if (!source) return <div className="ts-empty-grid"><strong>请选择 .xlsx 文件</strong><span>文件只在当前浏览器中读取，不会上传。</span></div>;
  return (
    <Workbook
      key={source.id}
      ref={workbookRef}
      data={data}
      lang="zh"
      allowEdit={false}
      showToolbar={false}
      showFormulaBar={false}
      showSheetTabs
      rowHeaderWidth={46}
      defaultRowHeight={31}
      defaultColWidth={190}
      hooks={{ afterActivateSheet: onSheetChange, afterSelectionChange: (_sheetId, selection) => onSelectionChange?.(selection) }}
    />
  );
});

function Metrics({ items }) {
  return <div className="ts-metrics">{items.map(([key, value]) => <article key={key}><span>{key}</span><strong>{value}</strong></article>)}</div>;
}

function PageControls({ total, unit, page, pages, pageSize, onPageChange, onPageSizeChange, management = false }) {
  const footerClass = management ? "global-list-footer management-list-footer" : "ts-footer";
  const summaryClass = management ? "global-page-summary" : "ts-page-summary";
  const paginationClass = management ? "global-pagination" : "ts-pagination";
  return <div className={footerClass}><div className={summaryClass}><span>共 {total} {unit}</span><label>每页<select className={management ? "input global-page-size" : undefined} value={pageSize} onChange={(event) => onPageSizeChange(Number(event.target.value))}>{PAGE_SIZE_OPTIONS.map((size) => <option key={size} value={size}>{management ? size : `${size} 条`}</option>)}</select></label></div><div className={paginationClass}><button aria-label="上一页" title="上一页" disabled={page <= 1} onClick={() => onPageChange(page - 1)}><ChevronLeft className="ui-icon" /></button><span>{page} / {pages}</span><button aria-label="下一页" title="下一页" disabled={page >= pages} onClick={() => onPageChange(page + 1)}><ChevronRight className="ui-icon" /></button></div></div>;
}

function ConfirmModal({ title, message, detail, confirmLabel = "确认", danger = false, onClose, onConfirm }) {
  const [submitting, setSubmitting] = useState(false);
  const dialogRef = useModalAccessibility(onClose);

  async function confirm() {
    setSubmitting(true);
    const shouldClose = await onConfirm();
    if (shouldClose !== false) onClose();
    else setSubmitting(false);
  }

  return <div className="ts-modal-layer ts-confirm-modal-layer"><div className="ts-modal-backdrop" aria-hidden="true" onClick={submitting ? undefined : onClose} /><div className="ts-modal ts-confirm-modal" ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="ts-confirm-modal-title" tabIndex={-1}>
    <header><h2 id="ts-confirm-modal-title">{title}</h2><button className="ts-icon-button ts-modal-close" title="关闭" aria-label="关闭" disabled={submitting} onClick={onClose}><X className="ui-icon" /></button></header>
    <div className="ts-modal-body"><p>{message}</p>{detail && <p className="ts-confirm-detail">{detail}</p>}</div>
    <footer><button className="ts-btn secondary" disabled={submitting} onClick={onClose}>取消</button><button className={`ts-btn ${danger ? "danger" : "primary"}`} disabled={submitting} onClick={confirm}>{danger && <Trash2 className="ui-icon" />}{submitting ? "处理中…" : confirmLabel}</button></footer>
  </div></div>;
}

function ListView({ onCreate, onOpen }) {
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(PAGE_SIZE);
  const [state, setState] = useState(() => testSetListCache || { items: [], metrics: {}, total: 0 });
  const [loading, setLoading] = useState(true);
  const [pendingDelete, setPendingDelete] = useState(null);
  const initialQueryEffect = useRef(true);
  const loadRequestId = useRef(0);

  async function load(nextPage = page, nextQuery = query, nextPageSize = pageSize) {
    const requestId = ++loadRequestId.current;
    setLoading(true);
    try {
      const payload = await request(`/api/test-sets?page=${nextPage}&page_size=${nextPageSize}&name_query=${encodeURIComponent(nextQuery)}`);
      if (requestId !== loadRequestId.current) return;
      testSetListCache = payload;
      setState(payload);
    } catch (error) {
      if (requestId === loadRequestId.current) toast(`加载测试集失败：${error.message}`, "error");
    } finally {
      if (requestId === loadRequestId.current) setLoading(false);
    }
  }

  useEffect(() => { load(page, query, pageSize); }, [page, pageSize]);
  useEffect(() => {
    if (initialQueryEffect.current) {
      initialQueryEffect.current = false;
      return undefined;
    }
    const timer = setTimeout(() => {
      if (page === 1) load(1, query, pageSize);
      else setPage(1);
    }, 250);
    return () => clearTimeout(timer);
  }, [query]);

  async function confirmRemove() {
    try {
      await request(`/api/test-sets/${pendingDelete.id}`, { method: "DELETE" });
      toast("测试集已删除");
      await load(page, query);
      return true;
    } catch (error) {
      toast(`删除失败：${error.message}`, "error");
      return false;
    }
  }

  const pages = Math.max(1, Math.ceil(state.total / pageSize));
  return <section className="ts-page execution-page">
    <div className="ts-heading execution-page-header management-page-header"><div className="management-page-title"><h1>测试集管理</h1><span className="management-page-description">维护测试字段与用例</span></div></div>
    <div className="toolbar execution-toolbar management-list-toolbar"><button className="btn btn-primary" type="button" onClick={onCreate}><Plus className="ui-icon" />新建测试集</button><button className="btn" type="button" disabled={loading} onClick={() => load(page, query)}><RefreshCw className="ui-icon" />刷新</button><span className="toolbar-sep" /><label className="ts-search"><Search className="ui-icon" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索测试集名称或说明" /></label></div>
    <div className="table-wrap execution-table-wrap management-list-wrap ts-table-wrap ts-list-table-wrap" aria-busy={loading}><table className="table execution-table management-list-table ts-table ts-list-table"><thead><tr><th>测试集名称</th><th>用例数</th><th>字段数</th><th>说明</th><th>最近更新</th><th className="management-list-actions-head">操作</th></tr></thead><tbody>
      {loading && !state.items.length && <tr><td colSpan="6"><div className="execution-empty"><strong>正在加载测试集...</strong></div></td></tr>}
      {!loading && !state.items.length && <tr><td colSpan="6"><div className="execution-empty"><strong>尚未创建测试集</strong><button className="btn btn-sm" type="button" onClick={onCreate}>新建测试集</button></div></td></tr>}
      {!!state.items.length && state.items.map((item) => <tr key={item.id}><td className="management-list-primary" title={item.name}><button className="execution-name-button ts-name" onClick={() => onOpen(item.id)}>{item.name}</button></td><td>{item.case_count}</td><td>{item.column_count}</td><td className="management-list-text" title={item.description || "暂无说明"}>{truncate(item.description || "暂无说明", 20)}</td><td className="management-list-time ts-time">{formatDateTime(item.updated_at)}</td><td className="management-list-actions-cell"><div className="management-list-row-actions"><button className="btn-icon" title="删除测试集" aria-label="删除测试集" onClick={() => setPendingDelete(item)}><Trash2 className="ui-icon" /></button></div></td></tr>)}
    </tbody></table></div>
    <PageControls management total={state.total} unit="个测试集" page={page} pages={pages} pageSize={pageSize} onPageChange={setPage} onPageSizeChange={(size) => { setPage(1); setPageSize(size); }} />
    {pendingDelete && <ConfirmModal title="删除测试集" message={`确定删除“${pendingDelete.name}”吗？`} detail="测试集及其全部用例将被删除，此操作不可恢复。" confirmLabel="删除" danger onClose={() => setPendingDelete(null)} onConfirm={confirmRemove} />}
  </section>;
}

function SaveModal({ mode, dataset, sourceCount, sheetCount, target, onClose, onSaved }) {
  const [name, setName] = useState(() => dataset.defaultName || "新建测试集");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const appending = mode === "append";
  const dialogRef = useModalAccessibility(onClose);

  async function save() {
    if (!appending && !name.trim()) return toast("请填写测试集名称", "error");
    setSaving(true);
    try {
      if (appending) {
        if (dataset.columns.length !== target.columns.length) throw new Error(`字段数量不一致：当前测试集为 ${target.columns.length} 个字段，本次选择为 ${dataset.columns.length} 个字段`);
        const appended = dataset.cases.map((item) => ({ id: makeId("case"), values: Object.fromEntries(target.columns.map((column, index) => [column, item.values[`col_${index + 1}`] || ""])) }));
        onSaved({ ...target, cases: filterBlankCases([...target.cases, ...appended], target.columns) }, false);
      } else {
        const payload = await request("/api/test-sets", { method: "POST", body: JSON.stringify({ name: name.trim(), description: description.trim(), columns: dataset.columns, cases: filterBlankCases(dataset.cases, dataset.columns) }) });
        onSaved(payload.test_set, true);
      }
    } catch (error) { toast(`${appending ? "添加" : "保存"}失败：${error.message}`, "error"); }
    finally { setSaving(false); }
  }

  return <div className="ts-modal-layer"><div className="ts-modal-backdrop" aria-hidden="true" onClick={onClose} /><div className="ts-modal" ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="ts-save-modal-title" tabIndex={-1}>
    <header><div>{!appending && <span>步骤 3 / 3</span>}<h2 id="ts-save-modal-title">{appending ? "添加 Excel 用例" : "保存测试集"}</h2></div><button className="ts-icon-button ts-modal-close" title="关闭" aria-label="关闭" onClick={onClose}><X className="ui-icon" /></button></header>
    <div className="ts-modal-body"><div className="ts-preview"><b><CircleCheck className="ui-icon" /></b><div><strong>选区已转换为数据库用例</strong><span>{dataset.cases.length} 条用例 · {dataset.columns.length} 个字段 · {sourceCount} 个 Excel · {sheetCount} 个 Sheet</span></div></div>
      {!appending && <><label className="ts-field"><span>测试集名称 <b>*</b></span><input maxLength="120" value={name} onChange={(event) => setName(event.target.value)} /></label><label className="ts-field"><span>测试集说明</span><textarea maxLength="1000" rows="4" value={description} onChange={(event) => setDescription(event.target.value)} /><small>{description.length}/1000</small></label></>}
      <div className="ts-schema"><div><strong>字段映射预览</strong><span>字段默认按选中位置生成</span></div>{dataset.columns.map((column, index) => <p key={column}><code>{appending ? target.columns[index] : column}</code><span>第 {index + 1} 个选中列</span></p>)}</div>
    </div><footer><button className="ts-btn secondary" onClick={onClose}>返回调整</button><button className="ts-btn primary" disabled={saving} onClick={save}>{saving ? "处理中…" : appending ? "添加到测试集" : "保存并查看详情"}</button></footer>
  </div></div>;
}

function ImportView({ mode, target, onBack, onComplete }) {
  const fileInput = useRef(null);
  const workbookRef = useRef(null);
  const [sources, setSources] = useState([]);
  const [activeSourceId, setActiveSourceId] = useState("");
  const [activeSheetId, setActiveSheetId] = useState("");
  const [selections, setSelections] = useState([]);
  const [interpretation, setInterpretation] = useState("rows");
  const [reading, setReading] = useState(false);
  const [showSave, setShowSave] = useState(false);
  const currentSelectionsRef = useRef([]);
  const source = sources.find((item) => item.id === activeSourceId) || null;
  const activeSheet = source?.sheets.find((sheet) => sheet.id === activeSheetId) || source?.sheets[0] || null;
  const dataset = useMemo(() => buildDataset(selections, interpretation), [selections, interpretation]);

  async function addFiles(event) {
    const files = Array.from(event.target.files || []);
    event.target.value = "";
    if (!files.length) return;
    setReading(true);
    for (const file of files) {
      try {
        const parsed = await readWorkbook(file);
        setSources((current) => [...current.filter((item) => item.name !== parsed.name), parsed]);
        setActiveSourceId(parsed.id);
        setActiveSheetId(parsed.sheets[0].id);
      } catch (error) { toast(`${file.name} 读取失败：${error.message}`, "error"); }
    }
    setReading(false);
  }

  function removeSource(sourceId) {
    const remaining = sources.filter((item) => item.id !== sourceId);
    setSources(remaining);
    setSelections((items) => items.filter((item) => item.sourceId !== sourceId));
    if (activeSourceId === sourceId) {
      setActiveSourceId(remaining[0]?.id || "");
      setActiveSheetId(remaining[0]?.sheets[0]?.id || "");
    }
  }

  function addCurrentSelections() {
    if (!source || !activeSheet) return toast("请先添加 Excel 文件", "error");
    const ranges = workbookRef.current?.getSelections() || [];
    if (!ranges.length) return toast("请先选择单元格区域", "error");
    const additions = ranges.map(normalizedRange).map((range) => {
      const rows = [];
      for (let row = range.row[0]; row <= range.row[1]; row += 1) {
        const values = [];
        for (let column = range.column[0]; column <= range.column[1]; column += 1) values.push(activeSheet.sourceMatrix[row]?.[column] || "");
        rows.push({ rowIndex: row, values });
      }
      return {
        id: `${source.id}:${activeSheet.id}:${range.row.join("-")}:${range.column.join("-")}`,
        sourceId: source.id,
        sourceFile: source.name,
        sheetId: activeSheet.id,
        sheetName: activeSheet.name,
        range,
        rows,
        columnCount: range.column[1] - range.column[0] + 1,
      };
    });
    setSelections((current) => [...current.filter((item) => !additions.some((next) => next.id === item.id)), ...additions]);
    toast(`已添加 ${additions.length} 个选区`);
  }

  const sourceCount = new Set(selections.map((item) => item.sourceId)).size;
  const sheetCount = new Set(selections.map((item) => `${item.sourceId}|${item.sheetId}`)).size;
  const defaultName = sources.length === 1 ? `${sources[0].name.replace(/\.xlsx$/i, "")}测试集` : `${sources[0]?.name.replace(/\.xlsx$/i, "") || "新建"}等 ${sources.length} 个文件测试集`;
  function updateCurrentSelection(selection) {
    const candidates = Array.isArray(selection) ? selection : selection ? [selection] : [];
    currentSelectionsRef.current = candidates.filter((item) =>
      item && Array.isArray(item.row) && Array.isArray(item.column) &&
      item.row.every(Number.isFinite) && item.column.every(Number.isFinite)
    );
    const label = document.getElementById("ts-current-selection");
    if (label) label.textContent = currentSelectionsRef.current.length
      ? currentSelectionsRef.current.map((item) => rangeLabel(normalizedRange(item))).join("、")
      : "-";
  }

  return <section className="ts-page ts-import-page">
    <div className="ts-heading"><div className="ts-heading-left"><button className="ts-btn ghost" onClick={onBack}><ArrowLeft className="ui-icon" />返回</button><div><h1>{mode === "append" ? "从 Excel 添加用例" : "从 Excel 创建测试集"}</h1><p>{mode === "append" ? "从一个或多个 Excel 选择用例，按字段顺序追加到当前测试集。" : "文件仅在浏览器中解析，可从多个 Excel 累计选择用例。"}</p></div></div><div className="ts-stepper"><span>1 选择文件</span><i /><b>2 选择用例</b><i /><span>3 保存测试集</span></div></div>
    <div className="ts-card ts-import-toolbar"><div className="ts-file-summary"><button className="ts-btn secondary" onClick={() => fileInput.current.click()}><FileUp className="ui-icon" />添加 .xlsx 文件</button><input ref={fileInput} hidden multiple type="file" accept=".xlsx" onChange={addFiles} /><div><strong>{source?.name || "尚未选择文件"}</strong><span>{source ? `${source.sheets.length} 个 Sheet · ${formatBytes(source.size)} · 浏览器内加载` : "文件不会上传到服务器"}</span></div></div><div className="ts-import-options"><span>选区首行作为用例保留</span><label>生成方式<select value={interpretation} onChange={(event) => setInterpretation(event.target.value)}><option value="rows">按行生成用例</option><option value="cells">每个单元格生成用例</option></select></label></div><div className="ts-file-tabs">{sources.map((item) => <button className={item.id === activeSourceId ? "active" : ""} key={item.id} onClick={() => { setActiveSourceId(item.id); setActiveSheetId(item.sheets[0].id); }}><span>{item.name}</span><i className="ts-tab-remove" title="移除文件" aria-label="移除文件" onClick={(event) => { event.stopPropagation(); removeSource(item.id); }}><X className="ui-icon" /></i></button>)}</div></div>
    <div className="ts-workspace"><div className="ts-card ts-grid-card"><div className="ts-grid-toolbar"><div><strong>选择 Excel 内容</strong><span>当前 Sheet：{activeSheet?.name || "-"} · 拖动选择单元格，按 Ctrl 可添加多个区域</span></div><div><span>当前选区：<b id="ts-current-selection">-</b></span><button className="ts-btn primary" onClick={addCurrentSelections}><Plus className="ui-icon" />添加当前选区</button></div></div><div className="ts-grid-host"><Spreadsheet ref={workbookRef} source={source} onSheetChange={(id) => { setActiveSheetId((current) => current === id ? current : id); updateCurrentSelection(null); }} onSelectionChange={updateCurrentSelection} />{reading && <div className="ts-loading">正在读取 Excel…</div>}</div></div>
      <aside className="ts-card ts-selection-panel"><div className="ts-panel-title"><div><strong>已选用例区域</strong><span>{selections.length} 个区域</span></div><button className="ts-clear-button" onClick={() => setSelections([])}><Eraser className="ui-icon" />清空</button></div><div className="ts-summary"><div><span>预计用例</span><strong>{dataset.cases.length}</strong></div><div><span>字段数量</span><strong>{dataset.columns.length}</strong></div><div><span>Excel 文件</span><strong>{sourceCount}</strong></div><div><span>涉及 Sheet</span><strong>{sheetCount}</strong></div></div><div className="ts-selection-list">{selections.map((item) => <article key={item.id}><div><strong>{item.sourceFile}</strong><span>{item.sheetName}!{rangeLabel(item.range)}</span></div><button className="ts-icon-button" title="移除选区" aria-label="移除选区" onClick={() => setSelections((current) => current.filter((selection) => selection.id !== item.id))}><X className="ui-icon" /></button></article>)}</div>{!selections.length && <div className="ts-selection-empty"><b><LayoutGrid className="ui-icon" /></b><strong>尚未添加选区</strong><p>在左侧选择任意网格，再点击“添加当前选区”。不同 Excel、不同 Sheet 的选区均可累计保存。</p></div>}<div className="ts-tip"><b><Info className="ui-icon" /></b><p>选区中的首行也作为用例保留；字段默认从 <code>col_1</code> 顺序生成，可在详情页修改或删除。</p></div><button className="ts-btn primary large full" disabled={!dataset.cases.length} onClick={() => setShowSave(true)}><Save className="ui-icon" />{mode === "append" ? "预览并添加到测试集" : "预览并保存测试集"}</button></aside>
    </div>
    {showSave && <SaveModal mode={mode} target={target} dataset={{ ...dataset, defaultName }} sourceCount={sourceCount} sheetCount={sheetCount} onClose={() => setShowSave(false)} onSaved={onComplete} />}
  </section>;
}

function ColumnSettingsModal({ testSet, draft, onClose, onSaved }) {
  const [entries, setEntries] = useState(() => draft.columns.map((column) => ({ original: column, name: column, deleted: false })));
  const [saving, setSaving] = useState(false);
  const [pendingDeletion, setPendingDeletion] = useState(null);
  const remainingCount = entries.filter((entry) => !entry.deleted).length;
  const dialogRef = useModalAccessibility(onClose);

  async function saveColumns(kept, columns) {
    const cases = filterBlankCases(draft.cases.map((item) => ({
      id: item.id,
      values: Object.fromEntries(kept.map((entry, index) => [columns[index], item.values[entry.original] || ""])),
    })), columns);
    setSaving(true);
    try {
      const payload = await request(`/api/test-sets/${draft.id}`, {
        method: "PUT",
        body: JSON.stringify({
          name: draft.name,
          description: draft.description,
          columns,
          cases,
        }),
      });
      onSaved(payload.test_set);
      toast("字段设置已保存并立即生效");
      return true;
    } catch (error) {
      toast(`字段设置保存失败：${error.message}`, "error");
      return false;
    } finally {
      setSaving(false);
    }
  }

  async function persist() {
    const kept = entries.filter((entry) => !entry.deleted);
    if (!kept.length) return toast("测试集至少保留一个字段", "error");
    const columns = kept.map((entry, index) => {
      const name = entry.name.trim();
      if (/^col_[1-9][0-9]*$/.test(name) && name === entry.original) return `col_${index + 1}`;
      return name;
    });
    if (columns.some((column) => !column)) return toast("字段名不能为空", "error");
    if (new Set(columns).size !== columns.length) return toast("字段名不能重复", "error");
    const deletedCount = entries.length - kept.length;
    if (deletedCount) {
      setPendingDeletion({ kept, columns, deletedCount });
      return;
    }
    await saveColumns(kept, columns);
  }

  return <><div className="ts-modal-layer"><div className="ts-modal-backdrop" aria-hidden="true" onClick={onClose} /><div className="ts-modal ts-column-settings-modal" ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="ts-column-settings-title" tabIndex={-1}>
    <header><div><h2 id="ts-column-settings-title">字段设置</h2><span>批量修改字段名称，或选择需要删除的字段</span></div><button className="ts-icon-button ts-modal-close" title="关闭" aria-label="关闭" onClick={onClose}><X className="ui-icon" /></button></header>
    <div className="ts-modal-body"><div className="ts-column-settings-head"><span>字段名称</span><span>删除</span></div><div className="ts-column-settings-list">
      {entries.map((entry, index) => <div className={entry.deleted ? "deleted" : ""} key={entry.original}><b>{index + 1}</b><input maxLength="120" aria-label={`字段 ${index + 1} 名称`} disabled={entry.deleted} value={entry.name} onChange={(event) => setEntries(entries.map((item, position) => position === index ? { ...item, name: event.target.value } : item))} /><label><input type="checkbox" checked={entry.deleted} onChange={(event) => setEntries(entries.map((item, position) => position === index ? { ...item, deleted: event.target.checked } : item))} /><span>删除</span></label></div>)}
    </div><p className="ts-column-settings-tip">保存后立即写入数据库；删除默认字段时，剩余的 <code>col_x</code> 会按顺序重新编号。</p></div>
    <footer><span className="ts-column-settings-count">保留 {remainingCount} 个字段</span><button className="ts-btn secondary" onClick={onClose}><X className="ui-icon" />取消</button><button className="ts-btn primary" disabled={saving || !remainingCount} onClick={persist}><Save className="ui-icon" />{saving ? "保存中…" : "保存并立即生效"}</button></footer>
  </div></div>{pendingDeletion && <ConfirmModal title="删除字段" message={`确定删除选中的 ${pendingDeletion.deletedCount} 个字段吗？`} detail="对应字段数据将从全部用例中删除，此操作不可恢复。" confirmLabel="删除字段" danger onClose={() => setPendingDeletion(null)} onConfirm={() => saveColumns(pendingDeletion.kept, pendingDeletion.columns)} />}</>;
}

function DetailView({ testSetId, initial, onBack, onImport }) {
  const [testSet, setTestSet] = useState(initial || null);
  const [draft, setDraft] = useState(initial || null);
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [casePageSize, setCasePageSize] = useState(CASE_PAGE_SIZE);
  const [editingName, setEditingName] = useState(false);
  const [editingDescription, setEditingDescription] = useState(false);
  const [saving, setSaving] = useState(false);
  const [showColumnSettings, setShowColumnSettings] = useState(false);
  const [pendingCase, setPendingCase] = useState(null);
  const [pendingCaseError, setPendingCaseError] = useState("");
  const [savingPendingCase, setSavingPendingCase] = useState(false);
  const pendingCaseRowRef = useRef(null);
  const pendingCaseInputRef = useRef(null);
  const pendingCaseSaveRef = useRef(null);
  const savedMetadataRef = useRef({ name: initial?.name || "", description: initial?.description || "" });
  const metadataDraftRef = useRef({ name: initial?.name || "", description: initial?.description || "" });
  const nameEditCancelledRef = useRef(false);
  const descriptionEditCancelledRef = useRef(false);

  useEffect(() => {
    if (initial?.id === testSetId) return;
    request(`/api/test-sets/${testSetId}`).then((payload) => {
      savedMetadataRef.current = { name: payload.test_set.name, description: payload.test_set.description };
      metadataDraftRef.current = { ...savedMetadataRef.current };
      setTestSet(payload.test_set);
      setDraft(payload.test_set);
    }).catch((error) => toast(`加载详情失败：${error.message}`, "error"));
  }, [testSetId]);

  if (!draft) return <div className="ts-loading-page">正在加载测试集…</div>;
  const filtered = draft.cases.filter((item) => !query || draft.columns.some((column) => String(item.values[column] || "").toLowerCase().includes(query.toLowerCase())));
  const pageCases = filtered.slice((page - 1) * casePageSize, page * casePageSize);
  const pages = Math.max(1, Math.ceil(filtered.length / casePageSize));

  function addCase() {
    if (pendingCase) {
      pendingCaseInputRef.current?.focus();
      return;
    }
    setPendingCase({ id: makeId("case"), values: Object.fromEntries(draft.columns.map((column) => [column, ""])) });
    setPendingCaseError("");
    setQuery("");
    setPage(1);
    requestAnimationFrame(() => pendingCaseInputRef.current?.focus());
  }

  function writeBody(cases) {
    const nonBlankCases = filterBlankCases(cases, draft.columns);
    return JSON.stringify({ name: draft.name, description: draft.description, columns: draft.columns, cases: nonBlankCases.map((item) => ({ id: item.id, values: item.values })) });
  }

  function isBlankCase(testCase) {
    return isBlankCaseValues(testCase.values, draft.columns);
  }

  async function persistMetadata(nextName, nextDescription) {
    try {
      const payload = await request(`/api/test-sets/${draft.id}/metadata`, {
        method: "PUT",
        body: JSON.stringify({ name: nextName, description: nextDescription }),
      });
      const metadata = {
        name: payload.test_set.name,
        description: payload.test_set.description,
        updated_at: payload.test_set.updated_at,
      };
      savedMetadataRef.current = { name: metadata.name, description: metadata.description };
      metadataDraftRef.current = { ...savedMetadataRef.current };
      setTestSet((current) => current ? { ...current, ...metadata } : payload.test_set);
      setDraft((current) => current ? { ...current, ...metadata } : payload.test_set);
      return true;
    } catch (error) {
      toast(`测试集信息保存失败：${error.message}`, "error");
      return false;
    }
  }

  async function commitName(nextName = draft.name) {
    if (nameEditCancelledRef.current) {
      nameEditCancelledRef.current = false;
      metadataDraftRef.current.name = savedMetadataRef.current.name;
      setDraft((current) => ({ ...current, name: savedMetadataRef.current.name }));
      setEditingName(false);
      return;
    }
    if (!nextName.trim()) {
      setDraft((current) => ({ ...current, name: savedMetadataRef.current.name }));
      setEditingName(false);
      toast("测试集名称不能为空", "error");
      return;
    }
    if (nextName === savedMetadataRef.current.name && draft.description === savedMetadataRef.current.description) {
      setEditingName(false);
      return;
    }
    if (await persistMetadata(nextName, draft.description)) setEditingName(false);
  }

  async function commitDescription(nextDescription = draft.description) {
    if (descriptionEditCancelledRef.current) {
      descriptionEditCancelledRef.current = false;
      metadataDraftRef.current.description = savedMetadataRef.current.description;
      setDraft((current) => ({ ...current, description: savedMetadataRef.current.description }));
      setEditingDescription(false);
      return;
    }
    if (draft.name === savedMetadataRef.current.name && nextDescription === savedMetadataRef.current.description) {
      setEditingDescription(false);
      return;
    }
    if (await persistMetadata(draft.name, nextDescription)) setEditingDescription(false);
  }

  async function savePendingCase() {
    if (pendingCaseSaveRef.current) return pendingCaseSaveRef.current;
    if (!pendingCase) return null;
    if (isBlankCase(pendingCase)) {
      setPendingCase(null);
      setPendingCaseError("");
      return null;
    }
    const nextCases = [pendingCase, ...draft.cases];
    setSavingPendingCase(true);
    setPendingCaseError("");
    const savePromise = request(`/api/test-sets/${draft.id}`, { method: "PUT", body: writeBody(nextCases) })
      .then((payload) => {
        setTestSet(payload.test_set);
        setDraft(payload.test_set);
        setPendingCase(null);
        setPage(1);
        toast("新用例已保存");
        return payload;
      })
      .catch((error) => {
        setPendingCaseError(`保存失败：${error.message}。内容已保留，请修改后再次点击行外或重试。`);
        toast(`新增用例保存失败：${error.message}`, "error");
        return null;
      })
      .finally(() => {
        setSavingPendingCase(false);
        pendingCaseSaveRef.current = null;
      });
    pendingCaseSaveRef.current = savePromise;
    return savePromise;
  }

  async function save() {
    if (pendingCase || pendingCaseSaveRef.current) {
      await savePendingCase();
      return;
    }
    setSaving(true);
    try {
      const payload = await request(`/api/test-sets/${draft.id}`, { method: "PUT", body: writeBody(draft.cases) });
      setTestSet(payload.test_set); setDraft(payload.test_set); toast("测试集修改已保存");
    } catch (error) { toast(`保存失败：${error.message}`, "error"); }
    finally { setSaving(false); }
  }

  function applyColumnSettings(record) {
    setTestSet(record);
    setDraft(record);
    setShowColumnSettings(false);
    setPage(1);
  }

  return <section className="ts-page"><div className="ts-detail-heading"><div className="ts-heading-left ts-detail-metadata"><button className="ts-btn ghost" onClick={onBack}><ArrowLeft className="ui-icon" />返回列表</button><span className="ts-detail-divider" />{editingName ? <input className="ts-detail-name-input" autoFocus maxLength="120" value={draft.name} onChange={(event) => { metadataDraftRef.current.name = event.target.value; setDraft({ ...draft, name: event.target.value }); }} onBlur={(event) => void commitName(metadataDraftRef.current.name === draft.name ? event.currentTarget.value : metadataDraftRef.current.name)} onKeyDown={(event) => { if (event.key === "Enter") event.currentTarget.blur(); if (event.key === "Escape") { nameEditCancelledRef.current = true; event.currentTarget.blur(); } }} aria-label="测试集名称" /> : <button type="button" className="ts-detail-name" title="编辑测试集名称" aria-label={`编辑测试集名称：${draft.name}`} onClick={() => { metadataDraftRef.current.name = draft.name; setEditingName(true); }}><span>{draft.name}</span><Pencil className="ui-icon" /></button>}<div className={`ts-detail-description ${editingDescription ? "is-editing" : ""}`}><FileText className="ui-icon" />{editingDescription ? <div className="ts-detail-description-editor"><textarea autoFocus maxLength="1000" rows="4" value={draft.description} onChange={(event) => { metadataDraftRef.current.description = event.target.value; setDraft({ ...draft, description: event.target.value }); }} onBlur={(event) => void commitDescription(metadataDraftRef.current.description === draft.description ? event.currentTarget.value : metadataDraftRef.current.description)} onKeyDown={(event) => { if (event.key === "Escape") { descriptionEditCancelledRef.current = true; event.currentTarget.blur(); } }} aria-label="测试集说明" /></div> : <button type="button" title="编辑测试集说明" aria-label="编辑测试集说明" onClick={() => { metadataDraftRef.current.description = draft.description; setEditingDescription(true); }}><span>{draft.description || "添加测试集说明"}</span><Pencil className="ui-icon" /></button>}</div></div><div className="ts-detail-actions"><button className="ts-btn secondary" onClick={() => onImport(draft)}><FileUp className="ui-icon" />从 .xlsx 添加</button><button className="ts-btn secondary" onClick={addCase}><Plus className="ui-icon" />手动添加</button><button className="ts-btn primary" disabled={saving} onClick={save}><Save className="ui-icon" />{saving ? "保存中…" : "保存修改"}</button></div></div>
    <Metrics items={[["用例数", draft.cases.length], ["字段数", draft.columns.length]]} />
    <div className="ts-card">
      <div className="ts-toolbar"><label className="ts-search"><Search className="ui-icon" /><input value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }} placeholder="搜索当前测试集用例" /></label></div>
      <div className="ts-table-wrap ts-detail-table"><table className="ts-table">
        <thead><tr>{draft.columns.map((column) => <th className="ts-case-header" key={column}><span>{column}</span></th>)}<th className="ts-field-settings-header"><button type="button" title="字段设置" onClick={() => setShowColumnSettings(true)}><Settings2 className="ui-icon" />字段设置</button></th></tr></thead>
        <tbody>
          {pendingCase && <>
            <tr ref={pendingCaseRowRef} className={`ts-new-case-row${pendingCaseError ? " error" : ""}`}>
              {draft.columns.map((column, index) => <td key={column}><input ref={index === 0 ? pendingCaseInputRef : null} className="ts-cell-input" aria-label={`新用例 ${column}`} disabled={savingPendingCase} value={pendingCase.values[column] || ""} onChange={(event) => { setPendingCase({ ...pendingCase, values: { ...pendingCase.values, [column]: event.target.value } }); setPendingCaseError(""); }} onBlur={(event) => { if (!pendingCaseRowRef.current?.contains(event.relatedTarget)) void savePendingCase(); }} /></td>)}
              <td><div className="ts-new-case-status" aria-live="polite"><span>{savingPendingCase ? "正在保存…" : pendingCaseError ? "保存失败" : "新用例"}</span>{pendingCaseError && <button type="button" onMouseDown={(event) => event.preventDefault()} onClick={() => void savePendingCase()}>重试</button>}</div></td>
            </tr>
            {pendingCaseError && <tr className="ts-new-case-error"><td colSpan={draft.columns.length + 1}>{pendingCaseError}</td></tr>}
          </>}
          {pageCases.map((item, rowIndex) => <tr key={item.id}>{draft.columns.map((column) => <td key={column}><input className="ts-cell-input" aria-label={`用例 ${(page - 1) * casePageSize + rowIndex + 1} ${column}`} value={item.values[column] || ""} onChange={(event) => setDraft({ ...draft, cases: draft.cases.map((testCase) => testCase.id === item.id ? { ...testCase, values: { ...testCase.values, [column]: event.target.value } } : testCase) })} /></td>)}<td><button className="ts-delete-case ts-icon-button" title="删除用例" aria-label="删除用例" onClick={() => setDraft({ ...draft, cases: draft.cases.filter((testCase) => testCase.id !== item.id) })}><Trash2 className="ui-icon" /></button></td></tr>)}
        </tbody>
      </table></div>
      <PageControls total={filtered.length} unit="条用例" page={page} pages={pages} pageSize={casePageSize} onPageChange={setPage} onPageSizeChange={(size) => { setPage(1); setCasePageSize(size); }} />
    </div>
    {showColumnSettings && <ColumnSettingsModal testSet={testSet} draft={draft} onClose={() => setShowColumnSettings(false)} onSaved={applyColumnSettings} />}
  </section>;
}

function TestSetApp() {
  const [view, setView] = useState({ name: "list" });
  if (view.name === "import") return <ImportView mode={view.mode} target={view.target} onBack={() => setView(view.target ? { name: "detail", id: view.target.id, initial: view.target } : { name: "list" })} onComplete={(record, persisted) => { if (persisted) toast("测试集已保存"); else toast("用例已追加，请保存修改"); setView({ name: "detail", id: record.id, initial: record }); }} />;
  if (view.name === "detail") return <DetailView testSetId={view.id} initial={view.initial} onBack={() => setView({ name: "list" })} onImport={(target) => setView({ name: "import", mode: "append", target })} />;
  return <ListView onCreate={() => setView({ name: "import", mode: "create" })} onOpen={(id) => setView({ name: "detail", id })} />;
}

let root = null;
function unmount() {
  if (!root) return;
  root.unmount();
  root = null;
}

function mount() {
  const container = document.getElementById("content-area");
  if (!container) return;
  unmount();
  window.currentView = "sets";
  container.innerHTML = '<div id="test-set-app-root" class="test-set-app"></div>';
  root = createRoot(document.getElementById("test-set-app-root"));
  root.render(<TestSetApp />);
}

window.TestSetManagement = { mount, unmount };
window.viewSets = mount;
