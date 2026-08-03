export function workflowNodeExecutionDuration(
    run,
    previousDurationMs = 0,
    nowMs = Date.now(),
) {
    const reportedDurationMs = Math.max(0, Number(run?.duration_ms) || 0);
    if (run?.status !== 'RUNNING') return reportedDurationMs;
    const startedAtMs = new Date(run.started_at).getTime();
    if (Number.isNaN(startedAtMs)) return Math.max(reportedDurationMs, previousDurationMs);
    return Math.max(reportedDurationMs, previousDurationMs, nowMs - startedAtMs);
}

export function workflowNodeLiveDuration(data, nowMs = Date.now()) {
    return workflowNodeExecutionDuration({
        status: data?.status,
        started_at: data?.executionStartedAt,
        duration_ms: data?.executionDurationMs,
    }, data?.executionDurationMs, nowMs);
}

export function resetWorkflowNodeForRun(node) {
    return {
        ...node,
        data: {
            ...node.data,
            status: 'PENDING',
            executionId: null,
            executionDurationMs: 0,
            executionStartedAt: null,
        },
    };
}
