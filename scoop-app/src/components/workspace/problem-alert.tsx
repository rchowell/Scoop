import { CircleAlertIcon } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

/** An error as an alert, using the API's problem title and detail when it has them. */
export function ProblemAlert({
  error,
  fallbackTitle,
  mono = false,
}: {
  error: Error;
  fallbackTitle: string;
  mono?: boolean;
}) {
  const problem = error instanceof ApiError ? error.problem : undefined;
  return (
    <Alert variant="destructive">
      <CircleAlertIcon />
      <AlertTitle>{problem?.title ?? fallbackTitle}</AlertTitle>
      <AlertDescription
        className={cn("whitespace-pre-wrap", mono && "font-mono text-xs")}
      >
        {problem?.detail ?? error.message}
      </AlertDescription>
    </Alert>
  );
}
