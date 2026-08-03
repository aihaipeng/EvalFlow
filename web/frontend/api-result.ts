type ApiResult<T> = {
  data?: T;
  error?: unknown;
  response: Response;
};

export interface ApiValidationIssue {
  loc: Array<string | number>;
  msg: string;
  type: string;
}

export class ApiRequestError extends Error {
  readonly status: number;
  readonly issues: ApiValidationIssue[];

  constructor(message: string, status: number, issues: ApiValidationIssue[]) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.issues = issues;
  }
}

function validationIssues(detail: unknown): ApiValidationIssue[] {
  if (!Array.isArray(detail)) return [];
  return detail.flatMap((item) => {
    if (
      !item ||
      typeof item !== "object" ||
      !("loc" in item) ||
      !Array.isArray(item.loc) ||
      !("msg" in item)
    ) {
      return [];
    }
    return [
      {
        loc: item.loc.filter(
          (part: unknown): part is string | number =>
            typeof part === "string" || typeof part === "number",
        ),
        msg: String(item.msg),
        type: "type" in item ? String(item.type) : "",
      },
    ];
  });
}

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
  const rawDetail =
    result.error && typeof result.error === "object" && "detail" in result.error
      ? result.error.detail
      : result.error;
  const detail = describeDetail(rawDetail);
  throw new ApiRequestError(
    detail || result.response.statusText || `HTTP ${result.response.status}`,
    result.response.status,
    validationIssues(rawDetail),
  );
}
