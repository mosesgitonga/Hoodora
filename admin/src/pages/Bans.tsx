import { useCreate, useDelete } from "@refinedev/core";
import { App, Card, Space, Table, Tabs, Typography } from "antd";
import { Link } from "react-router";

import { ActionButton, EmptyState, ErrorState, Loading } from "../components";
import { shortId, when } from "../format";
import { LoadMore, useCursorList } from "../lists";
import type { BanEntry } from "../types";

function BanList({ resource, empty }: { resource: "bans/phones" | "bans/devices"; empty: string }) {
  const list = useCursorList<BanEntry>(resource);
  const { mutateAsync: remove } = useDelete();
  const { message } = App.useApp();

  if (list.isLoading) return <Loading />;
  if (list.isError) return <ErrorState error={list.error} onRetry={list.refetch} title="Couldn't load the list" />;
  if (list.rows.length === 0) return <EmptyState title={empty} />;
  return (
    <>
      <Table<BanEntry>
        rowKey="id"
        size="small"
        pagination={false}
        dataSource={list.rows}
        columns={[
          { title: "Entry", dataIndex: "id", render: (id: string) => <code>{shortId(id)}</code> },
          { title: "Reason", dataIndex: "reason", render: (text: string | null) => text ?? "—" },
          {
            title: "Account",
            dataIndex: "user_id",
            render: (id: string | null) => (id ? <Link to={`/people/${id}`}>{shortId(id)}</Link> : "—"),
          },
          { title: "Added", dataIndex: "created_at", render: (value: string) => when(value) },
          {
            title: "",
            key: "lift",
            render: (_, row) => (
              <ActionButton
                label="Lift"
                buttonType="link"
                title="Lift this ban?"
                consequence={
                  resource === "bans/phones"
                    ? "The number can sign in, or sign up, again."
                    : "The installation can be used to sign in again."
                }
                confirmLabel="Lift it"
                onConfirm={async () => {
                  await remove({ resource, id: row.id, successNotification: false, errorNotification: false });
                  void message.success("Ban lifted.");
                }}
              />
            ),
          },
        ]}
      />
      <LoadMore more={list.more} loading={list.loadingMore} />
    </>
  );
}

export function Bans() {
  const { mutateAsync: create } = useCreate();
  const { message } = App.useApp();

  return (
    <Card title="Ban lists">
      <Typography.Paragraph type="secondary">
        Entries are keyed hashes. The numbers and devices behind them are never stored, so they can't be shown.
      </Typography.Paragraph>
      <Tabs
        items={[
          {
            key: "phones",
            label: "Phone numbers",
            children: (
              <Space direction="vertical" style={{ width: "100%" }}>
                <ActionButton
                  danger
                  label="Ban a number"
                  title="Ban a phone number?"
                  consequence="Signing in or up from it fails as if the code were wrong."
                  confirmLabel="Ban it"
                  fields={[
                    { name: "phone_number", label: "Phone number", kind: "text", required: true, min: 4, max: 32 },
                    { name: "reason", label: "Reason", kind: "textarea", required: true, min: 3, max: 1000 },
                  ]}
                  onConfirm={async (values) => {
                    await create({ resource: "bans/phones", values, successNotification: false, errorNotification: false });
                    void message.success("Number banned.");
                  }}
                />
                <BanList resource="bans/phones" empty="No numbers are banned" />
              </Space>
            ),
          },
          {
            key: "devices",
            label: "Devices",
            children: (
              <Space direction="vertical" style={{ width: "100%" }}>
                <Typography.Text type="secondary">Devices are added by banning an account.</Typography.Text>
                <BanList resource="bans/devices" empty="No devices are banned" />
              </Space>
            ),
          },
        ]}
      />
    </Card>
  );
}
