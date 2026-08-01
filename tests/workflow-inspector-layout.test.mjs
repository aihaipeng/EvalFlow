import test from 'node:test';
import assert from 'node:assert/strict';

import {clampInspectorPosition} from '../web/frontend/workflow-inspector-layout.mjs';


test('clamps an inspector resized above and outside its canvas', () => {
    assert.deepEqual(clampInspectorPosition({
        x: -30,
        y: -45,
        width: 900,
        height: 620,
        parentWidth: 1200,
        parentHeight: 700,
    }), {x: 14, y: 14});
});


test('clamps the lower-right edge while preserving an in-bounds position', () => {
    assert.deepEqual(clampInspectorPosition({
        x: 420,
        y: 180,
        width: 900,
        height: 620,
        parentWidth: 1200,
        parentHeight: 700,
    }), {x: 286, y: 66});
    assert.deepEqual(clampInspectorPosition({
        x: 24,
        y: 24,
        width: 700,
        height: 500,
        parentWidth: 1200,
        parentHeight: 700,
    }), {x: 24, y: 24});
});
