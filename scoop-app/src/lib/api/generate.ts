import { ApiError, API_BASE_URL } from "./client";
import type { AssistEvent, GenerateRequest, ProblemDetail } from "./schema";

/**
 * Asks the API's query assistant to author a query, calling `onEvent` for each
 * server-sent event. openapi-fetch can't consume a stream, so this uses fetch.
 * Resolves when the stream ends; rejects with an ApiError if the request
 * fails before streaming, or an AbortError when `signal` aborts.
 */
export async function streamGenerate(
  connectorId: string,
  body: GenerateRequest,
  {
    signal,
    onEvent,
  }: { signal?: AbortSignal; onEvent: (e: AssistEvent) => void },
): Promise<void> {
  const response = await fetch(
    `${API_BASE_URL}/v1/connectors/${encodeURIComponent(connectorId)}/generate`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify(body),
      signal,
    },
  );
  if (!response.ok || !response.body) {
    const problem = (await response.json().catch(() => undefined)) as
      ProblemDetail | undefined;
    throw new ApiError(response.status, problem);
  }

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    // Events are separated by a blank line; only `data:` lines matter here
    // since each payload carries its own `type`.
    let end: number;
    while ((end = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      const data = frame
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart())
        .join("\n");
      if (data) onEvent(JSON.parse(data) as AssistEvent);
    }
  }
}
