import { Card, Select, Space, Table, Tag, Typography } from "antd";
import { useState } from "react";
import { useNavigate } from "react-router";

import { EmptyState, ErrorState, Loading } from "../components";
import { TARGET_LABELS, waited, when, words } from "../format";
import { LoadMore, useCursorList } from "../lists";
import { TARGET_TYPES, type QueueItem } from "../types";

export function Queue() {
  const navigate = useNavigate();
  const [kind, setKind] = useState<string | undefined>();
  const list = useCursorList<QueueItem>(
    "queue",
    kind ? [{ field: "target_type", operator: "eq", value: kind }] : [],
  );

  return (
    <Card
      title="Reports queue"
      extra={
        <Select
          allowClear
          placeholder="Everything"
          style={{ width: 180 }}
          value={kind}
          onChange={setKind}
          aria-label="Only show"
          options={TARGET_TYPES.map((value) => ({ value, label: TARGET_LABELS[value] }))}
        />
      }
    >
      <Typography.Paragraph type="secondary">
        One row per thing, worst reason first, then longest waiting. Open one to see it in full and act.
      </Typography.Paragraph>
      {list.isLoading ? (
        <Loading what="Loading the queue" />
      ) : list.isError ? (
        <ErrorState error={list.error} onRetry={list.refetch} title="Couldn't load the queue" />
      ) : list.rows.length === 0 ? (
        <EmptyState title="Nothing is waiting">Reported and held things will appear here.</EmptyState>
      ) : (
        <>
          <Table<QueueItem>
            rowKey={(row) => `${row.target_type}/${row.target_id}`}
            dataSource={list.rows}
            pagination={false}
            onRow={(row) => ({
              onClick: () => navigate(`/queue/${row.target_type}/${row.target_id}`),
              style: { cursor: "pointer" },
            })}
            columns={[
              {
                title: "What",
                key: "what",
                render: (_, row) => (
                  <Space direction="vertical" size={0}>
                    <Tag>{TARGET_LABELS[row.target_type] ?? row.target_type}</Tag>
                    {row.held ? <Tag color="gold">Held</Tag> : null}
                  </Space>
                ),
              },
              {
                title: "Excerpt",
                dataIndex: "excerpt",
                render: (text: string) => text || <Typography.Text type="secondary">No text</Typography.Text>,
              },
              {
                title: "Reasons",
                key: "reasons",
                render: (_, row) =>
                  row.reasons.length ? row.reasons.map((reason) => <Tag key={reason} color="volcano">{words(reason)}</Tag>) : "—",
              },
              {
                title: "Reports",
                key: "reports",
                render: (_, row) => `${row.report_count}${row.trusted_report_count ? ` (${row.trusted_report_count} trusted)` : ""}`,
              },
              { title: "By", key: "author", render: (_, row) => row.author?.display_name ?? "—" },
              {
                title: "Waiting",
                key: "waiting",
                render: (_, row) => <span title={when(row.waiting_since)}>{waited(row.waiting_since)}</span>,
              },
            ]}
          />
          <LoadMore more={list.more} loading={list.loadingMore} />
        </>
      )}
    </Card>
  );
}
