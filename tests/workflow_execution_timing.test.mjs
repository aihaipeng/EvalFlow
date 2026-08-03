import assert from 'node:assert/strict';
import test from 'node:test';

import {
    resetWorkflowNodeForRun,
    workflowNodeExecutionDuration,
    workflowNodeLiveDuration,
} from '../web/frontend/workflow-execution-timing.mjs';

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

test('uses the shared clock to advance only a running node every 100ms', () => {
    const data = {
        status: 'RUNNING',
        executionStartedAt: '2026-08-01T08:00:00.000Z',
        executionDurationMs: 300,
    };

    assert.equal(workflowNodeLiveDuration(
        data,
        Date.parse('2026-08-01T08:00:01.000Z'),
    ), 1000);
    assert.equal(workflowNodeLiveDuration(
        data,
        Date.parse('2026-08-01T08:00:01.100Z'),
    ), 1100);
    assert.equal(workflowNodeLiveDuration({
        ...data,
        status: 'SUCCESS',
        executionDurationMs: 1080,
    }, Date.parse('2026-08-01T08:00:10.000Z')), 1080);
});

test('resets a node for a new workflow run without deleting its history', () => {
    const history = [{id: 'previous-run', status: 'SUCCESS', duration_ms: 1280}];
    const node = {
        id: 'node-1',
        selected: true,
        data: {
            label: '规则校验',
            status: 'FAILED',
            executionId: 'old-execution',
            executionDurationMs: 1280,
            runHistory: history,
        },
    };

    const reset = resetWorkflowNodeForRun(node);

    assert.notEqual(reset, node);
    assert.equal(reset.data.status, 'PENDING');
    assert.equal(reset.data.executionId, null);
    assert.equal(reset.data.executionDurationMs, 0);
    assert.equal(reset.data.executionStartedAt, null);
    assert.equal(reset.data.runHistory, history);
    assert.equal(reset.data.label, '规则校验');
    assert.equal(reset.selected, true);
});
