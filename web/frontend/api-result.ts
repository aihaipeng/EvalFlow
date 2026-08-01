type ApiResult<T> = {
  data?: T;
  error?: unknown;
  response: Response;
};

function describeDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (item && typeof item === "object" && "msg" in item) {
          return String(item.msg);
        }
        return String(item);
      })
      .join("；");
  }
  if (detail && typeof detail === "object") {
    if ("message" in detail) return String(detail.message);
    return JSON.stringify(detail);
  }
  return "";
}

export function unwrap<T>(result: ApiResult<T>): T {
  if (result.data !== undefined) return result.data;
  const detail =
    result.error && typeof result.error === "object" && "detail" in result.error
      ? describeDetail(result.error.detail)
      : describeDetail(result.error);
  throw new Error(
    detail || result.response.statusText || `HTTP ${result.response.status}`,
  );
}
