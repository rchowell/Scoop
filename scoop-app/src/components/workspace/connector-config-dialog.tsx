"use client";

import * as React from "react";
import { DatabaseIcon, PlusIcon, Trash2Icon } from "lucide-react";

import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  NativeSelect,
  NativeSelectOption,
} from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import {
  toError,
  useConnectorKinds,
  useCreateConnector,
  useDeleteConnector,
  useUpdateConnector,
  type Connector,
  type ConnectorKind,
  type ConnectorKindInfo,
  type ConnectorOption,
} from "@/lib/api";
import {
  useActiveConnector,
  useConnectorList,
} from "@/lib/workspace/use-active-connector";
import { useWorkspace } from "@/lib/workspace/store";

import { ProblemAlert } from "./problem-alert";

/** `null` selects the "new connector" form. */
type Selection = string | null;

export function ConnectorConfigDialog({
  open,
  onOpenChange,
  initialSelection,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initialSelection?: Selection;
}) {
  const { data, isLoading } = useConnectorList();
  const connectors = data?.items ?? [];
  const [selected, setSelected] = React.useState<Selection>(
    initialSelection ?? null,
  );
  const current = connectors.find((c) => c.id === selected);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[min(36rem,calc(100svh-2rem))] flex-col gap-0 p-0 sm:max-w-3xl">
        <DialogHeader className="border-b p-4">
          <DialogTitle>Configure connectors</DialogTitle>
          <DialogDescription>
            Add, edit or remove the databases Scoop can query.
          </DialogDescription>
        </DialogHeader>
        <div className="flex min-h-0 flex-1 flex-col sm:flex-row">
          <nav className="flex shrink-0 flex-col gap-1 border-b p-2 sm:w-56 sm:border-r sm:border-b-0">
            <Button
              variant={selected === null ? "secondary" : "ghost"}
              className="justify-start"
              onClick={() => setSelected(null)}
            >
              <PlusIcon />
              New connector
            </Button>
            <div className="flex max-h-32 flex-col gap-0.5 overflow-y-auto sm:max-h-none">
              {isLoading &&
                Array.from({ length: 3 }, (_, i) => (
                  <Skeleton key={i} className="h-8 w-full" />
                ))}
              {connectors.map((c) => (
                <Button
                  key={c.id}
                  variant={c.id === selected ? "secondary" : "ghost"}
                  className="justify-start"
                  onClick={() => setSelected(c.id)}
                >
                  <DatabaseIcon className="text-muted-foreground" />
                  <span className="truncate">{c.name}</span>
                </Button>
              ))}
            </div>
          </nav>
          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            {/* Keyed so switching connectors resets the form. */}
            <ConnectorForm
              key={current?.id ?? "new"}
              connector={current}
              onSaved={(c) => setSelected(c.id)}
              onDeleted={() => setSelected(null)}
            />
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

type FormValues = Record<string, string | boolean>;

function defaultValues(info: ConnectorKindInfo | undefined): FormValues {
  const values: FormValues = {};
  for (const option of info?.options ?? []) {
    values[option.name] =
      option.type === "boolean"
        ? Boolean(option.default)
        : option.default == null
          ? ""
          : String(option.default);
  }
  return values;
}

function connectorValues(
  connector: Connector,
  info: ConnectorKindInfo | undefined,
): FormValues {
  const values = defaultValues(info);
  for (const [name, value] of Object.entries(connector.options)) {
    values[name] = typeof value === "boolean" ? value : String(value ?? "");
  }
  return values;
}

/** Converts form values to API options; blank optional fields are omitted so the server default applies. */
function toOptions(
  values: FormValues,
  info: ConnectorKindInfo,
): Record<string, unknown> {
  const options: Record<string, unknown> = {};
  for (const option of info.options) {
    const value = values[option.name];
    if (option.type === "boolean") {
      options[option.name] = Boolean(value);
    } else if (typeof value === "string" && value.trim() !== "") {
      options[option.name] = option.type === "integer" ? Number(value) : value;
    }
  }
  return options;
}

function ConnectorForm({
  connector,
  onSaved,
  onDeleted,
}: {
  connector: Connector | undefined;
  onSaved: (connector: Connector) => void;
  onDeleted: () => void;
}) {
  const { dispatch } = useWorkspace();
  const { connector: active, connectors } = useActiveConnector();
  const { data: kindsData, isLoading: kindsLoading } = useConnectorKinds();
  const kinds = kindsData?.kinds ?? [];
  const create = useCreateConnector();
  const update = useUpdateConnector();
  const remove = useDeleteConnector();

  const [name, setName] = React.useState(connector?.name ?? "");
  const [kind, setKind] = React.useState<ConnectorKind | undefined>(
    connector?.kind,
  );
  const effectiveKind = kind ?? kinds[0]?.kind;
  const info = kinds.find((k) => k.kind === effectiveKind);

  // Values are tracked per kind so flipping the kind select doesn't lose input.
  const [valuesByKind, setValuesByKind] = React.useState<
    Partial<Record<ConnectorKind, FormValues>>
  >({});
  const values =
    (effectiveKind && valuesByKind[effectiveKind]) ??
    (connector ? connectorValues(connector, info) : defaultValues(info));
  const setValue = (option: string, value: string | boolean) => {
    if (!effectiveKind) return;
    setValuesByKind((prev) => ({
      ...prev,
      [effectiveKind]: { ...values, [option]: value },
    }));
  };

  const [error, setError] = React.useState<Error | null>(null);
  const [confirmDelete, setConfirmDelete] = React.useState(false);
  const saving = create.isMutating || update.isMutating;

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!info) return;
    setError(null);
    const options = toOptions(values, info);
    try {
      if (connector) {
        const saved = await update.trigger({
          id: connector.id,
          body: { name: name.trim(), options },
        });
        onSaved(saved);
      } else {
        const saved = await create.trigger({
          name: name.trim(),
          kind: info.kind,
          options,
        });
        // A freshly created connector becomes the active one.
        dispatch({ type: "setConnector", connectorId: saved.id });
        onSaved(saved);
      }
    } catch (err) {
      setError(toError(err));
    }
  };

  const onDelete = async () => {
    if (!connector) return;
    setError(null);
    // Move off the connector first so the schema tree doesn't refetch it into a 404.
    const wasActive = active?.id === connector.id;
    const fallback = connectors.find((c) => c.id !== connector.id);
    if (wasActive && fallback) {
      dispatch({ type: "setConnector", connectorId: fallback.id });
    }
    try {
      await remove.trigger({ id: connector.id });
      setConfirmDelete(false);
      onDeleted();
    } catch (err) {
      if (wasActive) {
        dispatch({ type: "setConnector", connectorId: connector.id });
      }
      setConfirmDelete(false);
      setError(toError(err));
    }
  };

  if (kindsLoading) {
    return (
      <div className="flex flex-col gap-3">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-8 w-full" />
        ))}
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-5">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="font-heading text-sm font-medium">
          {connector ? `Edit “${connector.name}”` : "New connector"}
        </h3>
        {connector && (
          <span className="text-xs text-muted-foreground">
            Created {new Date(connector.created_at).toLocaleString()}
          </span>
        )}
      </div>

      <FieldGroup>
        <Field>
          <FieldLabel htmlFor="connector-name">Name</FieldLabel>
          <Input
            id="connector-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Production analytics"
            required
            autoComplete="off"
          />
        </Field>
        <Field>
          <FieldLabel htmlFor="connector-kind">Database</FieldLabel>
          <NativeSelect
            id="connector-kind"
            className="w-full"
            value={effectiveKind ?? ""}
            onChange={(e) => setKind(e.target.value as ConnectorKind)}
            disabled={!!connector}
          >
            {kinds.map((k) => (
              <NativeSelectOption key={k.kind} value={k.kind}>
                {k.name}
              </NativeSelectOption>
            ))}
          </NativeSelect>
          {connector && (
            <FieldDescription>
              The database type can&apos;t be changed after creation.
            </FieldDescription>
          )}
        </Field>
        {info?.options.map((option) => (
          <OptionField
            key={`${info.kind}.${option.name}`}
            option={option}
            value={values[option.name]}
            onChange={(value) => setValue(option.name, value)}
          />
        ))}
      </FieldGroup>

      {error && <ProblemAlert error={error} fallbackTitle="Request failed" />}

      <div className="flex items-center gap-2">
        {connector && (
          <Button
            type="button"
            variant="destructive"
            onClick={() => setConfirmDelete(true)}
          >
            <Trash2Icon />
            Delete
          </Button>
        )}
        <Button
          type="submit"
          className="ml-auto"
          disabled={saving || !info || !name.trim()}
        >
          {saving && <Spinner />}
          {connector ? "Save changes" : "Create connector"}
        </Button>
      </div>

      <AlertDialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete “{connector?.name}”?</AlertDialogTitle>
            <AlertDialogDescription>
              This removes the connector from Scoop. The database itself is not
              affected. Query tabs using it will fall back to another connector.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <Button
              variant="destructive"
              onClick={onDelete}
              disabled={remove.isMutating}
            >
              {remove.isMutating && <Spinner />}
              Delete
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </form>
  );
}

