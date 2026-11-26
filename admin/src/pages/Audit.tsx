import { useList, type CrudFilters } from "@refinedev/core";
import { Card, DatePicker, Select, Space, Table, Typography } from "antd";
import type { Dayjs } from "dayjs";
import { useState } from "react";
import { Link } from "react-router";

import { EmptyState, ErrorState, Loading } from "../components";
import { shortId, when, words } from "../format";
import { LoadMore, useCursorList } from "../lists";
import { AUDIT_ACTIONS, type AuditEvent, type Staff } from "../types";

/** A picked calendar day, as the start of that day in Nairobi. */
export function nairobiStart(day: Dayjs, plusDays = 0): string {
  return `${day.add(plusDays, "day").format("YYYY-MM-DD")}T00:00:00+03:00`;
}

export function Audit() {
  const [actor, setActor] = useState<string | undefined>();
  const [action, setAction] = useState<string | undefined>();
  const [range, setRange] = useState<[Dayjs | null, Dayjs | null] | null>(null);
  const { result: staffList } = useList<Staff>({ resource: "staff", pagination: { mode: "off" } });
  const staffById = new Map((staffList?.data ?? []).map((staff) => [staff.id, staff]));

  const filters: CrudFilters = [
    { field: "actor_id", operator: "eq", value: actor },
    { field: "action", operator: "eq", value: action },
    { field: "since", operator: "eq", value: range?.[0] ? nairobiStart(range[0]) : undefined },
    { field: "until", operator: "eq", value: range?.[1] ? nairobiStart(range[1], 1) : undefined },
  ];
  const list = useCursorList<AuditEvent>("audit", filters);

  const who = (event: AuditEvent) => {
    if (event.actor_type === "system") return "The system";
    if (event.actor_type === "moderator") {
      const staff = event.actor_id ? staffById.get(event.actor_id) : undefined;
      return staff ? staff.display_name : `Staff ${shortId(event.actor_id)}`;
    }
    return event.actor_id ? <Link to={`/people/${event.actor_id}`}>Person {shortId(event.actor_id)}</Link> : "A person";
  };

  return (
    <Card title="Audit log">
      <Space wrap style={{ marginBottom: 16 }}>
        <Select
          allowClear
          placeholder="Any staff member"
          style={{ width: 200 }}
          value={actor}
          onChange={setActor}
          aria-label="Staff member"
          options={(staffList?.data ?? []).map((staff) => ({ value: staff.id, label: staff.display_name }))}
        />
        <Select
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder="Any action"
          style={{ width: 240 }}
          value={action}
          onChange={setAction}
          aria-label="Action"
          options={AUDIT_ACTIONS.map((value) => ({ value, label: words(value) }))}
        />
        <DatePicker.RangePicker value={range} onChange={(value) => setRange(value)} aria-label="Dates" />
      </Space>
      <Typography.Paragraph type="secondary">Newest first. Days are Nairobi days. Read only.</Typography.Paragraph>
      {list.isLoading ? (
        <Loading />
      ) : list.isError ? (
        <ErrorState error={list.error} onRetry={list.refetch} title="Couldn't load the audit log" />
      ) : list.rows.length === 0 ? (
        <EmptyState title="Nothing matches">Try fewer filters or a wider range of dates.</EmptyState>
      ) : (
        <>
          <Table<AuditEvent>
            rowKey="id"
            size="small"
            pagination={false}
            dataSource={list.rows}
            columns={[
              { title: "When", dataIndex: "created_at", render: (value: string) => when(value) },
              { title: "Who", key: "who", render: (_, event) => who(event) },
              { title: "What", dataIndex: "action", render: (value: string) => words(value) },
              {
                title: "On",
                key: "target",
                render: (_, event) =>
                  event.target_type === "user" && event.target_id ? (
                    <Link to={`/people/${event.target_id}`}>Person {shortId(event.target_id)}</Link>
                  ) : event.target_type ? (
                    `${words(event.target_type)} ${shortId(event.target_id)}`
                  ) : (
                    "—"
                  ),
              },
              {
                title: "Details",
                dataIndex: "context",
                render: (context: Record<string, unknown>) =>
                  Object.keys(context).length ? <code style={{ fontSize: 12 }}>{JSON.stringify(context)}</code> : "—",
              },
            ]}
          />
          <LoadMore more={list.more} loading={list.loadingMore} />
        </>
      )}
    </Card>
  );
}
