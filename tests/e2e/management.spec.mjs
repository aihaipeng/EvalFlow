import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import * as XLSX from "xlsx";

function captureErrors(page) {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  return errors;
}

async function expectNoAxeViolations(page, include) {
  let scan = new AxeBuilder({ page }).withTags([
    "wcag2a",
    "wcag2aa",
    "wcag21aa",
  ]);
  if (include) scan = scan.include(include);
  const result = await scan.analyze();
  expect(result.violations, JSON.stringify(result.violations, null, 2)).toEqual(
    [],
  );
}

async function createBatchValidationResources(request, prefix) {
  const id = () => crypto.randomUUID();
  const testSetResponse = await request.post("/api/test-sets", {
    data: {
      name: `${prefix}测试集`,
      description: "",
      columns: ["question", "expected"],
      cases: [{ values: { question: "hello", expected: "ok" } }],
    },
  });
  expect(testSetResponse.ok()).toBeTruthy();

  const startId = id();
  const endId = id();
  const workflowResponse = await request.post("/api/workflows", {
    data: {
      name: `${prefix}工作流`,
      description: "",
      nodes: [
        {
          node: {
            id: startId,
            type: "START",
            name: "START",
            description: "",
            inputs: [{ name: "question", type: "string", value: "" }],
          },
          position_x: 0,
          position_y: 0,
        },
        {
          node: { id: endId, type: "END", name: "END", description: "" },
          position_x: 240,
          position_y: 0,
        },
      ],
      edges: [{ id: id(), source_node_id: startId, target_node_id: endId }],
    },
  });
  expect(workflowResponse.ok()).toBeTruthy();
}

async function createParallelSingleCaseTask(request) {
  const id = () => crypto.randomUUID();
  const testSetResponse = await request.post("/api/test-sets", {
    data: {
      name: "并行单条测试集",
      description: "",
      columns: ["question"],
      cases: ["one", "two", "three"].map((question) => ({
        values: { question },
      })),
    },
  });
  const testSetId = (await testSetResponse.json()).test_set.id;
  const startId = id();
  const scriptId = id();
  const endId = id();
  const workflowResponse = await request.post("/api/workflows", {
    data: {
      name: "并行单条工作流",
      description: "",
      nodes: [
        {
          node: {
            id: startId,
            type: "START",
            name: "START",
            description: "",
            inputs: [{ name: "question", type: "string", value: "" }],
          },
          position_x: 0,
          position_y: 0,
        },
        {
          node: {
            id: scriptId,
            type: "SCRIPT",
            name: "等待槽位",
            description: "",
            script: 'import time\ntime.sleep(2)\nresult = context["question"]',
            outputs: [{ name: "answer", type: "string", source: "result" }],
          },
          position_x: 240,
          position_y: 0,
        },
        {
          node: { id: endId, type: "END", name: "END", description: "" },
          position_x: 480,
          position_y: 0,
        },
      ],
      edges: [
        { id: id(), source_node_id: startId, target_node_id: scriptId },
        { id: id(), source_node_id: scriptId, target_node_id: endId },
      ],
    },
  });
  const workflowId = (await workflowResponse.json()).workflow.workflow.id;
  const batchResponse = await request.post("/api/batch-runs", {
    data: {
      name: "并行单条任务",
      description: "",
      test_set_id: testSetId,
      workflow_id: workflowId,
      variables: [
        {
          source: "TEST_SET",
          key: "question",
          value: "question",
          type: "string",
        },
      ],
      case_concurrency: 2,
      failure_retry_count: 0,
      call_order: "SEQUENTIAL",
      evaluation_rules: [],
      case_display_column: "question",
      rule_display_column: null,
    },
  });
  expect(batchResponse.ok()).toBeTruthy();
  return (await batchResponse.json()).batch.id;
}

test("四个管理目录可切换且无浏览器错误", async ({ page }) => {
  const errors = captureErrors(page);
  await page.goto("/");
  for (const [nav, heading] of [
    ["测试集管理", "测试集管理"],
    ["供应商管理", "供应商管理"],
    ["工作流管理", "工作流管理"],
    ["任务调度", "任务调度"],
  ]) {
    await page.getByRole("button", { name: nav }).click();
    await expect(
      page.getByRole("heading", { name: heading, exact: true }),
    ).toBeVisible();
    await expectNoAxeViolations(page, "#content-area");
  }
  expect(errors).toEqual([]);
});

test("同一 Excel 可跨 Sheet 累计并保存正确用例", async ({ page, request }) => {
  const errors = captureErrors(page);
  const workbook = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(
    workbook,
    XLSX.utils.aoa_to_sheet([["Sheet1-value"]]),
    "Sheet1",
  );
  XLSX.utils.book_append_sheet(
    workbook,
    XLSX.utils.aoa_to_sheet([["Sheet2-value"]]),
    "Sheet2",
  );
  const buffer = XLSX.write(workbook, { bookType: "xlsx", type: "buffer" });

  await page.goto("/");
  await page.getByRole("button", { name: "新建测试集" }).first().click();
  await page.locator('input[type="file"][accept=".xlsx"]').setInputFiles({
    name: "multi-sheet.xlsx",
    mimeType:
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    buffer,
  });
  await expect(page.getByText("2 个 Sheet ·", { exact: false })).toBeVisible();

  async function selectA1AndAdd() {
    await page
      .locator("#luckysheet-sheettable_0")
      .click({ position: { x: 70, y: 15 } });
    await page.getByRole("button", { name: "添加当前选区" }).click();
  }

  await selectA1AndAdd();
  await page
    .locator(".luckysheet-sheets-item-name", { hasText: "Sheet2" })
    .click();
  await expect(
    page.getByText("当前 Sheet：Sheet2", { exact: false }),
  ).toBeVisible();
  await selectA1AndAdd();
  await expect(page.locator(".ts-selection-list article")).toHaveCount(2);
  await expect(page.locator(".ts-selection-list")).toContainText(
    "Sheet1!A1:A1",
  );
  await expect(page.locator(".ts-selection-list")).toContainText(
    "Sheet2!A1:A1",
  );

  await page.getByRole("button", { name: "返回", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "保存测试集修改？" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "取消", exact: true }).click();
  await expect(page.locator(".ts-selection-list article")).toHaveCount(2);
  await page.getByRole("button", { name: "返回", exact: true }).click();
  await page.getByRole("button", { name: "保存并离开", exact: true }).click();
  await page
    .getByRole("textbox", { name: /测试集名称/ })
    .fill("E2E 跨 Sheet 测试集");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "E2E 跨 Sheet 测试集", exact: true }),
  ).toBeVisible();

  const list = await request.get(
    "/api/test-sets?page=1&page_size=100&name_query=E2E%20%E8%B7%A8%20Sheet",
  );
  const listPayload = await list.json();
  const createdId = listPayload.items[0].id;
  const detail = await request.get(`/api/test-sets/${createdId}`);
  const detailPayload = await detail.json();
  expect(detailPayload.test_set.cases.map((item) => item.values.col_1)).toEqual(
    ["Sheet1-value", "Sheet2-value"],
  );
  await request.delete(`/api/test-sets/${createdId}`);
  expect(errors).toEqual([]);
});

