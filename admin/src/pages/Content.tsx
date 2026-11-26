import { useOne } from "@refinedev/core";
import { Card, Descriptions, Image, Space, Table, Tag, Typography } from "antd";
import { Link, useParams } from "react-router";

import { useAction } from "../actions";
import { AccountTags, ActionButton, EmptyState, ErrorState, Loading } from "../components";
import { shortId, TARGET_LABELS, when, words } from "../format";
import type { ActionOut, ContentDetail, ImageVariant, Report } from "../types";

function medium(variants: Record<string, ImageVariant>): ImageVariant | undefined {
  return Object.values(variants).sort((a, b) => Math.abs(a.width - 640) - Math.abs(b.width - 640))[0];
}

const STATUS = {
  visible: { colour: "green", label: "Visible" },
  hidden_pending_review: { colour: "gold", label: "Held for review" },
  removed: { colour: "red", label: "Removed" },
  deleted: { colour: "default", label: "Deleted by its author" },
} as Record<string, { colour: string; label: string }>;

export function Content() {
  const { type = "", id = "" } = useParams();
  const { query, result } = useOne<ContentDetail>({ resource: "content", id: `${type}/${id}`, queryOptions: { retry: false } });
  const act = useAction();

  if (query.isLoading) return <Loading />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} title="Couldn't load this" />;
  if (!result) return <EmptyState title="Nothing here" />;

  const { content, reports } = result;
  const base = `/content/${type}/${id}`;
  const refresh = ["content", "queue"];
  const pending = reports.filter((report) => report.status === "pending").length;
  const status = STATUS[content.status] ?? { colour: "default", label: words(content.status) };
  const gone = content.status === "removed" || content.status === "deleted";
  const send = (path: string, values: Record<string, unknown>, done: string) =>
    act(`${base}/${path}`, values, { done, refresh }) as Promise<ActionOut>;

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <Card
        title={
          <Space>
            {TARGET_LABELS[content.target_type] ?? content.target_type}
            <Tag color={status.colour}>{status.label}</Tag>
          </Space>
        }
        extra={<Link to="/queue">Back to the queue</Link>}
      >
        <Descriptions size="small" column={{ xs: 1, md: 2 }} style={{ marginBottom: 16 }}>
          <Descriptions.Item label="By">
            {content.author ? (
              <Space>
                <Link to={`/people/${content.author.id}`}>{content.author.display_name}</Link>
                <AccountTags account={content.author} />
              </Space>
            ) : (
              "—"
            )}
          </Descriptions.Item>
          <Descriptions.Item label="Made">{when(content.created_at)}</Descriptions.Item>
          {Object.entries(content.details)
            .filter(([, value]) => value !== null && value !== "" && !(Array.isArray(value) && value.length === 0))
            .map(([key, value]) => (
              <Descriptions.Item key={key} label={words(key)}>
                {Array.isArray(value)
                  ? `${value.length}: ${JSON.stringify(value)}`
                  : typeof value === "object"
                    ? JSON.stringify(value)
                    : String(value)}
              </Descriptions.Item>
            ))}
        </Descriptions>
        <Typography.Paragraph style={{ whiteSpace: "pre-wrap", fontSize: 15 }}>
          {content.text || <Typography.Text type="secondary">No text.</Typography.Text>}
        </Typography.Paragraph>
        {content.images.length ? (
          <Image.PreviewGroup>
            <Space wrap>
              {content.images.map((image) => {
                const variant = medium(image.variants);
                return variant ? (
                  <Image key={image.media_id} src={variant.url} width={200} alt="A photo in the reported content" />
                ) : null;
              })}
            </Space>
          </Image.PreviewGroup>
        ) : null}

        <Space wrap style={{ marginTop: 16 }}>
          {!gone ? (
            <ActionButton
              danger
              label="Remove"
              title="Remove this?"
              consequence="It disappears for everyone, its pending reports are upheld, and its author is told why."
              confirmLabel="Remove it"
              fields={[{ name: "reason", label: "Reason, shown to the author", kind: "textarea", required: true, min: 3, max: 1000 }]}
              onConfirm={(values) => send("remove", values, "Removed.")}
            />
          ) : null}
          {content.status !== "visible" && content.status !== "deleted" ? (
            <ActionButton
              label="Restore"
              title="Put this back?"
              consequence="It becomes visible again and its pending reports are dismissed."
              confirmLabel="Restore it"
              fields={[{ name: "note", label: "Note for the record (optional)", kind: "textarea", max: 1000 }]}
              onConfirm={(values) => send("restore", values, "Restored.")}
            />
          ) : null}
          {pending ? (
            <>
              <ActionButton
                label="Dismiss reports"
                title="Dismiss the reports?"
                consequence={`Nothing was wrong: the ${pending} pending ${pending === 1 ? "report closes" : "reports close"} and it stays as it is.`}
                confirmLabel="Dismiss"
                fields={[{ name: "note", label: "Note for the record (optional)", kind: "textarea", max: 1000 }]}
                onConfirm={(values) => send("resolve", { ...values, outcome: "dismissed" }, "Reports dismissed.")}
              />
              <ActionButton
                danger
                label="Uphold reports"
                title="Uphold the reports?"
                consequence="The reports were right and it was dealt with on the person (a warning, a restriction). The content stays as it is; the reports count against its author."
                confirmLabel="Uphold"
                fields={[{ name: "note", label: "What was done (optional)", kind: "textarea", max: 1000 }]}
                onConfirm={(values) => send("resolve", { ...values, outcome: "upheld" }, "Reports upheld.")}
              />
            </>
          ) : null}
        </Space>
      </Card>

      <Card title={`Reports (${reports.length})`}>
        {reports.length === 0 ? (
          <EmptyState title="No reports">It is here because it was held for review.</EmptyState>
        ) : (
          <Table<Report>
            rowKey="id"
            size="small"
            pagination={false}
            dataSource={reports}
            columns={[
              { title: "Reason", dataIndex: "reason", render: (reason: string) => <Tag color="volcano">{words(reason)}</Tag> },
              { title: "Details", dataIndex: "details", render: (text: string | null) => text ?? "—" },
              { title: "Trusted", dataIndex: "trusted", render: (trusted: boolean) => (trusted ? "Yes" : "No") },
              { title: "Status", dataIndex: "status", render: (value: string) => words(value) },
              { title: "Reported", dataIndex: "created_at", render: (value: string) => when(value) },
              {
                title: "By",
                dataIndex: "reporter_id",
                render: (value: string) => <Link to={`/people/${value}`}>{shortId(value)}</Link>,
              },
            ]}
          />
        )}
      </Card>
    </div>
  );
}

