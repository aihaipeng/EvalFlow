export function normalizeSelectionRange(range) {
  return {
    row: [Math.min(...range.row), Math.max(...range.row)],
    column: [Math.min(...range.column), Math.max(...range.column)],
  };
}

export function buildSheetSelections(source, sheetId, ranges) {
  const sheet = source?.sheets.find((item) => item.id === sheetId);
  if (!source || !sheet) return [];

  return ranges.map(normalizeSelectionRange).map((range) => {
    const rows = [];
    for (let row = range.row[0]; row <= range.row[1]; row += 1) {
      const values = [];
      for (let column = range.column[0]; column <= range.column[1]; column += 1) {
        values.push(sheet.sourceMatrix[row]?.[column] ?? "");
      }
      rows.push({ rowIndex: row, values });
    }
    return {
      id: `${source.id}:${sheet.id}:${range.row.join("-")}:${range.column.join("-")}`,
      sourceId: source.id,
      sourceFile: source.name,
      sheetId: sheet.id,
      sheetName: sheet.name,
      range,
      rows,
      columnCount: range.column[1] - range.column[0] + 1,
    };
  });
}
