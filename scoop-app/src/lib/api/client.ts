import createClient from "openapi-fetch";

import type { paths, ProblemDetail } from "./schema";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_SCOOP_API_URL ?? "http://localhost:8000";

/**
 * Calls the Scoop API directly; the API allows this app's origin via CORS
 * (`SCOOP_CORS_ORIGINS` on the API side).
 */
export const api = createClient<paths>({ baseUrl: API_BASE_URL });

/** Thrown by hooks when the API returns a non-2xx response. */
export class ApiError extends Error {
  readonly status: number;
  readonly problem?: ProblemDetail;

  constructor(status: number, problem?: ProblemDetail) {
    super(problem?.detail ?? problem?.title ?? `Request failed (${status})`);
    this.name = "ApiError";
    this.status = status;
    this.problem = problem;
  }
}

/** Return `data` from an openapi-fetch result, or throw an ApiError. */
export async function unwrap<T>(
  request: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await request;
  if (error !== undefined || !response.ok) {
    const problem =
      error && typeof error === "object" && "title" in error
        ? (error as ProblemDetail)
        : undefined;
    throw new ApiError(response.status, problem);
  }
  return data as T;
}

/** `value` if it's an Error, otherwise an Error describing it. */
export function toError(value: unknown): Error {
  return value instanceof Error ? value : new Error(String(value));
}
