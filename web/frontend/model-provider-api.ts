import createClient from "openapi-fetch";

import type { components, paths } from "./generated/openapi";
import { unwrap } from "./api-result";

const http = createClient<paths>({ baseUrl: window.location.origin });

export type ModelProviderConfiguration =
  components["schemas"]["ModelProviderConfiguration"];
export type ProviderConnectionRequest =
  components["schemas"]["ProviderConnectionRequest"];
export type ModelAvailabilityRequest =
  components["schemas"]["ModelAvailabilityRequest"];
export type ModelProviderRecord = components["schemas"]["ModelProviderRecord"];
export type ModelProviderSummary =
  components["schemas"]["ModelProviderSummary"];

export interface ProviderLatencyResult {
  latency_ms: number;
  reachable: boolean;
  status_code: number;
}

export interface ProviderModelsResult {
  endpoint: string;
  latency_ms: number;
  models: Array<{ id: string; owned_by?: string }>;
  protocol: string;
}

export interface ModelAvailabilityResult {
  available: boolean;
  error: string | null;
  latency_ms: number;
  output: unknown;
  response_body: string;
  status_code: number | null;
}

export async function listModelProviders(): Promise<ModelProviderSummary[]> {
  return unwrap(await http.GET("/api/model-providers")).providers;
}

export async function getModelProvider(
  providerId: string,
): Promise<ModelProviderRecord> {
  return unwrap(
    await http.GET("/api/model-providers/{provider_id}", {
      params: { path: { provider_id: providerId } },
    }),
  ).provider;
}

export async function saveModelProvider(
  providerId: string | null,
  body: ModelProviderConfiguration,
): Promise<ModelProviderRecord> {
  const result = providerId
    ? await http.PUT("/api/model-providers/{provider_id}", {
        params: { path: { provider_id: providerId } },
        body,
      })
    : await http.POST("/api/model-providers", { body });
  return unwrap(result).provider;
}

export async function deleteModelProvider(
  providerId: string,
): Promise<ModelProviderSummary> {
  return unwrap(
    await http.DELETE("/api/model-providers/{provider_id}", {
      params: { path: { provider_id: providerId } },
    }),
  ).provider;
}

export async function testProviderLatency(
  body: ProviderConnectionRequest,
): Promise<ProviderLatencyResult> {
  return unwrap(
    await http.POST("/api/model-providers/latency", { body }),
  ) as ProviderLatencyResult;
}

export async function fetchProviderModels(
  body: ProviderConnectionRequest,
): Promise<ProviderModelsResult> {
  return unwrap(
    await http.POST("/api/model-providers/models", { body }),
  ) as ProviderModelsResult;
}

export async function testProviderModel(
  body: ModelAvailabilityRequest,
): Promise<ModelAvailabilityResult> {
  return unwrap(
    await http.POST("/api/model-providers/test-model", { body }),
  ) as ModelAvailabilityResult;
}
