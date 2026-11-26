import { useCustomMutation } from "@refinedev/core";
import { Alert, App, Button, Card, Descriptions, Form, Input } from "antd";
import { useState } from "react";

import { currentStaff } from "../session";

interface Values {
  current_password: string;
  new_password: string;
  code: string;
}

export function Account() {
  const me = currentStaff();
  const { mutateAsync, mutation } = useCustomMutation();
  const { message } = App.useApp();
  const [failure, setFailure] = useState<string | null>(null);
  const [form] = Form.useForm<Values>();

  const submit = async (values: Values) => {
    setFailure(null);
    try {
      await mutateAsync({ url: "/me/password", method: "post", values, successNotification: false, errorNotification: false });
      form.resetFields();
      void message.success("Password changed.");
    } catch (error) {
      setFailure(error instanceof Error ? error.message : "Couldn't change the password.");
    }
  };

  return (
    <div style={{ display: "grid", gap: 16, maxWidth: 560 }}>
      <Card title="My account">
        <Descriptions column={1} size="small">
          <Descriptions.Item label="Name">{me?.display_name}</Descriptions.Item>
          <Descriptions.Item label="Email">{me?.email}</Descriptions.Item>
          <Descriptions.Item label="Role">{me?.role === "admin" ? "Admin" : "Moderator"}</Descriptions.Item>
        </Descriptions>
      </Card>
      <Card title="Change password">
        <Form form={form} layout="vertical" onFinish={(values) => void submit(values)} requiredMark={false}>
          <Form.Item name="current_password" label="Current password" rules={[{ required: true, message: "Enter your current password." }]}>
            <Input.Password autoComplete="current-password" />
          </Form.Item>
          <Form.Item name="new_password" label="New password" rules={[{ required: true, min: 12, message: "At least 12 characters." }]}>
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item name="code" label="Authenticator code" rules={[{ required: true, pattern: /^\d{6}$/, message: "The 6 digits from your authenticator app." }]}>
            <Input inputMode="numeric" autoComplete="one-time-code" maxLength={6} />
          </Form.Item>
          {failure ? <Alert type="error" showIcon message={failure} style={{ marginBottom: 16 }} /> : null}
          <Button type="primary" htmlType="submit" loading={mutation.isPending}>
            Change password
          </Button>
        </Form>
      </Card>
    </div>
  );
}