test("测试集详情仅显式保存并支持三种离开选择", async ({ page, request }) => {
  const errors = captureErrors(page);
  const created = await request.post("/api/test-sets", {
    data: {
      name: "E2E 未保存保护",
      description: "原说明",
      columns: ["question", "expected"],
      cases: [{ values: { question: "hello", expected: "HELLO" } }],
    },
  });
  const createdRecord = (await created.json()).test_set;

  async function readSaved() {
    const response = await request.get(`/api/test-sets/${createdRecord.id}`);
    return (await response.json()).test_set;
  }

  await page.goto("/");
  await page
    .getByRole("button", { name: "E2E 未保存保护", exact: true })
    .click();
  await page
    .getByRole("button", { name: "编辑测试集名称：E2E 未保存保护" })
    .click();
  await page.getByRole("textbox", { name: "测试集名称" }).fill("E2E 草稿名称");
  await page.getByRole("textbox", { name: "测试集名称" }).press("Enter");
  expect((await readSaved()).name).toBe("E2E 未保存保护");

  await page.getByRole("button", { name: "返回", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "保存测试集修改？" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "取消", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "编辑测试集名称：E2E 草稿名称" }),
  ).toBeVisible();

  await page.getByRole("button", { name: "返回", exact: true }).click();
  await page.getByRole("button", { name: "不保存并离开" }).click();
  await expect(
    page.getByRole("button", { name: "E2E 未保存保护", exact: true }),
  ).toBeVisible();
  expect((await readSaved()).name).toBe("E2E 未保存保护");

  await page
    .getByRole("button", { name: "E2E 未保存保护", exact: true })
    .click();
  await page
    .getByRole("button", { name: "编辑测试集名称：E2E 未保存保护" })
    .click();
  await page
    .getByRole("textbox", { name: "测试集名称" })
    .fill("E2E 已显式保存");
  await page.getByRole("textbox", { name: "测试集名称" }).press("Enter");
  await page.getByRole("button", { name: "手动添加" }).click();
  await page.getByRole("textbox", { name: "新用例 question" }).fill("world");
  await page.getByRole("textbox", { name: "新用例 expected" }).fill("WORLD");
  await page.locator(".ts-toolbar .ts-search input").click();
  expect((await readSaved()).cases).toHaveLength(1);

  await page.getByRole("button", { name: "供应商管理" }).click();
  await page.getByRole("button", { name: "保存并离开", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "供应商管理", exact: true }),
  ).toBeVisible();
  const saved = await readSaved();
  expect(saved.name).toBe("E2E 已显式保存");
  expect(saved.cases.map((item) => item.values.question)).toEqual([
    "world",
    "hello",
  ]);
  await request.delete(`/api/test-sets/${createdRecord.id}`);
  expect(errors).toEqual([]);
});

test("Excel 追加草稿可在切换目录时保存并离开", async ({ page, request }) => {
  const errors = captureErrors(page);
  const created = await request.post("/api/test-sets", {
    data: {
      name: "E2E Excel 追加保护",
      description: "",
      columns: ["question"],
      cases: [{ values: { question: "first" } }],
    },
  });
  const record = (await created.json()).test_set;
  const workbook = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(
    workbook,
    XLSX.utils.aoa_to_sheet([["second"]]),
    "追加页",
  );
  const buffer = XLSX.write(workbook, { bookType: "xlsx", type: "buffer" });

  await page.goto("/");
  await page
    .getByRole("button", { name: "E2E Excel 追加保护", exact: true })
    .click();
  await page.getByRole("button", { name: "从 .xlsx 添加" }).click();
  await page.locator('input[type="file"][accept=".xlsx"]').setInputFiles({
    name: "append.xlsx",
    mimeType:
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    buffer,
  });
  await page
    .locator("#luckysheet-sheettable_0")
    .click({ position: { x: 70, y: 15 } });
  await page.getByRole("button", { name: "添加当前选区" }).click();
  await page.getByRole("button", { name: "工作流管理" }).click();
  await expect(
    page.getByRole("heading", { name: "保存测试集修改？" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "保存并离开", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "工作流管理", exact: true }),
  ).toBeVisible();

  const detail = await request.get(`/api/test-sets/${record.id}`);
  const saved = (await detail.json()).test_set;
  expect(saved.cases.map((item) => item.values.question)).toEqual([
    "first",
    "second",
  ]);
  await request.delete(`/api/test-sets/${record.id}`);
  expect(errors).toEqual([]);
});

test("供应商可在 React 页面创建、编辑和删除", async ({ page }) => {
  const errors = captureErrors(page);
  await page.route("**/api/model-providers/test-model", async (route) => {
    const body = route.request().postDataJSON();
    await new Promise((resolve) => setTimeout(resolve, 200));
    if (body.model_name === "inactive-model") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          available: false,
          latency_ms: 42,
          status_code: 502,
          output: null,
          response_body: "{}",
          error: "HTTP 502",
        }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        available: true,
        latency_ms: 42,
        status_code: 200,
        output: "模型连接正常。",
        response_body: "{}",
        error: null,
      }),
    });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "供应商管理" }).click();
  await page.getByRole("button", { name: "新建供应商" }).click();
  expect(
    await page
      .locator("#model-provider-form")
      .evaluate((form) =>
        Array.from(
          form.querySelectorAll(
            "#model-provider-name, #model-provider-website, #model-provider-protocol, #model-provider-base-url, #model-provider-api-key, #model-provider-proxy-mode",
          ),
        ).map((control) => control.id),
      ),
  ).toEqual([
    "model-provider-name",
    "model-provider-website",
    "model-provider-protocol",
    "model-provider-base-url",
    "model-provider-api-key",
    "model-provider-proxy-mode",
  ]);
  expect(
    await page.locator("#model-provider-form").evaluate((form) => {
      const protocolRight = form
        .querySelector("#model-provider-protocol")
        .getBoundingClientRect().right;
      const sslRight = form
        .querySelector(".model-provider-ssl-setting")
        .getBoundingClientRect().right;
      return Math.abs(protocolRight - sslRight);
    }),
  ).toBeLessThanOrEqual(1);
  await page.locator("#model-provider-name").fill("E2E Provider");
  await page.locator("#model-provider-api-key").fill("test-secret");
  await page.locator("#model-provider-base-url").fill("https://example.com/v1");
  await expect(
    page.locator(".model-provider-validation-heading small"),
  ).toHaveText("https://example.com/v1/chat/completions");
  await expect(page.locator(".model-provider-status")).not.toContainText(
    "推理端点",
  );
  await expect(page.getByText("凭证与网络设置", { exact: true })).toHaveCount(
    0,
  );
  for (const heading of ["基础配置", "连接验证", "已添加模型"]) {
    await expect(
      page.getByRole("heading", { name: heading, exact: true }),
    ).toHaveCSS("font-size", "16px");
  }
  await expect(
    page.locator(".model-provider-validation-heading small"),
  ).toHaveCSS("font-size", "12px");
  await page.locator("#model-provider-add-model").click();
  await page.locator("#model-provider-manual").fill("test-model");
  await page.locator("#model-provider-confirm-model").click();
  const modelTable = page.getByRole("table", { name: "已添加模型列表" });
  await expect(modelTable.getByRole("columnheader")).toHaveText([
    "模型名称",
    "协议",
    "状态",
    "操作",
  ]);
  const activeRow = modelTable
    .getByRole("row")
    .filter({ hasText: "test-model" });
  await expect(activeRow).toContainText("OpenAI Chat Completions");
  const columnOffsets = await modelTable.evaluate((table) => {
    const header = table.querySelector(".model-provider-selected-head");
    const row = table.querySelector(".model-provider-selected-row");
    const textBox = (node) => {
      const range = document.createRange();
      range.selectNodeContents(node);
      return range.getBoundingClientRect();
    };
    const headerBoxes = Array.from(header.children).map(textBox);
    const actionButtons = Array.from(
      row.querySelectorAll(".model-provider-model-actions button"),
    );
    const rowLeft = [
      row
        .querySelector(".model-provider-model-name strong")
        .getBoundingClientRect().left,
      row
        .querySelector(".model-provider-model-state-label")
        .getBoundingClientRect().left,
    ];
    const left = [
      Math.abs(headerBoxes[0].left - rowLeft[0]),
      Math.abs(headerBoxes[2].left - rowLeft[1]),
    ];
    const protocolBox = textBox(
      row.querySelector(".model-provider-model-protocol"),
    );
    const protocolCenter = protocolBox.left + protocolBox.width / 2;
    const headerProtocolCenter =
      headerBoxes[1].left + headerBoxes[1].width / 2;
    const actionLeft = actionButtons[0].getBoundingClientRect().left;
    const actionRight = actionButtons.at(-1).getBoundingClientRect().right;
    const actionCenter = (actionLeft + actionRight) / 2;
    const headerActionCenter = headerBoxes[3].left + headerBoxes[3].width / 2;
    return {
      left,
      protocolCenter: Math.abs(headerProtocolCenter - protocolCenter),
      actionCenter: Math.abs(headerActionCenter - actionCenter),
    };
  });
  expect(columnOffsets.left.every((offset) => offset <= 1)).toBe(true);
  expect(columnOffsets.protocolCenter).toBeLessThanOrEqual(1);
  expect(columnOffsets.actionCenter).toBeLessThanOrEqual(1);
  await expect(activeRow.locator(".model-provider-model-state")).toHaveText(
    "Unknown",
  );
  await activeRow.getByRole("button", { name: "测试 test-model" }).click();
  await expect(
    activeRow.getByRole("button", { name: "正在测试 test-model" }),
  ).toBeDisabled();
  await expect(activeRow.locator(".model-provider-test-spinner")).toBeVisible();
  await expect(activeRow.locator(".model-provider-model-state")).toHaveText(
    "Active",
  );
  await expect(activeRow.locator(".model-provider-model-state")).toHaveClass(
    "model-provider-model-state is-active",
  );

  await page.locator("#model-provider-manual").fill("inactive-model");
  await page.locator("#model-provider-confirm-model").click();
  const inactiveRow = modelTable
    .getByRole("row")
    .filter({ hasText: "inactive-model" });
  await inactiveRow
    .getByRole("button", { name: "测试 inactive-model" })
    .click();
  await expect(
    inactiveRow.getByRole("button", { name: "正在测试 inactive-model" }),
  ).toBeDisabled();
  await expect(inactiveRow.locator(".model-provider-model-state")).toHaveText(
    "Inactive",
  );
  await expect(inactiveRow.locator(".model-provider-model-state")).toHaveClass(
    "model-provider-model-state is-inactive",
  );
  await page.locator("#model-provider-save").click();
  await page.waitForTimeout(300);
  expect(errors).toEqual([]);
  await expect(
    page.getByRole("button", { name: "E2E Provider" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "E2E Provider" }).click();
  await page.locator("#model-provider-name").fill("E2E Provider Updated");
  await page.locator("#model-provider-save").click();
  await page.waitForTimeout(300);
  expect(errors).toEqual([]);
  await expect(
    page.getByRole("button", { name: "E2E Provider Updated" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "删除模型供应商" }).click();
  await page.getByRole("button", { name: "删除", exact: true }).click();
  await expect(page.getByText("尚未添加模型供应商")).toBeVisible();
  expect(errors).toEqual([]);
});

