import assert from 'node:assert/strict';
import test from 'node:test';

import {workflowNodeExecutionDuration} from '../web/frontend/workflow-execution-timing.mjs';

test('increments a running node duration from its start time', () => {
    const startedAt = '2026-08-01T08:00:00.000Z';
    const nowMs = Date.parse('2026-08-01T08:00:03.250Z');

    assert.equal(workflowNodeExecutionDuration({
        status: 'RUNNING',
        started_at: startedAt,
        duration_ms: 0,
    }, 0, nowMs), 3250);
});

test('never moves a running node duration backwards', () => {
    assert.equal(workflowNodeExecutionDuration({
        status: 'RUNNING',
        started_at: 'invalid',
        duration_ms: 400,
    }, 750, 1000), 750);
});

test('uses the backend duration after a node finishes', () => {
    assert.equal(workflowNodeExecutionDuration({
        status: 'SUCCESS',
        started_at: '2026-08-01T08:00:00.000Z',
        duration_ms: 1280,
    }, 5000, Date.parse('2026-08-01T08:00:10.000Z')), 1280);
});
