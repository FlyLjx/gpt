"use client";

import { useEffect, useMemo, useState } from "react";
import { Alert, Button, Card, Empty, Progress, Skeleton, Space, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  Activity,
  AlertCircle,
  CheckCircle2,
  Database,
  Gauge,
  KeyRound,
  LoaderCircle,
  RefreshCw,
  Server,
  ShieldAlert,
  TimerReset,
  UsersRound,
} from "lucide-react";
import { toast } from "sonner";

import { fetchDashboard, type DashboardSummary } from "@/lib/api";
import { useAuthGuard } from "@/lib/use-auth-guard";
import { cn } from "@/lib/utils";

function numberText(value: unknown) {
  const numeric = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numeric)) {
    return "0";
  }
  if (numeric >= 10000) {
    return `${(numeric / 10000).toFixed(1)}w`;
  }
  if (numeric >= 1000) {
    return `${(numeric / 1000).toFixed(1)}k`;
  }
  return String(numeric);
}

function percent(value: number, total: number) {
  if (total <= 0) {
    return 0;
  }
  return Math.round((value / total) * 100);
}

function statusTag(status?: string) {
  const value = String(status || "").trim();
  const color: Record<string, string> = {
    healthy: "green",
    success: "green",
    running: "processing",
    queued: "blue",
    error: "red",
    failed: "red",
    unhealthy: "red",
  };
  return <Tag color={color[value] || "default"}>{value || "-"}</Tag>;
}

function sortedEntries(source?: Record<string, number>, limit = 5) {
  return Object.entries(source || {})
    .filter(([, value]) => Number(value) > 0)
    .sort((left, right) => right[1] - left[1])
    .slice(0, limit);
}

function MetricCard({
  title,
  value,
  helper,
  icon: Icon,
  tone = "blue",
}: {
  title: string;
  value: string | number;
  helper: string;
  icon: typeof Activity;
  tone?: "blue" | "green" | "amber" | "rose" | "slate";
}) {
  const toneClass = {
    blue: "bg-blue-50 text-blue-600",
    green: "bg-emerald-50 text-emerald-600",
    amber: "bg-amber-50 text-amber-600",
    rose: "bg-rose-50 text-rose-600",
    slate: "bg-slate-100 text-slate-600",
  }[tone];

  return (
    <Card className="h-full">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="text-sm font-medium text-slate-500">{title}</div>
          <div className="mt-3 text-3xl font-semibold tracking-normal text-slate-950">{value}</div>
          <div className="mt-2 text-sm text-slate-400">{helper}</div>
        </div>
        <div className={cn("flex size-10 shrink-0 items-center justify-center rounded-lg", toneClass)}>
          <Icon className="size-5" />
        </div>
      </div>
    </Card>
  );
}

function EntryBars({ items, emptyText = "暂无数据" }: { items: Array<[string, number]>; emptyText?: string }) {
  const maxValue = Math.max(...items.map(([, value]) => value), 0);
  if (!items.length) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={emptyText} />;
  }
  return (
    <div className="space-y-3">
      {items.map(([label, value]) => (
        <div key={label} className="space-y-1.5">
          <div className="flex items-center justify-between gap-3 text-sm">
            <span className="min-w-0 truncate text-slate-600">{label}</span>
            <span className="font-mono text-xs font-semibold text-slate-500">{numberText(value)}</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-slate-100">
            <div className="h-full rounded-full bg-blue-500" style={{ width: `${maxValue > 0 ? Math.max(6, Math.round((value / maxValue) * 100)) : 0}%` }} />
          </div>
        </div>
      ))}
    </div>
  );
}