test("测试集可编辑保存且工作流可从画布创建", async ({ page, request }) => {
  const errors = captureErrors(page);
  const created = await request.post("/api/test-sets", {
    data: {
      name: "E2E 浏览器测试集",
      description: "浏览器编辑前",
      columns: ["question", "expected"],
      cases: [{ values: { question: "hello", expected: "HELLO" } }],
    },
  });
  expect(created.ok()).toBeTruthy();

  await page.goto("/");
  await page.getByRole("button", { name: "测试集管理" }).click();
  await page
    .getByRole("button", { name: "E2E 浏览器测试集", exact: true })
    .click();
  await page
    .getByRole("button", { name: "编辑测试集名称：E2E 浏览器测试集" })
    .click();
  await page
    .getByRole("textbox", { name: "测试集名称" })
    .fill("E2E 测试集已编辑");
  await page.getByRole("textbox", { name: "测试集名称" }).press("Enter");
  await page
    .getByRole("textbox", { name: "用例 1 expected" })
    .fill("HELLO UPDATED");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "编辑测试集名称：E2E 测试集已编辑" }),
  ).toBeVisible();

  await page.getByRole("button", { name: "工作流管理" }).click();
  await page.locator("#btn-workflow-add").click();
  await expect(page.getByLabel("工作流画布")).toBeVisible();
  await page
    .getByRole("button", { name: "编辑工作流名称：未命名工作流" })
    .click();
  await page
    .getByRole("textbox", { name: "工作流名称" })
    .fill("E2E 画布工作流");
  await page.getByRole("textbox", { name: "工作流名称" }).press("Enter");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await page.getByRole("button", { name: "返回", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "E2E 画布工作流", exact: true }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test("LLM 上下文支持 Markdown 高亮并原样保存", async ({ page, request }) => {
  const errors = captureErrors(page);
  const editorText = (editor) =>
    editor
      .locator(".cm-line")
      .allTextContents()
      .then((lines) => lines.join("\n"));
  await page.goto("/");
  await page.getByRole("button", { name: "工作流管理" }).click();
  await page.locator("#btn-workflow-add").click();
  await expect(page.getByLabel("工作流画布")).toBeVisible();
  await page
    .getByRole("button", { name: "编辑工作流名称：未命名工作流" })
    .click();
  await page
    .getByRole("textbox", { name: "工作流名称" })
    .fill("E2E LLM 上下文编辑");
  await page.getByRole("textbox", { name: "工作流名称" }).press("Enter");

  await page.getByRole("button", { name: "快速插入节点" }).first().click();
  await page
    .locator(".wf-edge-picker")
    .getByRole("menuitem", { name: "LLM" })
    .click();
  const addedNode = page.locator(".react-flow__node").last();
  await addedNode.getByRole("button", { name: "配置 LLM" }).click();

  const inspector = page.getByLabel("节点配置");
  const systemEditor = inspector.getByLabel("SYSTEM 消息内容");
  const userEditor = inspector.getByLabel("USER 消息内容");
  await expect(
    inspector.locator(".wf-markdown-editor .cm-placeholder").first(),
  ).toHaveText("为对话提供高层指导(通过${变量名}引用上下文)");
  await expect(
    inspector.locator(".wf-markdown-editor .cm-placeholder").nth(1),
  ).toHaveText(
    "向模型提供指令、查询或任何基于文本的输入(通过${变量名}引用上下文)",
  );
  expect(
    await inspector
      .locator(".wf-markdown-editor")
      .first()
      .evaluate((element) => ({
        minHeight: getComputedStyle(element).minHeight,
        fontSize: getComputedStyle(element.querySelector(".cm-editor"))
          .fontSize,
      })),
  ).toEqual({ minHeight: "140px", fontSize: "14px" });

  const expandButton = inspector.getByRole("button", {
    name: "放大编辑 SYSTEM 上下文",
  });
  await expandButton.click();
  const dialog = page.getByRole("dialog", { name: "编辑 SYSTEM 上下文" });
  const expandedEditor = dialog.getByLabel("SYSTEM 上下文放大编辑器");
  await expect(dialog).toBeVisible();
  await expect(expandedEditor).toBeFocused();

  const viewport = page.viewportSize();
  const dialogBox = await dialog.boundingBox();
  expect(dialogBox.width).toBeGreaterThanOrEqual(viewport.width * 0.78);
  expect(dialogBox.width).toBeLessThanOrEqual(viewport.width * 0.82);
  expect(dialogBox.height).toBeGreaterThanOrEqual(viewport.height * 0.73);
  expect(dialogBox.height).toBeLessThanOrEqual(viewport.height * 0.77);

  const prompt = [
    "# 审核规则 ✨",
    "",
    "- 根据 ${payload.items[0]} 给出结论",
    "- 明确列出判断依据",
    "",
    "```json",
    '{"status":"可追溯"}',
    "```",
  ].join("\n");
  await expandedEditor.fill(prompt);
  await expect.poll(() => editorText(systemEditor)).toBe(prompt);
  await expect(dialog.locator(".cm-template-variable")).toHaveText(
    "${payload.items[0]}",
  );
  expect(await dialog.locator(".cm-line > span").count()).toBeGreaterThan(3);
  await expect(dialog.getByText(`${prompt.length} 字符`)).toBeVisible();
  await expectNoAxeViolations(page, ".wf-llm-editor-dialog");

  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(expandButton).toBeFocused();
  await expect.poll(() => editorText(systemEditor)).toBe(prompt);
  await expect(inspector.locator(".cm-template-variable")).toHaveText(
    "${payload.items[0]}",
  );

  const addMessage = inspector.getByRole("button", { name: /添加消息/ });
  await addMessage.click();
  await addMessage.click();
  await expect(inspector.locator(".wf-llm-message")).toHaveCount(4);
  const addedUserEditor = inspector.getByLabel("USER 消息内容").nth(1);
  await addedUserEditor.fill("这段非空内容不得被自动删除");
  await inspector.getByRole("button", { name: "保存", exact: true }).click();
  await expect(inspector.locator(".wf-llm-message")).toHaveCount(4);

  const workflowsResponse = await request.get("/api/workflows");
  const workflows = (await workflowsResponse.json()).workflows;
  const workflowId = workflows.find(
    (item) => item.name === "E2E LLM 上下文编辑",
  ).id;
  const savedResponse = await request.get(`/api/workflows/${workflowId}`);
  const saved = (await savedResponse.json()).workflow;
  expect(saved.node_models[0].context.messages[0].content).toBe(prompt);
  expect(saved.workflow.nodes).toHaveLength(1);

  await addedUserEditor.fill(" \n ");
  await inspector.getByRole("button", { name: "保存", exact: true }).click();
  await expect(inspector.locator(".wf-llm-message")).toHaveCount(2);

  await addMessage.click();
  await addMessage.click();
  await page
    .locator(".wf-header-actions")
    .getByRole("button", {
      name: "保存",
      exact: true,
    })
    .click();
  await expect(inspector.locator(".wf-llm-message")).toHaveCount(2);

  await addMessage.click();
  await addMessage.click();
  await inspector.getByRole("button", { name: "关闭", exact: true }).click();
  const leaveDialog = page.getByRole("alertdialog", { name: "保存节点修改？" });
  await expect(leaveDialog).toBeVisible();
  await leaveDialog.getByRole("button", { name: "保存", exact: true }).click();
  await expect(inspector).toBeHidden();
  await page.reload();
  await page.getByRole("button", { name: "工作流管理" }).click();
  await page
    .getByRole("button", { name: "E2E LLM 上下文编辑", exact: true })
    .click();
  await expect(page.getByLabel("工作流画布")).toBeVisible();
  await expect(page.locator(".react-flow__node")).toHaveCount(4);
  await page.getByRole("button", { name: "配置 LLM" }).click();
  await expect(
    page.getByLabel("节点配置").locator(".wf-llm-message"),
  ).toHaveCount(2);
  await expect
    .poll(() =>
      editorText(page.getByLabel("节点配置").getByLabel("SYSTEM 消息内容")),
    )
    .toBe(prompt);
  expect(
    await page
      .getByLabel("节点配置")
      .evaluate((element) => element.scrollWidth > element.clientWidth),
  ).toBe(false);
  await request.delete(`/api/workflows/${workflowId}`);
  expect(errors).toEqual([]);
});

test("五类节点字段间距统一且输出变量类型末置", async ({ page }) => {
  const errors = captureErrors(page);
  await page.goto("/");
  await page.getByRole("button", { name: "工作流管理" }).click();
  await page.locator("#btn-workflow-add").click();

  const inspector = page.getByLabel("节点配置");
  const quickInsert = page.getByRole("button", { name: "快速插入节点" });
  await quickInsert.first().click();
  await page
    .locator(".wf-edge-picker")
    .getByRole("menuitem", { name: "LLM" })
    .click();
  await quickInsert.first().click();
  await page
    .locator(".wf-edge-picker")
    .getByRole("menuitem", { name: "HTTP" })
    .click();
  const configNames = {
    START: "配置 开始",
    SCRIPT: "配置 规则校验",
    LLM: "配置 LLM",
    HTTP: "配置 HTTP",
    END: "配置 结束",
  };

  for (const nodeType of ["START", "SCRIPT", "LLM", "HTTP", "END"]) {
    const node = page.locator(".react-flow__node").filter({
      has: page.getByRole("button", {
        name: configNames[nodeType],
        exact: true,
      }),
    });
    await expect(node).toHaveCount(1);
    await node
      .getByRole("button", { name: configNames[nodeType], exact: true })
      .click();
    await expect(inspector).toHaveAttribute("data-node-type", nodeType);
    expect(
      await inspector.locator(".wf-editor-form-grid").evaluate((element) =>
        Array.from(element.querySelectorAll(":scope > label")).map((field) => {
          const label = field
            .querySelector(":scope > span")
            .getBoundingClientRect();
          const control = field
            .querySelector(
              ":scope > input, :scope > textarea, :scope > select, :scope > button",
            )
            .getBoundingClientRect();
          return Math.round(control.left - label.right);
        }),
      ),
    ).toEqual([10, 10]);

    if (nodeType === "START") {
      expect(
        await inspector.locator(".wf-start-input-row").evaluate((element) => {
          const fields = Array.from(element.querySelectorAll(":scope > label"));
          return {
            fields: fields.map((field) => field.dataset.startField),
            visibleGaps: fields.map((field) => {
              const label = field
                .querySelector(":scope > span")
                .getBoundingClientRect();
              const control = field
                .querySelector(":scope > input, :scope > select")
                .getBoundingClientRect();
              return Math.round(control.left - label.right);
            }),
          };
        }),
      ).toEqual({
        fields: ["name", "value", "type"],
        visibleGaps: [10, 10, 10],
      });
    }

    if (["SCRIPT", "LLM", "HTTP"].includes(nodeType)) {
      await inspector
        .getByRole("button", { name: "输出变量", exact: true })
        .click();

      const outputList = inspector.locator(".wf-output-variable-list");
      await expect(outputList).toHaveAttribute("data-node-type", nodeType);
      expect(
        await outputList.evaluate((element) => {
          const row = element.querySelector(".wf-output-variable-row");
          const fields = Array.from(row.querySelectorAll(":scope > label"));
          return {
            fields: fields.map((field) => field.dataset.outputField),
            visibleGaps: fields.map((field) => {
              const label = field
                .querySelector(":scope > span")
                .getBoundingClientRect();
              const control = field
                .querySelector(":scope > input, :scope > select")
                .getBoundingClientRect();
              return Math.round(control.left - label.right);
            }),
            overflow: element.scrollWidth > element.clientWidth,
          };
        }),
      ).toEqual({
        fields: ["name", "source", "type"],
        visibleGaps: [10, 10, 10],
        overflow: false,
      });
    }

    await inspector.getByRole("button", { name: "关闭", exact: true }).click();
    await expect(inspector).toBeHidden();
  }

  await page.evaluate(() =>
    document.documentElement.setAttribute("data-theme", "dark"),
  );
  const httpNode = page.locator(".react-flow__node").filter({
    has: page.getByRole("button", { name: "配置 HTTP", exact: true }),
  });
  await httpNode
    .getByRole("button", { name: "配置 HTTP", exact: true })
    .click();
  await inspector
    .getByRole("button", { name: "输出变量", exact: true })
    .click();
  const darkList = inspector.locator(".wf-output-variable-list");
  expect(
    await darkList.evaluate((element) => ({
      nodeType: element.dataset.nodeType,
      visibleGap: (() => {
        const field = element.querySelector('[data-output-field="type"]');
        const label = field
          .querySelector(":scope > span")
          .getBoundingClientRect();
        const control = field
          .querySelector(":scope > select")
          .getBoundingClientRect();
        return Math.round(control.left - label.right);
      })(),
      overflow: element.scrollWidth > element.clientWidth,
    })),
  ).toEqual({ nodeType: "HTTP", visibleGap: 10, overflow: false });
  expect(errors).toEqual([]);
});

test("双击 HTTP 只打开设置且日志按需单次加载不污染状态", async ({
  page,
  request,
}) => {
  const errors = captureErrors(page);
  const id = () => crypto.randomUUID();
  const startId = id();
  const httpId = id();
  const endId = id();
  const workflowName = "E2E HTTP 历史隔离";
  const created = await request.post("/api/workflows", {
    data: {
      name: workflowName,
      description: "",
      nodes: [
        {
          node: {
            id: startId,
            type: "START",
            name: "开始",
            description: "",
            inputs: [],
          },
          position_x: 0,
          position_y: 0,
        },
        {
          node: { id: httpId, type: "HTTP", name: "HTTP", description: "" },
          position_x: 260,
          position_y: 0,
        },
        {
          node: { id: endId, type: "END", name: "结束", description: "" },
          position_x: 520,
          position_y: 0,
        },
      ],
      edges: [
        { id: id(), source_node_id: startId, target_node_id: httpId },
        { id: id(), source_node_id: httpId, target_node_id: endId },
      ],
    },
  });
  expect(created.ok()).toBeTruthy();
  const workflowId = (await created.json()).workflow.workflow.id;
  const started = await request.post(`/api/workflows/${workflowId}/runs`);
  expect(started.ok()).toBeTruthy();
  const executionId = (await started.json()).execution.id;
  await expect
    .poll(async () => {
      const response = await request.get(
        `/api/workflows/${workflowId}/runs/${executionId}`,
      );
      return (await response.json()).execution.status;
    })
    .toBe("FAILED");

  await page.goto("/");
  await page.getByRole("button", { name: "工作流管理" }).click();
  await page.getByRole("button", { name: workflowName, exact: true }).click();
  const httpNode = page.locator(".react-flow__node").filter({
    has: page.getByRole("button", { name: "配置 HTTP", exact: true }),
  });
  await expect(httpNode.locator(".wf-node-status")).toHaveText("PENDING");

  const historyRequests = [];
  page.on("request", (requestEvent) => {
    const url = new URL(requestEvent.url());
    if (
      requestEvent.method() === "GET" &&
      url.pathname.includes(`/api/workflows/${workflowId}/`)
    ) {
      if (
        url.pathname.endsWith("/runs") ||
        /\/runs\/[^/]+\/nodes$/.test(url.pathname)
      ) {
        historyRequests.push(url.pathname);
      }
    }
  });

  await httpNode.dblclick();
  const inspector = page.getByLabel("节点配置");
  await expect(inspector).toHaveAttribute("data-node-type", "HTTP");
  await expect(httpNode.locator(".wf-node-status")).toHaveText("PENDING");
  expect(historyRequests).toEqual([]);

  await inspector.getByRole("button", { name: "日志", exact: true }).click();
  await expect
    .poll(() => historyRequests)
    .toEqual([`/api/workflows/${workflowId}/nodes/${httpId}/runs`]);
  await expect(inspector.locator(".wf-llm-run")).toHaveCount(1);
  await expect(inspector.locator(".wf-llm-run-summary")).toContainText(
    "FAILED",
  );
  await expect(httpNode.locator(".wf-node-status")).toHaveText("PENDING");
  expect(
    historyRequests.some((path) => /\/runs\/[^/]+\/nodes$/.test(path)),
  ).toBe(false);
  expect(errors).toEqual([]);
  await request.delete(`/api/workflows/${workflowId}`);
});

test("节点修改后关闭或切换时可选择保存、不保存或取消", async ({
  page,
  request,
}) => {
  const errors = captureErrors(page);
  const workflowName = "E2E 单节点草稿";
  await page.goto("/");
  await page.getByRole("button", { name: "工作流管理" }).click();
  await page.locator("#btn-workflow-add").click();
  await page
    .getByRole("button", { name: "编辑工作流名称：未命名工作流" })
    .click();
  await page.getByRole("textbox", { name: "工作流名称" }).fill(workflowName);
  await page.getByRole("textbox", { name: "工作流名称" }).press("Enter");

  const pane = page.locator(".react-flow__pane");
  await pane.click({ button: "right", position: { x: 540, y: 180 } });
  await page.getByRole("button", { name: /添加节点/ }).click();
  await page.getByRole("menuitem", { name: "SCRIPT" }).click();
  const addedNodeCandidate = page.locator(".react-flow__node").filter({
    has: page.getByRole("button", { name: "配置 SCRIPT", exact: true }),
  });
  const addedNodeId = await addedNodeCandidate.getAttribute("data-id");
  const addedNode = page.locator(`.react-flow__node[data-id="${addedNodeId}"]`);
  await pane.click({ button: "right", position: { x: 1120, y: 120 } });
  await page.getByRole("button", { name: /添加节点/ }).click();
  await page.getByRole("menuitem", { name: "LLM" }).click();
  const secondNode = page.locator(".react-flow__node").last();
  await addedNode.getByRole("button", { name: "配置 SCRIPT" }).click();
  const inspector = page.getByLabel("节点配置");
  await inspector.getByLabel("名称").fill("关闭前待确认");
  await inspector.getByRole("button", { name: "关闭", exact: true }).click();
  const leaveDialog = page.getByRole("alertdialog", { name: "保存节点修改？" });
  await expect(leaveDialog).toBeVisible();
  await leaveDialog.getByRole("button", { name: "取消", exact: true }).click();
  await expect(inspector.getByLabel("名称")).toHaveValue("关闭前待确认");
  await inspector.getByRole("button", { name: "关闭", exact: true }).click();
  await leaveDialog
    .getByRole("button", { name: "不保存", exact: true })
    .click();
  await expect(inspector).toBeHidden();
  await expect(addedNode).toContainText("SCRIPT");

  const workflowsResponse = await request.get("/api/workflows");
  const workflows = (await workflowsResponse.json()).workflows;
  const workflowId = workflows.find((item) => item.name === workflowName).id;
  const readWorkflow = async () => {
    const response = await request.get(`/api/workflows/${workflowId}`);
    return (await response.json()).workflow;
  };
  let saved = await readWorkflow();
  expect(saved.node_models).toHaveLength(0);
  expect(saved.workflow.edges).toEqual([]);

  await addedNode.getByRole("button", { name: "配置 SCRIPT" }).click();
  await inspector.getByLabel("名称").fill("切换时保存");
  await secondNode
    .getByRole("button", { name: "配置 LLM" })
    .evaluate((button) => button.click());
  await expect(leaveDialog).toBeVisible();
  await leaveDialog.getByRole("button", { name: "保存", exact: true }).click();
  await expect(inspector.getByLabel("名称")).toHaveValue("LLM");
  await inspector.getByRole("button", { name: "关闭", exact: true }).click();

  saved = await readWorkflow();
  expect(saved.node_models).toHaveLength(1);
  expect(saved.node_models[0].name).toBe("切换时保存");
  expect(saved.workflow.edges).toEqual([]);

  await addedNode.getByRole("button", { name: "配置 切换时保存" }).click();
  await inspector.getByLabel("名称").fill("");
  await inspector.getByRole("button", { name: "关闭", exact: true }).click();
  await leaveDialog.getByRole("button", { name: "保存", exact: true }).click();
  await expect(inspector).toBeVisible();
  await expect(leaveDialog).toBeVisible();
  await expect(
    page.getByText("节点名称不能为空", { exact: true }),
  ).toBeVisible();
  saved = await readWorkflow();
  expect(saved.node_models[0].name).toBe("切换时保存");
  await leaveDialog.getByRole("button", { name: "取消", exact: true }).click();

  await inspector.getByLabel("名称").fill("显式保存成功");
  const nodeSaveButton = inspector.getByRole("button", {
    name: "保存",
    exact: true,
  });
  await page.mouse.move(1, 1);
  const lightBackgroundBefore = await nodeSaveButton.evaluate(
    (button) => getComputedStyle(button).backgroundColor,
  );
  await nodeSaveButton.click();
  await page.mouse.move(1, 1);
  await expect(page.locator(".wf-node-save-toast")).toContainText(
    "显式保存成功 已保存",
  );
  await expect(addedNode).not.toContainText("已保存");
  await expect(nodeSaveButton).not.toHaveClass(/is-saved/);
  await expect
    .poll(() =>
      nodeSaveButton.evaluate(
        (button) => getComputedStyle(button).backgroundColor,
      ),
    )
    .toBe(lightBackgroundBefore);
  saved = await readWorkflow();
  expect(saved.node_models).toHaveLength(1);
  expect(saved.node_models[0].name).toBe("显式保存成功");
  expect(saved.workflow.edges).toEqual([]);

  await page.evaluate(() =>
    document.documentElement.setAttribute("data-theme", "dark"),
  );
  await page.mouse.move(1, 1);
  const darkBackgroundBefore = await nodeSaveButton.evaluate(
    (button) => getComputedStyle(button).backgroundColor,
  );
  await nodeSaveButton.click();
  await page.mouse.move(1, 1);
  await expect(nodeSaveButton).not.toHaveClass(/is-saved/);
  await expect
    .poll(() =>
      nodeSaveButton.evaluate(
        (button) => getComputedStyle(button).backgroundColor,
      ),
    )
    .toBe(darkBackgroundBefore);

  await page.reload();
  await page.getByRole("button", { name: "工作流管理" }).click();
  await page.getByRole("button", { name: workflowName, exact: true }).click();
  await expect(page.locator(".react-flow__node")).toHaveCount(1);
  await expect(page.locator(".react-flow__node")).toContainText("显式保存成功");
  await page.getByRole("button", { name: "运行", exact: true }).click();
  await expect(page.getByText(/Workflow 必须恰好包含一个 START/)).toBeVisible();
  expect(errors).toEqual([]);
});

test("画布已有开始和结束节点时右键菜单不再提供重复系统节点", async ({
  page,
}) => {
  const errors = captureErrors(page);
  await page.goto("/");
  await page.getByRole("button", { name: "工作流管理" }).click();
  await page.locator("#btn-workflow-add").click();

  const pane = page.locator(".react-flow__pane");
  await pane.click({ button: "right", position: { x: 540, y: 180 } });
  await page.getByRole("button", { name: /添加节点/ }).click();
  const menu = page.getByTestId("pane-context-menu");
  await expect(menu.getByRole("menuitem", { name: "START" })).toHaveCount(0);
  await expect(menu.getByRole("menuitem", { name: "END" })).toHaveCount(0);
  await expect(menu.getByRole("menuitem", { name: "SCRIPT" })).toBeVisible();
  await expect(menu.getByRole("menuitem", { name: "LLM" })).toBeVisible();
  await expect(menu.getByRole("menuitem", { name: "HTTP" })).toBeVisible();

  await pane.click({ position: { x: 80, y: 80 } });
  const startNode = page.locator(".react-flow__node").filter({
    has: page.getByRole("button", { name: "配置 开始", exact: true }),
  });
  await startNode.click({ button: "right" });
  await page
    .getByTestId("node-context-menu")
    .getByText("删除", { exact: true })
    .click();
  await pane.click({ button: "right", position: { x: 540, y: 180 } });
  await page.getByRole("button", { name: /添加节点/ }).click();
  await expect(menu.getByRole("menuitem", { name: "START" })).toBeVisible();
  await expect(menu.getByRole("menuitem", { name: "END" })).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("顶部保存拒绝不完整图且不覆盖工作流草稿", async ({ page, request }) => {
  const errors = captureErrors(page);
  const workflowName = "E2E 结构完整性";
  await page.goto("/");
  await page.getByRole("button", { name: "工作流管理" }).click();
  await page.locator("#btn-workflow-add").click();
  await page
    .getByRole("button", { name: "编辑工作流名称：未命名工作流" })
    .click();
  await page.getByRole("textbox", { name: "工作流名称" }).fill(workflowName);
  await page.getByRole("textbox", { name: "工作流名称" }).press("Enter");

  const pane = page.locator(".react-flow__pane");
  await pane.click({ button: "right", position: { x: 1120, y: 120 } });
  await page.getByRole("button", { name: /添加节点/ }).click();
  await page.getByRole("menuitem", { name: "SCRIPT" }).click();
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(
    page.getByText("START 必须是唯一根节点且不能有入边", { exact: true }),
  ).toBeVisible();

  const listing = await request.get(
    `/api/workflows?name_query=${encodeURIComponent(workflowName)}`,
  );
  const workflow = (await listing.json()).workflows.find(
    (item) => item.name === workflowName,
  );
  const detail = await request.get(`/api/workflows/${workflow.id}`);
  const saved = (await detail.json()).workflow;
  expect(saved.node_models).toHaveLength(0);
  expect(saved.workflow.edges).toEqual([]);
  expect(
    errors.filter((message) => !message.includes("400 (Bad Request)")),
  ).toEqual([]);
});

test("再次启动工作流时全部节点先重置为 PENDING", async ({ page, request }) => {
  const errors = captureErrors(page);
  const id = () => crypto.randomUUID();
  const start = id();
  const script = id();
  const end = id();
  const created = await request.post("/api/workflows", {
    data: {
      name: "E2E 运行状态重置",
      description: "",
      nodes: [
        {
          node: {
            id: start,
            type: "START",
            name: "START",
            description: "",
            inputs: [{ name: "question", type: "string", value: "hello" }],
          },
          position_x: 0,
          position_y: 0,
        },
        {
          node: {
            id: script,
            type: "SCRIPT",
            name: "SCRIPT",
            description: "",
            script: 'result = context["question"].upper()',
            outputs: [{ name: "answer", type: "string", source: "result" }],
          },
          position_x: 260,
          position_y: 0,
        },
        {
          node: { id: end, type: "END", name: "END", description: "" },
          position_x: 520,
          position_y: 0,
        },
      ],
      edges: [
        { id: id(), source_node_id: start, target_node_id: script },
        { id: id(), source_node_id: script, target_node_id: end },
      ],
    },
  });
  const workflowId = (await created.json()).workflow.workflow.id;

  await page.goto("/");
  await page.getByRole("button", { name: "工作流管理" }).click();
  await page
    .getByRole("button", { name: "E2E 运行状态重置", exact: true })
    .click();
  const runButton = page.getByRole("button", { name: "运行", exact: true });
  await runButton.click();
  await expect(page.locator(".wf-workflow-timer.is-success")).toBeVisible();
  await expect(page.locator(".wf-node-status.is-success")).toHaveCount(3);

  let releaseSecondRun;
  const secondRunGate = new Promise((resolve) => {
    releaseSecondRun = resolve;
  });
  let holdNextRun = true;
  await page.route(`**/api/workflows/${workflowId}/runs`, async (route) => {
    if (holdNextRun && route.request().method() === "POST") {
      holdNextRun = false;
      await secondRunGate;
    }
    await route.continue();
  });

  await runButton.click();
  const nodeStatuses = page.locator(".wf-node-status");
  await expect(nodeStatuses).toHaveText(["PENDING", "PENDING", "PENDING"]);
  await expect(page.locator(".wf-node-execution span")).toHaveText([
    "0ms",
    "0ms",
    "0ms",
  ]);
  releaseSecondRun();
  await expect(page.locator(".wf-workflow-timer.is-success")).toBeVisible();
  await request.delete(`/api/workflows/${workflowId}`);
  expect(errors).toEqual([]);
});

test("运行节点耗时按共享时钟线性增长并以终态耗时收口", async ({
  page,
  request,
}) => {
  const errors = captureErrors(page);
  const id = () => crypto.randomUUID();
  const startId = id();
  const scriptId = id();
  const endId = id();
  const created = await request.post("/api/workflows", {
    data: {
      name: "E2E 节点线性计时",
      description: "",
      nodes: [
        {
          node: {
            id: startId,
            type: "START",
            name: "START",
            description: "",
            inputs: [],
          },
          position_x: 0,
          position_y: 0,
        },
        {
          node: {
            id: scriptId,
            type: "SCRIPT",
            name: "线性计时",
            description: "",
            script: "import time\ntime.sleep(1.5)\nresult = 'ok'",
            execution: {
              timeout_seconds: 5,
              max_attempts: 0,
              retry_interval_seconds: 0,
              delay_seconds: 0,
            },
            outputs: [{ name: "result", type: "string", source: "result" }],
          },
          position_x: 260,
          position_y: 0,
        },
        {
          node: { id: endId, type: "END", name: "END", description: "" },
          position_x: 520,
          position_y: 0,
        },
      ],
      edges: [
        { id: id(), source_node_id: startId, target_node_id: scriptId },
        { id: id(), source_node_id: scriptId, target_node_id: endId },
      ],
    },
  });
  expect(created.ok()).toBeTruthy();
  const workflowId = (await created.json()).workflow.workflow.id;

  await page.goto("/");
  await page.getByRole("button", { name: "工作流管理" }).click();
  await page
    .getByRole("button", { name: "E2E 节点线性计时", exact: true })
    .click();
  const scriptNode = page.locator(`.react-flow__node[data-id="${scriptId}"]`);
  await page.getByRole("button", { name: "运行", exact: true }).click();
  await expect(scriptNode).toContainText("RUNNING");

  const duration = scriptNode.locator(".wf-node-execution span");
  const samples = [];
  for (let index = 0; index < 5; index += 1) {
    samples.push(await duration.textContent());
    await page.waitForTimeout(140);
  }
  const toMilliseconds = (value) =>
    value.endsWith("ms")
      ? Number(value.slice(0, -2))
      : Number(value.slice(0, -1)) * 1000;
  const sampledMilliseconds = samples.map(toMilliseconds);
  expect(new Set(samples).size).toBeGreaterThanOrEqual(3);
  expect(sampledMilliseconds).toEqual(
    [...sampledMilliseconds].sort((left, right) => left - right),
  );
  expect(
    sampledMilliseconds.at(-1) - sampledMilliseconds[0],
  ).toBeGreaterThanOrEqual(300);

  await expect(scriptNode).toContainText("SUCCESS", { timeout: 8_000 });
  const runs = await request.get(`/api/workflows/${workflowId}/runs`);
  const executionId = (await runs.json()).executions[0].id;
  const nodeRuns = await request.get(
    `/api/workflows/${workflowId}/runs/${executionId}/nodes`,
  );
  const finalDuration = (await nodeRuns.json()).executions.find(
    (execution) => execution.node_id === scriptId,
  ).duration_ms;
  const expectedText =
    finalDuration < 1000
      ? `${Math.round(finalDuration)}ms`
      : `${(Math.round(finalDuration) / 1000).toFixed(1)}s`;
  await expect(duration).toHaveText(expectedText);
  expect(errors).toEqual([]);
});

test("任务可创建、复制、设置定时、启动并查看详情", async ({
  page,
  request,
}) => {
  const errors = captureErrors(page);
  const id = () => crypto.randomUUID();
  const testSet = await request.post("/api/test-sets", {
    data: {
      name: "E2E 测试集",
      description: "",
      columns: ["col_1", "expected"],
      cases: [
        { values: { col_1: "41", expected: "42" } },
        { values: { col_1: "99", expected: "100" } },
      ],
    },
  });
  expect(testSet.ok()).toBeTruthy();
  const testSetId = (await testSet.json()).test_set.id;
  const start = id(),
    script = id(),
    end = id();
  const workflow = await request.post("/api/workflows", {
    data: {
      name: "E2E 工作流",
      description: "",
      nodes: [
        {
          node: {
            id: start,
            type: "START",
            name: "START",
            description: "",
            inputs: [{ name: "start_default", type: "integer", value: 7 }],
          },
          position_x: 0,
          position_y: 0,
        },
        {
          node: {
            id: script,
            type: "SCRIPT",
            name: "SCRIPT",
            description: "",
            script: 'result = context["input_value"] + 1',
            outputs: [{ name: "answer", type: "integer", source: "result" }],
          },
          position_x: 200,
          position_y: 0,
        },
        {
          node: { id: end, type: "END", name: "END", description: "" },
          position_x: 400,
          position_y: 0,
        },
      ],
      edges: [
        { id: id(), source_node_id: start, target_node_id: script },
        { id: id(), source_node_id: script, target_node_id: end },
      ],
    },
  });
  expect(workflow.ok()).toBeTruthy();
  const workflowId = (await workflow.json()).workflow.workflow.id;
  await page.goto("/");
  await page.getByRole("button", { name: "任务调度" }).click();
  await page.getByRole("button", { name: "新建任务" }).click();
  await page.locator("#batch-name").fill("E2E 任务");
  await expect(
    page.locator("#batch-variables .batch-variable-row"),
  ).toHaveCount(1);
  await page.getByLabel("变量 1 Key").fill("input_value");
  const testSetValue = page.getByLabel("变量 1 测试集字段");
  await expect(testSetValue).toHaveAttribute(
    "list",
    "batch-variable-value-options",
  );
  await testSetValue.fill("col_1");
  await page.getByLabel("变量 1 类型").selectOption("integer");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByRole("button", { name: "E2E 任务" })).toBeVisible();
  const row = page.getByRole("row").filter({
    has: page.getByRole("button", { name: "E2E 任务", exact: true }),
  });
  await row.getByRole("button", { name: "拷贝任务" }).click();
  await expect(page.locator("#batch-name")).toHaveValue("E2E 任务_copy");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "E2E 任务_copy" }),
  ).toBeVisible();
  await row.getByRole("button", { name: "定时任务设置" }).click();
  await page.locator("#batch-schedule-cadence").selectOption("WEEKLY");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await row.getByRole("button", { name: "启动任务" }).click();
  await page.getByRole("button", { name: "启动", exact: true }).click();
  const taskListResponse = await request.get("/api/batch-runs");
  const tasks = (await taskListResponse.json()).batches;
  const taskId = tasks.find((item) => item.name === "E2E 任务")?.id;
  expect(taskId).toBeTruthy();
  await expect
    .poll(async () => {
      const response = await request.get(`/api/batch-runs/${taskId}`);
      return (await response.json()).batch.status;
    })
    .toBe("SUCCESS");
  const caseResponse = await request.get(`/api/batch-runs/${taskId}/cases`);
  const executedCases = (await caseResponse.json()).cases;
  expect(executedCases.map((item) => item.initial_context.input_value)).toEqual([
    41, 99,
  ]);
  expect(executedCases.every((item) => !("start_inputs" in item))).toBeTruthy();
  const firstExecutionResponse = await request.get(
    `/api/workflows/${workflowId}/runs/${executedCases[0].workflow_execution_ids[0]}`,
  );
  const firstExecution = (await firstExecutionResponse.json()).execution;
  expect(firstExecution.context.initial).toEqual({ input_value: 41 });
  expect(firstExecution.context.final).toMatchObject({
    input_value: 41,
    start_default: 7,
    answer: 42,
  });
  const frozenStart = firstExecution.structural_snapshot.nodes.find(
    (item) => item.node.type === "START",
  ).node;
  expect(frozenStart.inputs).toEqual([
    { name: "start_default", type: "integer", value: 7 },
  ]);
  await page.getByRole("button", { name: "E2E 任务", exact: true }).click();
  await expect(page.getByRole("heading", { name: "E2E 任务" })).toBeVisible();
  await expect(page.locator(".batch-case-table tbody tr")).toHaveCount(2);
  expect(errors).toEqual([]);
});

