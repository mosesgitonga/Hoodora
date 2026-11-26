import { useCustomMutation } from "@refinedev/core";
import { Alert, Button, Card, Form, Input, List, Space, Typography } from "antd";
import { useState } from "react";
import { Link, useNavigate } from "react-router";

import { AccountTags } from "../components";
import { when } from "../format";
import type { Account } from "../types";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function People() {
  const navigate = useNavigate();
  const { mutateAsync, mutation } = useCustomMutation<Account[]>();
  const [found, setFound] = useState<Account[] | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const lookUp = async ({ phone_number }: { phone_number: string }) => {
    setFailure(null);
    setFound(null);
    try {
      const out = await mutateAsync({
        url: "/users/lookup",
        method: "post",
        values: { phone_number },
        successNotification: false,
        errorNotification: false,
      });
      setFound(out.data as unknown as Account[]);
    } catch (error) {
      setFailure(error instanceof Error ? error.message : "Couldn't look that up.");
    }
  };

  return (
    <div style={{ display: "grid", gap: 16, maxWidth: 720 }}>
      <Card title="Find someone by phone number">
        <Typography.Paragraph type="secondary">
          An exact match on the number, written any usual way (0712…, +254712…). Every look-up is recorded in the audit
          log, and the number is never shown back.
        </Typography.Paragraph>
        <Form layout="inline" onFinish={lookUp} autoComplete="off">
          <Form.Item name="phone_number" rules={[{ required: true, message: "Enter a number." }]}>
            <Input placeholder="0712 345 678" style={{ width: 240 }} inputMode="tel" />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={mutation.isPending}>
            Look up
          </Button>
        </Form>
        {failure ? <Alert type="error" showIcon message={failure} style={{ marginTop: 16 }} /> : null}
        {found && found.length === 0 ? (
          <Alert type="info" showIcon message="Nobody has that number." style={{ marginTop: 16 }} />
        ) : null}
        {found && found.length > 0 ? (
          <List
            style={{ marginTop: 16 }}
            dataSource={found}
            renderItem={(account) => (
              <List.Item actions={[<Link key="open" to={`/people/${account.id}`}>Open</Link>]}>
                <List.Item.Meta
                  title={account.display_name}
                  description={
                    <Space wrap>
                      <AccountTags account={account} />
                      <span>Joined {when(account.created_at)}</span>
                    </Space>
                  }
                />
              </List.Item>
            )}
          />
        ) : null}
      </Card>

      <Card title="Open by ID">
        <Typography.Paragraph type="secondary">
          From a report, the audit log or a ban entry. People are also one click away from anything in the queue.
        </Typography.Paragraph>
        <Form layout="inline" onFinish={({ id }: { id: string }) => navigate(`/people/${id.trim()}`)}>
          <Form.Item name="id" rules={[{ required: true, pattern: UUID, message: "That isn't an account ID." }]}>
            <Input placeholder="3f0c…" style={{ width: 340 }} />
          </Form.Item>
          <Button htmlType="submit">Open</Button>
        </Form>
      </Card>
    </div>
  );
}
