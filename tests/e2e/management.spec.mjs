import {expect, test} from "@playwright/test";

function captureErrors(page) {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
  return errors;
}

test("四个管理目录可切换且无浏览器错误", async ({page}) => {
  const errors = captureErrors(page);
  await page.goto("/");
  for (const [nav, heading] of [["测试集管理","测试集管理"],["供应商管理","供应商管理"],["工作流管理","工作流管理"],["任务调度","任务调度"]]) {
    await page.getByRole("button", {name: nav}).click();
    await expect(page.getByRole("heading", {name: heading, exact: true})).toBeVisible();
  }
  expect(errors).toEqual([]);
});

test("供应商可在 React 页面创建、编辑和删除", async ({page}) => {
  const errors = captureErrors(page);
  await page.goto("/");
  await page.getByRole("button", {name: "供应商管理"}).click();
  await page.getByRole("button", {name: "新增模型"}).click();
  await page.locator("#model-provider-name").fill("E2E Provider");
  await page.locator("#model-provider-api-key").fill("test-secret");
  await page.locator("#model-provider-base-url").fill("https://example.com/v1");
  await page.locator("#model-provider-add-model").click();
  await page.locator("#model-provider-manual").fill("test-model");
  await page.locator("#model-provider-confirm-model").click();
  await page.locator("#model-provider-save").click();
  await page.waitForTimeout(300);
  expect(errors).toEqual([]);
  await expect(page.getByRole("button", {name: "E2E Provider"})).toBeVisible();
  await page.getByRole("button", {name: "E2E Provider"}).click();
  await page.locator("#model-provider-name").fill("E2E Provider Updated");
  await page.locator("#model-provider-save").click();
  await page.waitForTimeout(300);
  expect(errors).toEqual([]);
  await expect(page.getByRole("button", {name: "E2E Provider Updated"})).toBeVisible();
  await page.getByRole("button", {name: "删除模型供应商"}).click();
  await page.getByRole("button", {name: "删除", exact: true}).click();
  await expect(page.getByText("尚未添加模型供应商")).toBeVisible();
  expect(errors).toEqual([]);
});

test("测试集可编辑保存且工作流可从画布创建", async ({page, request}) => {
  const errors = captureErrors(page);
  const created = await request.post("/api/test-sets", {data: {
    name: "E2E 浏览器测试集",
    description: "浏览器编辑前",
    columns: ["question", "expected"],
    cases: [{values: {question: "hello", expected: "HELLO"}}],
  }});
  expect(created.ok()).toBeTruthy();

  await page.goto("/");
  await page.getByRole("button", {name: "测试集管理"}).click();
  await page.getByRole("button", {name: "E2E 浏览器测试集", exact: true}).click();
  await page.getByRole("button", {name: "编辑测试集名称：E2E 浏览器测试集"}).click();
  await page.getByRole("textbox", {name: "测试集名称"}).fill("E2E 测试集已编辑");
  await page.getByRole("textbox", {name: "测试集名称"}).press("Enter");
  await page.getByRole("textbox", {name: "用例 1 expected"}).fill("HELLO UPDATED");
  await page.getByRole("button", {name: "保存修改"}).click();
  await expect(page.getByRole("button", {name: "编辑测试集名称：E2E 测试集已编辑"})).toBeVisible();

  await page.getByRole("button", {name: "工作流管理"}).click();
  await page.locator("#btn-workflow-add").click();
  await expect(page.getByLabel("工作流画布")).toBeVisible();
  await page.getByRole("button", {name: "编辑工作流名称：未命名工作流"}).click();
  await page.getByRole("textbox", {name: "工作流名称"}).fill("E2E 画布工作流");
  await page.getByRole("textbox", {name: "工作流名称"}).press("Enter");
  await page.getByRole("button", {name: "保存", exact: true}).click();
  await page.getByRole("button", {name: "返回工作流管理"}).click();
  await expect(page.getByRole("button", {name: "E2E 画布工作流", exact: true})).toBeVisible();
  expect(errors).toEqual([]);
});

test("任务可创建、复制、设置定时、启动并查看详情", async ({page, request}) => {
  const errors = captureErrors(page);
  const id = () => crypto.randomUUID();
  const testSet = await request.post("/api/test-sets", {data:{name:"E2E 测试集",description:"",columns:["question","expected"],cases:[{values:{question:"hello",expected:"HELLO"}},{values:{question:"world",expected:"WORLD"}}]}});
  expect(testSet.ok()).toBeTruthy();
  const testSetId = (await testSet.json()).test_set.id;
  const start=id(),script=id(),end=id();
  const workflow = await request.post("/api/workflows", {data:{name:"E2E 工作流",description:"",nodes:[{node:{id:start,type:"START",name:"START",description:"",inputs:[{name:"question",type:"string",value:""}]},position_x:0,position_y:0},{node:{id:script,type:"SCRIPT",name:"SCRIPT",description:"",script:'result = context["question"].upper()',outputs:[{name:"answer",type:"string",source:"result"}]},position_x:200,position_y:0},{node:{id:end,type:"END",name:"END",description:""},position_x:400,position_y:0}],edges:[{id:id(),source_node_id:start,target_node_id:script},{id:id(),source_node_id:script,target_node_id:end}]}});
  expect(workflow.ok()).toBeTruthy();
  await page.goto("/");
  await page.getByRole("button", {name:"任务调度"}).click();
  await page.getByRole("button", {name:"创建任务"}).click();
  await page.locator("#batch-name").fill("E2E 任务");
  await expect(page.locator("#batch-variables .batch-variable-row")).toHaveCount(1);
  await page.getByRole("button", {name:"保存", exact:true}).click();
  await expect(page.getByRole("button", {name:"E2E 任务"})).toBeVisible();
  const row=page.getByRole("row").filter({has:page.getByRole("button", {name:"E2E 任务", exact:true})});
  await row.getByRole("button", {name:"拷贝任务"}).click();
  await expect(page.locator("#batch-name")).toHaveValue("E2E 任务_copy");
  await page.getByRole("button", {name:"保存", exact:true}).click();
  await expect(page.getByRole("button", {name:"E2E 任务_copy"})).toBeVisible();
  await row.getByRole("button", {name:"定时任务设置"}).click();
  await page.locator("#batch-schedule-cadence").selectOption("WEEKLY");
  await page.getByRole("button", {name:"保存设置"}).click();
  await row.getByRole("button", {name:"启动任务"}).click();
  await page.getByRole("button", {name:"启动", exact:true}).click();
  await expect(row.getByRole("button", {name:/停止任务|启动任务/})).toBeVisible();
  await page.getByRole("button", {name:"E2E 任务", exact:true}).click();
  await expect(page.getByRole("heading", {name:"E2E 任务"})).toBeVisible();
  await expect(page.locator(".batch-case-table tbody tr")).toHaveCount(2);
  expect(errors).toEqual([]);
});
