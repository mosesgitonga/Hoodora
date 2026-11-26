import { useCustomMutation, useInvalidate, useList, useUpdate } from "@refinedev/core";
import { Alert, App, Button, Card, Modal, Space, Table, Tag, Typography } from "antd";
import { useState } from "react";

import { ActionButton, EmptyState, ErrorState, Loading } from "../components";
import { when } from "../format";
import { useCodeRequired } from "../options";
import { currentStaff } from "../session";
import type { IssuedCredentials, Staff } from "../types";

/** Shown once, after creating an account or resetting one: the API never
 * shows these again. As text, for typing into the authenticator by hand. */
function Credentials({ issued, onClose }: { issued: IssuedCredentials | null; onClose: () => void }) {
  const needsCode = useCodeRequired();
  if (!issued) return null;
  const copy = (value: string) => void navigator.clipboard?.writeText(value);
  return (
    <Modal open title={`Sign-in details for ${issued.staff.display_name}`} onCancel={onClose} footer={<Button type="primary" onClick={onClose}>I've passed these on</Button>}>
      <Alert type="warning" showIcon message="Shown once. Pass them on privately; they can't be shown again." style={{ marginBottom: 16 }} />
      <Typography.Paragraph>
        Temporary password: <Typography.Text code copyable={{ onCopy: () => copy(issued.temporary_password) }}>{issued.temporary_password}</Typography.Text>
      </Typography.Paragraph>
      <Typography.Paragraph>
        Authenticator key: <Typography.Text code copyable>{issued.totp_secret}</Typography.Text>
      </Typography.Paragraph>
      <Typography.Paragraph type="secondary">
        {needsCode === false
          ? "Sign-in codes are off for now, so the key isn't needed to sign in. Keep it for when they come back: in the authenticator app, enter it by hand, or open this link on the phone:"
          : "In the authenticator app, choose to enter a key by hand and type this key, or open this link on the phone:"}
      </Typography.Paragraph>
      <Typography.Paragraph>
        <Typography.Text code copyable style={{ wordBreak: "break-all" }}>{issued.totp_uri}</Typography.Text>
      </Typography.Paragraph>
    </Modal>
  );
}

export function StaffPage() {
  const { query, result } = useList<Staff>({ resource: "staff", pagination: { mode: "off" }, queryOptions: { retry: false } });
  const { mutateAsync: update } = useUpdate<Staff>();
  const { mutateAsync: custom } = useCustomMutation<IssuedCredentials>();
  const invalidate = useInvalidate();
  const { message } = App.useApp();
  const [issued, setIssued] = useState<IssuedCredentials | null>(null);
  const me = currentStaff();

  const change = async (staff: Staff, values: Partial<Pick<Staff, "role" | "disabled" | "display_name">>, done: string) => {
    await update({ resource: "staff", id: staff.id, values, successNotification: false, errorNotification: false });
    void message.success(done);
  };
  const issue = async (url: string, values: Record<string, unknown>) => {
    const out = await custom({ url, method: "post", values, successNotification: false, errorNotification: false });
    await invalidate({ resource: "staff", invalidates: ["list"] });
    setIssued(out.data as unknown as IssuedCredentials);
  };

  return (
    <Card
      title="Staff"
      extra={
        <ActionButton
          buttonType="primary"
          label="Add a moderator"
          title="Add a staff account"
          consequence="They get a temporary password and an authenticator key, shown to you once."
          confirmLabel="Create account"
          fields={[
            { name: "email", label: "Email", kind: "text", required: true, max: 320 },
            { name: "display_name", label: "Name", kind: "text", required: true, max: 100 },
            {
              name: "role",
              label: "Role",
              kind: "select",
              initial: "moderator",
              options: [
                { value: "moderator", label: "Moderator" },
                { value: "admin", label: "Admin" },
              ],
            },
          ]}
          onConfirm={(values) => issue("/staff", values)}
        />
      }
    >
      <Credentials issued={issued} onClose={() => setIssued(null)} />
      {query.isLoading ? (
        <Loading />
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} title="Couldn't load staff" />
      ) : !result?.data.length ? (
        <EmptyState title="No staff accounts" />
      ) : (
        <Table<Staff>
          rowKey="id"
          pagination={false}
          dataSource={result.data}
          columns={[
            { title: "Name", dataIndex: "display_name" },
            { title: "Email", dataIndex: "email" },
            { title: "Role", dataIndex: "role", render: (role: string) => <Tag color={role === "admin" ? "volcano" : "blue"}>{role === "admin" ? "Admin" : "Moderator"}</Tag> },
            {
              title: "Status",
              key: "status",
              render: (_, staff) => (staff.disabled ? <Tag>Disabled</Tag> : staff.locked ? <Tag color="orange">Locked</Tag> : <Tag color="green">Active</Tag>),
            },
            { title: "Last sign-in", dataIndex: "last_login_at", render: (value: string | null) => when(value) },
            {
              title: "",
              key: "actions",
              render: (_, staff) =>
                staff.id === me?.id ? (
                  <Typography.Text type="secondary">You</Typography.Text>
                ) : (
                  <Space wrap size={0}>
                    <ActionButton
                      buttonType="link"
                      label={staff.role === "admin" ? "Make moderator" : "Make admin"}
                      title={`Change ${staff.display_name}'s role?`}
                      consequence={staff.role === "admin" ? "They lose bans, the ban lists, the audit log, staff and the overview." : "They can ban, manage staff and see the audit log."}
                      confirmLabel="Change role"
                      onConfirm={() => change(staff, { role: staff.role === "admin" ? "moderator" : "admin" }, "Role changed.")}
                    />
                    {staff.disabled ? (
                      <ActionButton
                        buttonType="link"
                        label="Enable"
                        title={`Enable ${staff.display_name}?`}
                        consequence="They can sign in again with their current details."
                        confirmLabel="Enable"
                        onConfirm={() => change(staff, { disabled: false }, "Account enabled.")}
                      />
                    ) : (
                      <ActionButton
                        buttonType="link"
                        danger
                        label="Deactivate"
                        title={`Deactivate ${staff.display_name}?`}
                        consequence="Their sessions end now and they can't sign in until enabled again."
                        confirmLabel="Deactivate"
                        onConfirm={() => change(staff, { disabled: true }, "Account deactivated.")}
                      />
                    )}
                    <ActionButton
                      buttonType="link"
                      danger
                      label="Reset sign-in"
                      title={`Reset ${staff.display_name}'s sign-in?`}
                      consequence="Their password and authenticator key are replaced, their sessions end, and the account unlocks. For a lost phone or a leak."
                      confirmLabel="Reset"
                      onConfirm={() => issue(`/staff/${staff.id}/reset-credentials`, {})}
                    />
                  </Space>
                ),
            },
          ]}
        />
      )}
    </Card>
  );
}
