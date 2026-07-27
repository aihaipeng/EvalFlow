import assert from 'node:assert/strict';
import test from 'node:test';

import {calculateAlignmentGuides} from '../web/frontend/workflow-alignment.mjs';

const node = (id, x, y, width = 236, height = 112) => ({
    id,
    position: {x, y},
    measured: {width, height},
});

test('shows horizontal and vertical guides within the Dify five pixel threshold', () => {
    const dragging = node('dragging', 103, 104, 200, 80);
    const guides = calculateAlignmentGuides([
        dragging,
        node('horizontal', 400, 100, 180, 90),
        node('vertical', 100, 260, 220, 100),
    ], dragging);

    assert.deepEqual(guides, {
        horizontal: {top: 100, left: 103, width: 477},
        vertical: {top: 104, left: 100, height: 256},
    });
});

test('does not show guides at or beyond five pixels and never mutates node positions', () => {
    const dragging = node('dragging', 105, 105);
    const nodes = [dragging, node('candidate', 100, 100)];
    const before = structuredClone(nodes);

    assert.equal(calculateAlignmentGuides(nodes, dragging), null);
    assert.deepEqual(nodes, before);
});

test('extends each guide across all aligned nodes and the dragging node', () => {
    const dragging = node('dragging', 300, 101, 100, 50);
    const guides = calculateAlignmentGuides([
        node('left', 50, 100, 100, 60),
        dragging,
        node('right', 500, 102, 200, 70),
    ], dragging);

    assert.deepEqual(guides?.horizontal, {top: 100, left: 50, width: 650});
    assert.equal(guides?.vertical, null);
});
