import assert from "node:assert/strict";
import test from "node:test";

import { buildSheetSelections } from "../web/frontend/test-set-import.mjs";

const source = {
  id: "source-1",
  name: "cases.xlsx",
  sheets: [
    {
      id: "sheet-1",
      name: "Sheet1",
      sourceMatrix: [["first-a", "first-b"]],
    },
    {
      id: "sheet-2",
      name: "Sheet2",
      sourceMatrix: [["second-a", "second-b"]],
    },
  ],
};

test("跨 Sheet 选区始终从回调携带的真实 Sheet 取值", () => {
  const selections = buildSheetSelections(source, "sheet-2", [
    { row: [0, 0], column: [0, 1] },
  ]);

  assert.equal(selections.length, 1);
  assert.equal(selections[0].sheetId, "sheet-2");
  assert.equal(selections[0].sheetName, "Sheet2");
  assert.deepEqual(selections[0].rows, [
    { rowIndex: 0, values: ["second-a", "second-b"] },
  ]);
});

test("未知 Sheet 不回退到第一个 Sheet", () => {
  assert.deepEqual(
    buildSheetSelections(source, "missing-sheet", [
      { row: [0, 0], column: [0, 1] },
    ]),
    [],
  );
});
