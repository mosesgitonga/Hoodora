import { CanAccess, useOne } from "@refinedev/core";
import { Card, Descriptions, Space, Table, Tabs, Tag } from "antd";
import type { Dayjs } from "dayjs";
import { Link, useParams } from "react-router";

import { useAction } from "../actions";
import { AccountTags, ActionButton, EmptyState, ErrorState, Loading } from "../components";
import { shortId, when, words } from "../format";
import type { AuditEvent, Report, UserHistory, Warning } from "../types";

/** The API takes a number of days; the screen offers an end date (decision D.2). */
export function daysUntil(end: Dayjs | Date, now: Date = new Date()): number {
  const target = end instanceof Date ? end : end.toDate();
  const ms = target.getTime() - now.getTime();
  return Math.min(365, Math.max(1, Math.ceil(ms / 86_400_000)));
}

function ReportsTable({ reports, side }: { reports: Report[]; side: "against" | "by" }) {
  if (reports.length === 0) {
    return <EmptyState title={side === "against" ? "Nobody has reported them" : "They haven't reported anything"} />;
  }
  return (
    <Table<Report>
      rowKey="id"
      size="small"
      pagination={{ pageSize: 10, hideOnSinglePage: true }}
      dataSource={reports}
      columns={[
        { title: "Reason", dataIndex: "reason", render: (reason: string) => <Tag color="volcano">{words(reason)}</Tag> },
        { title: "Details", dataIndex: "details", render: (text: string | null) => text ?? "—" },
        { title: "Status", dataIndex: "status", render: (status: string) => words(status) },
        { title: "When", dataIndex: "created_at", render: (value: string) => when(value) },
        ...(side === "against"
          ? [{ title: "By", dataIndex: "reporter_id", render: (id: string) => <Link to={`/people/${id}`}>{shortId(id)}</Link> }]
          : []),
      ]}
    />
  );
}

