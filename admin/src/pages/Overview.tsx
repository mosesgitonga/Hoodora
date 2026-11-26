import { useCustom } from "@refinedev/core";
import { Card, Col, Progress, Row, Statistic, Table, Typography } from "antd";

import { THEME } from "../theme";
import { EmptyState, ErrorState, Loading } from "../components";
import { day, LIMIT_LABELS, waited, when } from "../format";
import type { DayCounts, Stats } from "../types";

const COLUMNS = [
  { key: "sign_ups", label: "Sign-ups" },
  { key: "posts", label: "Posts" },
  { key: "listings", label: "Listings" },
  { key: "reports_opened", label: "Reports opened" },
  { key: "reports_resolved", label: "Reports resolved" },
] as const;

function band(from: number, to: number): string {
  return from === to ? `${from} km` : `${from}–${to} km`;
}

export function Overview() {
  const { query, result } = useCustom<Stats>({ url: "/stats", method: "get" });
  if (query.isLoading) return <Loading what="Counting" />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} title="Couldn't load the overview" />;
  const stats = result?.data;
  if (!stats) return <EmptyState title="No numbers yet" />;

  const today = stats.days[stats.days.length - 1];
  const sums = Object.fromEntries(
    COLUMNS.map(({ key }) => [key, stats.days.reduce((total, d) => total + d[key], 0)]),
  ) as Record<(typeof COLUMNS)[number]["key"], number>;
  const peak = Math.max(1, ...stats.days.map((d) => d.posts));
  const { totals, radius } = stats;

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <Typography.Text type="secondary">
        Counted at {when(stats.generated_at)}, Nairobi time. Counts only: nobody is named here.
      </Typography.Text>

      <Row gutter={[16, 16]}>
        {COLUMNS.map(({ key, label }) => (
          <Col xs={12} md={8} lg={4} key={key}>
            <Card size="small">
              <Statistic title={`${label} today`} value={today?.[key] ?? 0} />
              <Typography.Text type="secondary">{sums[key]} in 30 days</Typography.Text>
            </Card>
          </Col>
        ))}
        <Col xs={12} md={8} lg={4}>
          <Card size="small">
            <Statistic title="Accounts" value={totals.users} />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          <Card title="Active people" size="small">
            <Row gutter={16}>
              <Col span={6}><Statistic title="Last day" value={totals.active.last_day} /></Col>
              <Col span={6}><Statistic title="7 days" value={totals.active.last_7_days} /></Col>
              <Col span={6}><Statistic title="14 days" value={totals.active.last_14_days} /></Col>
              <Col span={6}><Statistic title="30 days" value={totals.active.last_30_days} /></Col>
            </Row>
            <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
              Accounts in good standing that opened the app. 14 days is what the feed radius counts.
              Only each person's latest visit is kept, so there is no history per day.
            </Typography.Paragraph>
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="Waiting for a moderator" size="small">
            <Row gutter={16}>
              <Col span={8}><Statistic title="Open reports" value={totals.open_reports} /></Col>
              <Col span={8}><Statistic title="Held items" value={totals.held_items} /></Col>
              <Col span={8}><Statistic title="Longest wait" value={waited(totals.oldest_waiting_since)} /></Col>
            </Row>
            <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
              {totals.waiting === 0
                ? "The queue is empty."
                : `${totals.waiting === 1 ? "1 thing" : `${totals.waiting} things`} in the queue.` +
                  (totals.oldest_open_report_at ? ` The oldest open report is from ${when(totals.oldest_open_report_at)}.` : "")}
            </Typography.Paragraph>
          </Card>
        </Col>
      </Row>

      <Card title="Feed radius across the people using the app" size="small">
        {radius.people === 0 ? (
          <EmptyState title="No active people yet">Once people use the app, their radius shows here.</EmptyState>
        ) : (
          <Row gutter={[32, 16]}>
            <Col xs={24} lg={12}>
              <Typography.Text strong>By radius</Typography.Text>
              {radius.bands.map((b) => (
                <div key={`${b.from_km}-${b.to_km}`} style={{ display: "grid", gridTemplateColumns: "90px 1fr 70px", gap: 8, alignItems: "center" }}>
                  <span>{band(b.from_km, b.to_km)}</span>
                  <Progress percent={Math.round((100 * b.people) / radius.people)} showInfo={false} strokeColor={THEME.token.colorPrimary} />
                  <span style={{ textAlign: "right" }}>{b.people}</span>
                </div>
              ))}
            </Col>
            <Col xs={24} lg={12}>
              <Typography.Text strong>What set it</Typography.Text>
              {Object.entries(radius.by_condition).map(([limit, people]) => (
                <div key={limit} style={{ display: "grid", gridTemplateColumns: "1fr 70px", gap: 8 }}>
                  <span>{LIMIT_LABELS[limit] ?? limit}</span>
                  <span style={{ textAlign: "right" }}>{people}</span>
                </div>
              ))}
              <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
                The radius grows until it holds enough active people and enough recent posts.
              </Typography.Paragraph>
            </Col>
          </Row>
        )}
      </Card>

      <Card title="The last 30 days" size="small">
        <Table<DayCounts>
          size="small"
          rowKey="date"
          pagination={false}
          dataSource={[...stats.days].reverse()}
          columns={[
            { title: "Day", dataIndex: "date", render: (value: string) => day(value) },
            ...COLUMNS.map(({ key, label }) => ({ title: label, dataIndex: key })),
            {
              title: "",
              key: "bar",
              width: 160,
              render: (_: unknown, row: DayCounts) => (
                <Progress percent={Math.round((100 * row.posts) / peak)} showInfo={false} size="small" strokeColor={THEME.token.colorPrimary} aria-label={`${row.posts} posts`} />
              ),
            },
          ]}
        />
      </Card>
    </div>
  );
}