test("任务详情可按任务并发数并行启动多条用例", async ({ page, request }) => {
  const errors = captureErrors(page);
  const batchId = await createParallelSingleCaseTask(request);
  await page.goto("/");
  await page.getByRole("button", { name: "任务调度" }).click();
  await page.getByRole("button", { name: "并行单条任务", exact: true }).click();
  await expect(page.locator(".batch-case-table tbody tr")).toHaveCount(3);

  const caseRow = (value) =>
    page.locator(".batch-case-table tbody tr").filter({ hasText: value });
  await caseRow("one").getByRole("button", { name: "执行用例" }).click();
  await expect(
    caseRow("one").getByRole("button", { name: "执行中" }),
  ).toBeVisible();
  await expect(
    caseRow("two").getByRole("button", { name: "执行用例" }),
  ).toBeEnabled();

  await caseRow("two").getByRole("button", { name: "执行用例" }).click();
  await expect(
    caseRow("two").getByRole("button", { name: "执行中" }),
  ).toBeVisible();
  await expect(
    caseRow("three").getByRole("button", { name: "执行用例" }),
  ).toBeEnabled();

  await caseRow("three").getByRole("button", { name: "执行用例" }).click();
  await expect(page.getByText("执行中", { exact: true })).toHaveCount(2);
  await expect(
    caseRow("three").getByRole("button", { name: "排队中" }),
  ).toBeVisible();
  await expect(page.getByText("排队中", { exact: true })).toBeVisible();
  await expectNoAxeViolations(page, ".batch-detail");

  await expect
    .poll(
      async () => {
        const response = await request.get(`/api/batch-runs/${batchId}`);
        return (await response.json()).batch.status;
      },
      { timeout: 12_000 },
    )
    .toBe("SUCCESS");
  await expect(page.getByRole("button", { name: "执行用例" })).toHaveCount(3);
  const casesResponse = await request.get(`/api/batch-runs/${batchId}/cases`);
  const cases = (await casesResponse.json()).cases;
  expect(cases.map((item) => item.status)).toEqual([
    "SUCCESS",
    "SUCCESS",
    "SUCCESS",
  ]);
  expect(cases.map((item) => item.workflow_execution_ids.length)).toEqual([
    1, 1, 1,
  ]);
  expect(errors).toEqual([]);
});

