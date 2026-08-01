import createClient from "openapi-fetch";

import type { components, paths } from "./generated/openapi";
import { unwrap } from "./api-result";

const http = createClient<paths>({ baseUrl: window.location.origin });

export type BatchCreateRequest = components["schemas"]["BatchCreateRequest"];
export type BatchScheduleRequest =
  components["schemas"]["BatchScheduleRequest"];
export type BatchStartRequest = components["schemas"]["BatchStartRequest"];
export type BatchRecord = Record<string, any>;

export interface BatchPreview {
  headers: string[];
  sample_rows: Record<string, unknown>[];
  test_set_id: string;
  test_set_name: string;
  total_rows: number;
}

export interface BatchHistoryItem {
  executed_cases: number;
  finished_at: string | null;
  passed_cases: number;
  started_at: string | null;
  test_set_name: string;
  total_cases: number;
  workflow_name: string;
}

export interface BatchResources {
  flows: Record<string, any>[];
  sets: Record<string, any>[];
}

export async function listBatches(): Promise<BatchRecord[]> {
  return unwrap(await http.GET("/api/batch-runs")).batches as BatchRecord[];
}

export async function getBatch(batchId: string): Promise<BatchRecord> {
  return unwrap(
    await http.GET("/api/batch-runs/{batch_id}", {
      params: { path: { batch_id: batchId } },
    }),
  ).batch as BatchRecord;
}

export async function getBatchCopyName(batchId: string): Promise<string> {
  return unwrap(
    await http.GET("/api/batch-runs/{batch_id}/copy-name", {
      params: { path: { batch_id: batchId } },
    }),
  ).name;
}

export async function listBatchHistory(
  batchId: string,
): Promise<BatchHistoryItem[]> {
  return unwrap(
    await http.GET("/api/batch-runs/{batch_id}/history", {
      params: { path: { batch_id: batchId } },
    }),
  ).history as BatchHistoryItem[];
}

export async function loadBatchResources(): Promise<BatchResources> {
  const [setsResult, workflowsResult] = await Promise.all([
    http.GET("/api/test-sets", {
      params: { query: { page: 1, page_size: 200 } },
    }),
    http.GET("/api/workflows"),
  ]);
  const sets = unwrap(setsResult);
  const workflows = unwrap(workflowsResult);
  return {
    sets: (sets.items || sets.test_sets || []) as Record<string, any>[],
    flows: workflows.workflows as Record<string, any>[],
  };
}

export async function previewBatch(testSetId: string): Promise<BatchPreview> {
  return unwrap(
    await http.POST("/api/batch-runs/preview", {
      body: { test_set_id: testSetId },
    }),
  ) as BatchPreview;
}

export async function saveBatch(
  batchId: string | null,
  body: BatchCreateRequest,
): Promise<BatchRecord> {
  const result = batchId
    ? await http.PUT("/api/batch-runs/{batch_id}", {
        params: { path: { batch_id: batchId } },
        body,
      })
    : await http.POST("/api/batch-runs", { body });
  return unwrap(result).batch as BatchRecord;
}

export async function saveBatchSchedule(
  batchId: string,
  body: BatchScheduleRequest,
): Promise<Record<string, unknown>> {
  return unwrap(
    await http.PUT("/api/batch-runs/{batch_id}/schedule", {
      params: { path: { batch_id: batchId } },
      body,
    }),
  );
}

export async function deleteBatch(batchId: string): Promise<BatchRecord> {
  return unwrap(
    await http.DELETE("/api/batch-runs/{batch_id}", {
      params: { path: { batch_id: batchId } },
    }),
  ).batch as BatchRecord;
}

export async function startBatch(
  batchId: string,
  body: BatchStartRequest,
): Promise<BatchRecord> {
  return unwrap(
    await http.POST("/api/batch-runs/{batch_id}/start", {
      params: { path: { batch_id: batchId } },
      body,
    }),
  ).batch as BatchRecord;
}

export async function cancelBatch(batchId: string): Promise<BatchRecord> {
  return unwrap(
    await http.POST("/api/batch-runs/{batch_id}/cancel", {
      params: { path: { batch_id: batchId } },
    }),
  ).batch as BatchRecord;
}
