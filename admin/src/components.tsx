// Pieces every screen uses: loading, empty and error states, status tags, and
// the one dialog every action goes through.

import { Alert, Button, Checkbox, DatePicker, Empty, Form, Input, InputNumber, Modal, Result, Select, Space, Spin, Tag } from "antd";
import type { Dayjs } from "dayjs";
import { useState, type ReactNode } from "react";

import { STATUS_LABELS } from "./format";
import type { Account } from "./types";

export function Loading({ what = "Loading" }: { what?: string }) {
  return (
    <div style={{ padding: 48, textAlign: "center" }} role="status">
      <Spin />
      <div style={{ marginTop: 12, color: "rgba(0,0,0,0.45)" }}>{what}…</div>
    </div>
  );
}

export function ErrorState({ error, onRetry, title = "Couldn't load this" }: {
  error: unknown;
  onRetry?: () => void;
  title?: string;
}) {
  const message = error instanceof Error ? error.message : "Something went wrong.";
  return (
    <Result
      status="warning"
      title={title}
      subTitle={message}
      extra={onRetry ? <Button onClick={onRetry}>Try again</Button> : undefined}
    />
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <Empty
      style={{ padding: 32 }}
      description={
        <div>
          <div style={{ fontWeight: 600 }}>{title}</div>
          {children ? <div style={{ marginTop: 4 }}>{children}</div> : null}
        </div>
      }
    />
  );
}

export function AccountTags({ account }: { account: Account }) {
  const colour = { active: "green", suspended: "orange", banned: "red", deletion_pending: "default" }[account.status];
  return (
    <Space size={4} wrap>
      <Tag color={colour}>{STATUS_LABELS[account.status] ?? account.status}</Tag>
      {account.deleted ? <Tag>Deleted</Tag> : null}
      {account.restricted ? <Tag color="gold">Restricted</Tag> : null}
      {account.is_verified_neighbour ? <Tag color="blue">Verified neighbour</Tag> : null}
      {account.badge_locked ? <Tag>Badge locked</Tag> : null}
    </Space>
  );
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------
export type Field =
  | { name: string; label: string; kind: "text" | "textarea"; required?: boolean; min?: number; max?: number; help?: string; initial?: string }
  | { name: string; label: string; kind: "number"; min: number; max: number; initial?: number; help?: string }
  | { name: string; label: string; kind: "date"; required?: boolean; help?: string }
  | { name: string; label: string; kind: "checkbox"; initial?: boolean; help?: string }
  | { name: string; label: string; kind: "select"; options: { value: string; label: string }[]; initial?: string };

export interface ActionProps {
  label: string;
  title: string;
  /** What will happen, in plain words. Shown before anything is sent. */
  consequence: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  fields?: Field[];
  disabled?: boolean;
  onConfirm: (values: Record<string, unknown>) => Promise<unknown>;
  buttonType?: "default" | "primary" | "link";
}

/** Nothing is sent until the dialog's own button is pressed: every action,
 * destructive or not, is confirmed, and asks for its reason where the API takes one. */
export function ActionButton({ label, title, consequence, confirmLabel, danger, fields = [], disabled, onConfirm, buttonType = "default" }: ActionProps) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form] = Form.useForm();

  const close = () => {
    setOpen(false);
    setError(null);
    form.resetFields();
  };

  const submit = async () => {
    let values: Record<string, unknown>;
    try {
      values = await form.validateFields();
    } catch {
      return; // The form shows what is missing.
    }
    setBusy(true);
    setError(null);
    try {
      await onConfirm(values);
      close();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  };

  const initial = Object.fromEntries(
    fields.filter((field) => "initial" in field && field.initial !== undefined).map((field) => [field.name, (field as { initial: unknown }).initial]),
  );

  return (
    <>
      <Button danger={danger} type={buttonType} disabled={disabled} onClick={() => setOpen(true)}>
        {label}
      </Button>
      <Modal
        open={open}
        title={title}
        onCancel={close}
        destroyOnHidden
        footer={[
          <Button key="cancel" onClick={close} disabled={busy}>
            Cancel
          </Button>,
          <Button key="confirm" type="primary" danger={danger} loading={busy} onClick={() => void submit()}>
            {confirmLabel}
          </Button>,
        ]}
      >
        <div style={{ marginBottom: 16 }}>{consequence}</div>
        <Form form={form} layout="vertical" initialValues={initial} preserve={false}>
          {fields.map((field) => (
            <FieldInput key={field.name} field={field} />
          ))}
        </Form>
        {error ? <Alert type="error" showIcon message={error} /> : null}
      </Modal>
    </>
  );
}

function FieldInput({ field }: { field: Field }) {
  switch (field.kind) {
    case "text":
    case "textarea": {
      const rules = [
        ...(field.required ? [{ required: true, message: `${field.label} is needed.` }] : []),
        ...(field.min ? [{ min: field.min, message: `At least ${field.min} characters.` }] : []),
        ...(field.max ? [{ max: field.max, message: `At most ${field.max} characters.` }] : []),
      ];
      return (
        <Form.Item name={field.name} label={field.label} rules={rules} extra={field.help}>
          {field.kind === "text" ? <Input /> : <Input.TextArea rows={3} />}
        </Form.Item>
      );
    }
    case "number":
      return (
        <Form.Item name={field.name} label={field.label} extra={field.help} rules={[{ required: true, message: `${field.label} is needed.` }]}>
          <InputNumber min={field.min} max={field.max} style={{ width: 160 }} />
        </Form.Item>
      );
    case "date":
      return (
        <Form.Item name={field.name} label={field.label} extra={field.help} rules={field.required ? [{ required: true, message: `${field.label} is needed.` }] : []}>
          <DatePicker disabledDate={(day: Dayjs) => day.isBefore(new Date(), "day")} />
        </Form.Item>
      );
    case "checkbox":
      return (
        <Form.Item name={field.name} valuePropName="checked" extra={field.help}>
          <Checkbox>{field.label}</Checkbox>
        </Form.Item>
      );
    case "select":
      return (
        <Form.Item name={field.name} label={field.label}>
          <Select options={field.options} style={{ width: 200 }} />
        </Form.Item>
      );
  }
}
