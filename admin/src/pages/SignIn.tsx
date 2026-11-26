import { useLogin } from "@refinedev/core";
import { Alert, Button, Card, Form, Input, Typography } from "antd";
import { useState } from "react";

import { config } from "../config";
import { signOutReason } from "../session";

interface Values {
  email: string;
  password: string;
  code: string;
}

const REASONS = {
  idle: `You were signed out after ${config.idleTimeoutMinutes} minutes without activity.`,
  expired: "Your session ended. Sign in again to carry on.",
  signed_out: null,
} as const;

export function SignIn() {
  const { mutate: login, isPending } = useLogin<Values>();
  const [failure, setFailure] = useState<string | null>(null);
  // Why the last session ended, if it did not end by choice.
  const reason = signOutReason();
  const notice = reason ? REASONS[reason] : null;

  const submit = (values: Values) => {
    setFailure(null);
    login(values, {
      onSuccess: (result) => {
        if (!result.success) setFailure(result.error?.message ?? "Those details are not right.");
      },
    });
  };

  return (
    <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: 16, background: "#f5f5f5" }}>
      <Card style={{ width: "100%", maxWidth: 400 }}>
        <div style={{ textAlign: "center", marginBottom: 16 }}>
          <img src="/favicon.svg" alt="" width={48} height={48} />
          <Typography.Title level={3} style={{ marginTop: 8, marginBottom: 0 }}>
            Hoodora admin
          </Typography.Title>
          <Typography.Text type="secondary">For moderators and admins</Typography.Text>
        </div>
        {notice ? <Alert type="info" showIcon message={notice} style={{ marginBottom: 16 }} /> : null}
        <Form<Values> layout="vertical" onFinish={submit} requiredMark={false} autoComplete="off">
          <Form.Item name="email" label="Email" rules={[{ required: true, message: "Enter your email." }]}>
            <Input type="email" autoComplete="username" autoFocus />
          </Form.Item>
          <Form.Item name="password" label="Password" rules={[{ required: true, message: "Enter your password." }]}>
            <Input.Password autoComplete="current-password" />
          </Form.Item>
          <Form.Item
            name="code"
            label="Authenticator code"
            rules={[{ required: true, pattern: /^\d{6}$/, message: "The 6 digits from your authenticator app." }]}
          >
            <Input inputMode="numeric" autoComplete="one-time-code" maxLength={6} placeholder="123456" />
          </Form.Item>
          {failure ? <Alert type="error" showIcon message={failure} style={{ marginBottom: 16 }} /> : null}
          <Button type="primary" htmlType="submit" block loading={isPending}>
            Sign in
          </Button>
        </Form>
      </Card>
    </div>
  );
}