export function Person() {
  const { id = "" } = useParams();
  const { query, result } = useOne<UserHistory>({ resource: "people", id, queryOptions: { retry: false } });
  const act = useAction();

  if (query.isLoading) return <Loading />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} title="Couldn't load this person" />;
  if (!result) return <EmptyState title="Nobody here" />;

  const { account } = result;
  const base = `/users/${account.id}`;
  const refresh = ["people", "queue"];
  const send = (path: string, values: Record<string, unknown>, done: string) => act(`${base}/${path}`, values, { done, refresh });
  const suspended = account.status === "suspended";
  const banned = account.status === "banned";

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <Card title={<Space>{account.display_name}<AccountTags account={account} /></Space>} extra={<Link to="/people">Find someone else</Link>}>
        <Descriptions size="small" column={{ xs: 1, md: 2 }}>
          <Descriptions.Item label="Joined">{when(account.created_at)}</Descriptions.Item>
          <Descriptions.Item label="Content removed">{result.content_removed_count}</Descriptions.Item>
          {account.suspended_until ? <Descriptions.Item label="Suspended until">{when(account.suspended_until)}</Descriptions.Item> : null}
          {suspended && !account.suspended_until ? <Descriptions.Item label="Suspended">Until lifted by hand</Descriptions.Item> : null}
          {account.restricted ? (
            <Descriptions.Item label="Restricted until">
              {when(account.restricted_until)}
              {account.restriction_reason ? ` — ${account.restriction_reason}` : ""}
            </Descriptions.Item>
          ) : null}
          <Descriptions.Item label="Account ID">{account.id}</Descriptions.Item>
        </Descriptions>

        {account.deleted ? null : (
          <Space wrap style={{ marginTop: 16 }}>
            <ActionButton
              label="Warn"
              title={`Warn ${account.display_name}?`}
              consequence="They see the reason in their standing and as a notification."
              confirmLabel="Send warning"
              fields={[{ name: "reason", label: "Reason, shown to them", kind: "textarea", required: true, min: 3, max: 1000 }]}
              onConfirm={(values) => send("warn", values, "Warning sent.")}
            />
            {!suspended && !banned ? (
              <ActionButton
                danger
                label="Suspend"
                title={`Suspend ${account.display_name}?`}
                consequence="They keep read access, can see why, and can export their data, but can't post or message."
                confirmLabel="Suspend"
                fields={[
                  { name: "reason", label: "Reason, shown to them", kind: "textarea", required: true, min: 3, max: 1000 },
                  { name: "until", label: "Until", kind: "date", help: "Leave empty to suspend until it is lifted by hand." },
                ]}
                onConfirm={({ reason, until }) =>
                  send("suspend", { reason, days: until ? daysUntil(until as Dayjs) : undefined }, "Suspended.")
                }
              />
            ) : null}
            {suspended ? (
              <ActionButton
                label="Lift suspension"
                title="Lift the suspension?"
                consequence="They can post and message again straight away."
                confirmLabel="Lift it"
                onConfirm={() => send("unsuspend", {}, "Suspension lifted.")}
              />
            ) : null}
            {!account.restricted ? (
              <ActionButton
                danger
                label="Restrict"
                title={`Restrict ${account.display_name}?`}
                consequence="New-account limits whatever their age, no new conversations or job posts, and new posts held for review. It lapses on its own."
                confirmLabel="Restrict"
                fields={[
                  { name: "reason", label: "Reason", kind: "textarea", required: true, min: 3, max: 500 },
                  { name: "days", label: "Days", kind: "number", min: 1, max: 90, initial: 7 },
                ]}
                onConfirm={(values) => send("restrict", values, "Restricted.")}
              />
            ) : (
              <ActionButton
                label="Lift restriction"
                title="Lift the restriction?"
                consequence="Their pending reports are dismissed and the limits end now."
                confirmLabel="Lift it"
                fields={[{ name: "note", label: "Note for the record (optional)", kind: "textarea", max: 1000 }]}
                onConfirm={(values) => send("unrestrict", values, "Restriction lifted.")}
              />
            )}
            {account.is_verified_neighbour ? (
              <ActionButton
                danger
                label="Revoke badge"
                title="Take the verified-neighbour badge away?"
                consequence="The badge goes at once."
                confirmLabel="Revoke"
                fields={[{ name: "lock", label: "Lock it, so the nightly check doesn't award it back", kind: "checkbox", initial: true }]}
                onConfirm={(values) => send("badge/revoke", values, "Badge revoked.")}
              />
            ) : null}
            {account.badge_locked ? (
              <ActionButton
                label="Unlock badge"
                title="Let the badge be earned again?"
                consequence="It returns on the next nightly check if they still qualify."
                confirmLabel="Unlock"
                onConfirm={() => send("badge/unlock", {}, "Badge unlocked.")}
              />
            ) : null}
            <CanAccess resource="people" action="ban" fallback={null}>
              {!banned ? (
                <ActionButton
                  danger
                  label="Ban"
                  title={`Ban ${account.display_name}?`}
                  consequence="They are signed out everywhere at once and can't sign back in."
                  confirmLabel="Ban"
                  fields={[
                    { name: "reason", label: "Reason", kind: "textarea", required: true, min: 3, max: 1000 },
                    { name: "ban_phone", label: "Also ban their phone number", kind: "checkbox", initial: true },
                    { name: "ban_devices", label: "Also ban every device they signed in from", kind: "checkbox", initial: true },
                    { name: "ban_google_account", label: "Also ban their Google account", kind: "checkbox", initial: true },
                    { name: "remove_content", label: "Also take down everything they have posted", kind: "checkbox", initial: false },
                  ]}
                  onConfirm={(values) => send("ban", values, "Banned.")}
                />
              ) : (
                <ActionButton
                  label="Lift ban"
                  title="Lift the ban?"
                  consequence="The phone and device bans it added are lifted too."
                  confirmLabel="Lift it"
                  onConfirm={() => send("unban", {}, "Ban lifted.")}
                />
              )}
            </CanAccess>
          </Space>
        )}
      </Card>

      <Card>
        <Tabs
          items={[
            { key: "against", label: `Reports against (${result.reports_against.length})`, children: <ReportsTable reports={result.reports_against} side="against" /> },
            { key: "by", label: `Reports by them (${result.reports_by.length})`, children: <ReportsTable reports={result.reports_by} side="by" /> },
            {
              key: "warnings",
              label: `Warnings (${result.warnings.length})`,
              children: result.warnings.length ? (
                <Table<Warning>
                  rowKey="id"
                  size="small"
                  pagination={false}
                  dataSource={result.warnings}
                  columns={[
                    { title: "Reason", dataIndex: "reason" },
                    { title: "When", dataIndex: "created_at", render: (value: string) => when(value) },
                  ]}
                />
              ) : (
                <EmptyState title="No warnings" />
              ),
            },
            {
              key: "actions",
              label: `Actions (${result.actions.length})`,
              children: result.actions.length ? (
                <Table<AuditEvent>
                  rowKey="id"
                  size="small"
                  pagination={{ pageSize: 10, hideOnSinglePage: true }}
                  dataSource={result.actions}
                  columns={[
                    { title: "What", dataIndex: "action", render: (action: string) => words(action) },
                    { title: "When", dataIndex: "created_at", render: (value: string) => when(value) },
                    { title: "By", key: "by", render: (_, event) => `${words(event.actor_type)} ${shortId(event.actor_id)}` },
                  ]}
                />
              ) : (
                <EmptyState title="No actions taken" />
              ),
            },
          ]}
        />
      </Card>
    </div>
  );
}