test("任务保存错误精确定位到变量和结果校验字段", async ({ page, request }) => {
  const errors = captureErrors(page);
  await createBatchValidationResources(request, "字段定位");

  await page.goto("/");
  await page.getByRole("button", { name: "任务调度" }).click();
  await page.getByRole("button", { name: "新建任务" }).click();
  await page.locator("#batch-name").fill("字段定位任务");
  await expect(
    page.locator("#batch-variables .batch-variable-row"),
  ).toHaveCount(1);

  await page.getByRole("button", { name: "添加变量" }).click();
  await expect(
    page.locator("#batch-variables .batch-variable-row"),
  ).toHaveCount(2);
  await page.getByLabel("变量 1 Key").fill("another_question");
  await page.getByLabel("变量 2 测试集字段").fill("");
  await page.getByRole("button", { name: "保存", exact: true }).click();

  const variableValue = page.getByLabel("变量 2 测试集字段");
  await expect(variableValue).toHaveAttribute("aria-invalid", "true");
  await expect(page.locator("#batch-variable-1-value-error")).toHaveText(
    "变量注入第 2 行 · Value：请选择测试集字段",
  );
  await expect(variableValue).toBeFocused();
  await expect(page.getByRole("dialog", { name: "新建任务" })).toBeVisible();

  await variableValue.fill("question");
  await page.getByRole("button", { name: "添加规则" }).click();
  await page.getByLabel("校验规则 1 结果路径").fill("answer");
  await page.getByLabel("校验规则 1 运算符").selectOption("REGEX");
  await page.getByLabel("校验规则 1 预期值").fill("[");
  await page.getByRole("button", { name: "保存", exact: true }).click();

  const expectedValue = page.getByLabel("校验规则 1 预期值");
  await expect(expectedValue).toHaveAttribute("aria-invalid", "true");
  await expect(page.locator("#batch-rule-0-expected_value-error")).toHaveText(
    "结果校验第 1 行 · 预期值：正则表达式无效",
  );
  await expect(expectedValue).toBeFocused();
  await expectNoAxeViolations(page, ".radix-dialog-content");

  await expectedValue.fill("ok");
  await page.route("**/api/batch-runs", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    await route.fulfill({
      status: 422,
      contentType: "application/json",
      body: JSON.stringify({
        detail: [
          {
            loc: ["body", "variables", 1, "value"],
            msg: "Field required",
            type: "missing",
          },
          {
            loc: ["body", "evaluation_rules", 0],
            msg: "Value error, 正则表达式无效",
            type: "value_error",
          },
        ],
      }),
    });
  });
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.locator("#batch-variable-1-value-error")).toHaveText(
    "变量注入第 2 行 · Value：不能为空",
  );
  await expect(page.locator("#batch-rule-0-expected_value-error")).toHaveText(
    "结果校验第 1 行 · 预期值：正则表达式无效",
  );
  await expect(variableValue).toBeFocused();
  expect(
    errors.filter((message) => !message.includes("status of 422")),
  ).toEqual([]);
});

test("Radix 弹窗支持 Escape、焦点返回且通过 WCAG A/AA", async ({ page }) => {
  const errors = captureErrors(page);
  await page.goto("/");
  await page.getByRole("button", { name: "任务调度" }).click();
  const trigger = page.getByRole("button", { name: "新建任务" });
  await trigger.focus();
  await trigger.click();
  const dialog = page.getByRole("dialog", { name: "新建任务" });
  await expect(dialog).toBeVisible();
  // 层级防火墙：弹窗中心必须命中弹窗自身，防止被高层容器（如画布 z-index 2000）遮挡
  const hitSelf = await dialog.evaluate((el) => {
    const r = el.getBoundingClientRect();
    const hit = document.elementsFromPoint(
      r.x + r.width / 2,
      r.y + r.height / 2,
    )[0];
    return el === hit || el.contains(hit);
  });
  expect(hitSelf).toBe(true);
  await expectNoAxeViolations(page, ".radix-dialog-content");
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(trigger).toBeFocused();
  expect(errors).toEqual([]);
});