function DashboardContent() {
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const loadDashboard = async (silent = false) => {
    if (silent) {
      setIsRefreshing(true);
    } else {
      setIsLoading(true);
    }
    try {
      setData(await fetchDashboard());
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "加载总览失败");
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    void loadDashboard();
  }, []);

  const taskColumns = useMemo<ColumnsType<DashboardSummary["tasks"]["recent"][number]>>(
    () => [
      { title: "任务", dataIndex: "id", ellipsis: true },
      { title: "模式", dataIndex: "mode", width: 96, render: (value) => <Tag>{value === "edit" ? "图生图" : "文生图"}</Tag> },
      { title: "状态", dataIndex: "status", width: 96, render: statusTag },
      { title: "更新时间", dataIndex: "updated_at", width: 180 },
    ],
    [],
  );

  const failedColumns = useMemo<ColumnsType<DashboardSummary["calls"]["recent_failed"][number]>>(
    () => [
      { title: "时间", dataIndex: "time", width: 170 },
      { title: "摘要", dataIndex: "summary", width: 130, ellipsis: true },
      { title: "模型", dataIndex: "model", width: 130, ellipsis: true },
      { title: "错误", dataIndex: "error", ellipsis: true },
    ],
    [],
  );

  if (isLoading && !data) {
    return (
      <div className="dashboard-console">
        <Skeleton active paragraph={{ rows: 8 }} />
      </div>
    );
  }

  if (!data) {
    return (
      <Card>
        <Empty description="暂时无法加载系统总览" />
      </Card>
    );
  }

  const totalAccounts = data.accounts.total;
  const totalCalls = data.calls.total;
  const failedCalls = data.calls.by_status.failed || 0;
  const runningTasks = (data.tasks.by_status.running || 0) + (data.tasks.by_status.queued || 0);
  const storageHealthy = data.storage.health.status === "healthy";
  const callSuccessPercent = percent(totalCalls - failedCalls, totalCalls);

  return (
    <div className="dashboard-console">
      <section className="flex flex-col gap-4 rounded-lg border border-slate-200 bg-white px-5 py-5 shadow-sm lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Tag color={storageHealthy ? "green" : "red"} className="m-0">{storageHealthy ? "运行正常" : "需要检查"}</Tag>
            <span className="text-sm text-slate-400">v{data.version}</span>
          </div>
          <Typography.Title level={2} className="!mt-3 !mb-1 !text-2xl">
            系统总览
          </Typography.Title>
          <Typography.Text type="secondary">最后更新：{data.generated_at}</Typography.Text>
        </div>
        <Button
          type="primary"
          icon={isRefreshing ? <LoaderCircle className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
          onClick={() => void loadDashboard(true)}
          disabled={isRefreshing}
        >
          刷新
        </Button>
      </section>

      {!storageHealthy ? (
        <Alert
          type="error"
          showIcon
          message="存储后端异常"
          description={String(data.storage.health.error || "请检查数据库连接和容器状态。")}
        />
      ) : null}

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard title="可用账号" value={`${numberText(data.accounts.active)}/${numberText(totalAccounts)}`} helper={`限流 ${data.accounts.limited}，异常 ${data.accounts.abnormal}`} icon={UsersRound} tone="green" />
        <MetricCard title="剩余额度" value={data.accounts.unlimited_quota_count > 0 ? "不限" : numberText(data.accounts.total_quota)} helper={`调度冷却 ${data.accounts.cooling} 个账号`} icon={Gauge} tone="blue" />
        <MetricCard title="今日调用" value={numberText(totalCalls)} helper={`失败 ${failedCalls}，成功率 ${callSuccessPercent}%`} icon={Activity} tone={failedCalls ? "amber" : "green"} />
        <MetricCard title="队列任务" value={numberText(runningTasks)} helper={`历史任务 ${data.tasks.total} 条`} icon={TimerReset} tone={runningTasks ? "amber" : "slate"} />
      </section>

      <section className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <Card title="账号池状态">
          <div className="grid gap-6 lg:grid-cols-[220px_1fr]">
            <div className="flex flex-col items-center justify-center">
              <Progress
                type="circle"
                percent={percent(data.accounts.active, Math.max(1, totalAccounts))}
                size={150}
                strokeColor="#10b981"
                format={() => `${data.accounts.active}`}
              />
              <div className="mt-3 text-sm text-slate-500">正常账号占比</div>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-lg bg-slate-50 p-4">
                <div className="flex items-center gap-2 text-sm text-slate-500"><CheckCircle2 className="size-4 text-emerald-500" /> 正常</div>
                <div className="mt-2 text-2xl font-semibold">{data.accounts.active}</div>
              </div>
              <div className="rounded-lg bg-slate-50 p-4">
                <div className="flex items-center gap-2 text-sm text-slate-500"><AlertCircle className="size-4 text-amber-500" /> 限流</div>
                <div className="mt-2 text-2xl font-semibold">{data.accounts.limited}</div>
              </div>
              <div className="rounded-lg bg-slate-50 p-4">
                <div className="flex items-center gap-2 text-sm text-slate-500"><ShieldAlert className="size-4 text-rose-500" /> 异常</div>
                <div className="mt-2 text-2xl font-semibold">{data.accounts.abnormal}</div>
              </div>
              <div className="rounded-lg bg-slate-50 p-4">
                <div className="flex items-center gap-2 text-sm text-slate-500"><KeyRound className="size-4 text-blue-500" /> 用户密钥</div>
                <div className="mt-2 text-2xl font-semibold">{data.auth_keys.enabled_users}/{data.auth_keys.users}</div>
              </div>
            </div>
          </div>
        </Card>

        <Card title="存储与代理">
          <div className="space-y-4">
            <div className="flex items-start gap-3 rounded-lg bg-slate-50 p-4">
              <Database className="mt-0.5 size-5 text-blue-500" />
              <div className="min-w-0">
                <div className="font-medium text-slate-800">{data.storage.backend.description || data.storage.backend.type || "存储后端"}</div>
                <div className="mt-1 break-all text-xs text-slate-500">{data.storage.backend.database_url || data.storage.health.backend || "-"}</div>
                <div className="mt-2">{statusTag(data.storage.health.status)}</div>
              </div>
            </div>
            <div className="flex items-start gap-3 rounded-lg bg-slate-50 p-4">
              <Server className="mt-0.5 size-5 text-emerald-500" />
              <div>
                <div className="font-medium text-slate-800">代理账号</div>
                <div className="mt-1 text-sm text-slate-500">
                  已配置 {data.accounts.proxy_stats.accounts} 个，冷却 {data.accounts.proxy_stats.cooling} 个
                </div>
              </div>
            </div>
          </div>
        </Card>
      </section>

      <section className="grid gap-4 xl:grid-cols-3">
        <Card title="今日接口分布">
          <EntryBars items={sortedEntries(data.calls.by_endpoint)} />
        </Card>
        <Card title="模型使用">
          <EntryBars items={sortedEntries(data.calls.by_model)} />
        </Card>
        <Card title="账号类型">
          <EntryBars items={sortedEntries(data.accounts.by_type)} />
        </Card>
      </section>

      <section className="grid gap-4 xl:grid-cols-2">
        <Card title="最近任务" styles={{ body: { padding: 0 } }}>
          <Table
            rowKey="id"
            columns={taskColumns}
            dataSource={data.tasks.recent}
            pagination={false}
            size="small"
            locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无图片任务" /> }}
          />
        </Card>
        <Card title="最近失败" styles={{ body: { padding: 0 } }}>
          <Table
            rowKey={(record) => String(record.id || `${record.time}-${record.error}`)}
            columns={failedColumns}
            dataSource={data.calls.recent_failed}
            pagination={false}
            size="small"
            locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="今日暂无失败调用" /> }}
          />
        </Card>
      </section>
    </div>
  );
}

export default function DashboardPage() {
  const { isCheckingAuth, session } = useAuthGuard(["admin"]);

  if (isCheckingAuth || !session || session.role !== "admin") {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-stone-400" />
      </div>
    );
  }

  return <DashboardContent />;
}