function OptionField({
  option,
  value,
  onChange,
}: {
  option: ConnectorOption;
  value: string | boolean | undefined;
  onChange: (value: string | boolean) => void;
}) {
  const id = `connector-option-${option.name}`;
  const label = (
    <FieldLabel htmlFor={id}>
      {option.name}
      {!option.required && (
        <span className="font-normal text-muted-foreground">(optional)</span>
      )}
    </FieldLabel>
  );

  if (option.type === "boolean") {
    return (
      <Field orientation="horizontal">
        <Switch
          id={id}
          checked={Boolean(value)}
          onCheckedChange={(checked) => onChange(checked)}
        />
        {label}
        <FieldDescription>{option.description}</FieldDescription>
      </Field>
    );
  }

  return (
    <Field>
      {label}
      <Input
        id={id}
        type={
          option.secret
            ? "password"
            : option.type === "integer"
              ? "number"
              : "text"
        }
        inputMode={option.type === "integer" ? "numeric" : undefined}
        step={option.type === "integer" ? 1 : undefined}
        value={typeof value === "string" ? value : ""}
        onChange={(e) => onChange(e.target.value)}
        required={option.required}
        placeholder={
          option.default != null ? String(option.default) : undefined
        }
        autoComplete={option.secret ? "new-password" : "off"}
      />
      {option.description && (
        <FieldDescription>{option.description}</FieldDescription>
      )}
    </Field>
  );
}
