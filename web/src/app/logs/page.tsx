"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Button,
  Card,
  Checkbox,
  Empty,
  Modal,
  Pagination,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { LoaderCircle, RefreshCw, Search, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { DateRangeFilter } from "@/components/date-range-filter";
import { deleteSystemLogs, fetchSystemLogs, type SystemLog } from "@/lib/api";
import { useAuthGuard } from "@/lib/use-auth-guard";

const LogType = {
  Call: "call",
  Account: "account",
} as const;

const typeLabels: Record<string, string> = {
  [LogType.Call]: "调用日志",
  [LogType.Account]: "账号管理日志",
};

function getDetailText(item: SystemLog, key: string) {
  const value = item.detail?.[key];
  return typeof value === "string" || typeof value === "number" ? String(value) : "-";
}

function formatDuration(item: SystemLog) {
  if (item.detail?.status === "running") {
    return "进行中";
  }
  const value = item.detail?.duration_ms;
  return typeof value === "number" ? `${(value / 1000).toFixed(2)} s` : "-";
}

function getStatus(item: SystemLog) {
  const status = item.detail?.status;
  if (status === "success") return "成功";
  if (status === "failed") return "失败";
  if (status === "running") return "处理中";
  return "-";
}

function getStatusColor(item: SystemLog) {
  const status = item.detail?.status;
  if (status === "failed") return "red";
  if (status === "running") return "processing";
  return "green";
}

function LogsContent() {
  const [items, setItems] = useState<SystemLog[]>([]);
  const [type, setType] = useState<string>(LogType.Call);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [detailLog, setDetailLog] = useState<SystemLog | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [page, setPage] = useState(1);
  const [isLoading, setIsLoading] = useState(true);
  const [isDeleting, setIsDeleting] = useState(false);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [deletingItems, setDeletingItems] = useState<SystemLog[]>([]);
  const isCallLog = type === LogType.Call;
  const pageSize = 10;
  const pageCount = Math.max(1, Math.ceil(items.length / pageSize));
  const safePage = Math.min(page, pageCount);
  const currentRows = items.slice((safePage - 1) * pageSize, safePage * pageSize);
  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);
  const currentPageSelected = currentRows.length > 0 && currentRows.every((item) => selectedSet.has(item.id));
  const allSelected = items.length > 0 && items.every((item) => selectedSet.has(item.id));

  const loadLogs = async () => {
    setIsLoading(true);
    try {
      const data = await fetchSystemLogs({ type, start_date: startDate, end_date: endDate });
      setItems(data.items);
      setSelectedIds((current) => current.filter((id) => data.items.some((item) => item.id === id)));
      setPage(1);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "加载日志失败");
    } finally {
      setIsLoading(false);
    }
  };

  const clearFilters = () => {
    setStartDate("");
    setEndDate("");
  };

  const openDetail = (item: SystemLog) => {
    setDetailLog(item);
    setDetailOpen(true);
  };

  const toggleIds = (ids: string[], checked: boolean) => {
    setSelectedIds((current) => checked ? Array.from(new Set([...current, ...ids])) : current.filter((id) => !ids.includes(id)));
  };

  const confirmDelete = async () => {
    const ids = deletingItems.map((item) => item.id);
    if (ids.length === 0) return;
    setIsDeleting(true);
    try {
      const data = await deleteSystemLogs(ids);
      toast.success(`已删除 ${data.removed} 条日志`);
      setDeletingItems([]);
      setSelectedIds((current) => current.filter((id) => !ids.includes(id)));
      if (detailLog && ids.includes(detailLog.id)) {
        setDetailOpen(false);
        setDetailLog(null);
      }
      await loadLogs();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "删除日志失败");
    } finally {
      setIsDeleting(false);
    }
  };

  useEffect(() => {
    void loadLogs();
  }, [type, startDate, endDate]);

  const columns: ColumnsType<SystemLog> = [
    {
      title: "",
      width: 48,
      render: (_, item) => (
        <Checkbox checked={selectedSet.has(item.id)} onChange={(event) => toggleIds([item.id], event.target.checked)} />
      ),
    },
    { title: "时间", dataIndex: "time", width: 180, render: (value: string) => <span className="whitespace-nowrap">{value}</span> },
    {
      title: "类型",
      dataIndex: "type",
      width: 130,
      render: (value: string) => <Tag color="blue">{typeLabels[value] || value}</Tag>,
    },
    ...(isCallLog
      ? [
          { title: "令牌名称", width: 160, render: (_: unknown, item: SystemLog) => getDetailText(item, "key_name") },
          { title: "调用耗时", width: 120, render: (_: unknown, item: SystemLog) => formatDuration(item) },
          {
            title: "状态",
            width: 90,
            render: (_: unknown, item: SystemLog) => (
              <Tag color={getStatusColor(item)}>{getStatus(item)}</Tag>
            ),
          },
        ] satisfies ColumnsType<SystemLog>
      : []),
    {
      title: "简述",
      dataIndex: "summary",
      ellipsis: true,
      render: (value?: string) => <span className="text-slate-500">{value || "-"}</span>,
    },
    {
      title: "操作",
      width: 150,
      fixed: "right",
      render: (_, item) => (
        <Space size={4}>
          <Button type="link" size="small" onClick={() => openDetail(item)}>查看详情</Button>
          <Button type="link" danger size="small" onClick={() => setDeletingItems([item])}>删除</Button>
        </Space>
      ),
    },
  ];

  return (
    <section className="space-y-4">
      <Card>
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <Typography.Text type="secondary" className="text-xs font-semibold uppercase tracking-[0.18em]">Logs</Typography.Text>
            <Typography.Title level={3} className="!mb-0 !mt-1">日志管理</Typography.Title>
            <Typography.Text type="secondary">查看调用和账号管理事件，支持日期筛选和批量删除。</Typography.Text>
          </div>
          <Space wrap>
            <Select
              value={type}
              onChange={setType}
              style={{ width: 150 }}
              options={[
                { value: LogType.Call, label: "调用日志" },
                { value: LogType.Account, label: "账号管理日志" },
              ]}
            />
            <DateRangeFilter startDate={startDate} endDate={endDate} onChange={(start, end) => { setStartDate(start); setEndDate(end); }} />
            <Button onClick={clearFilters}>清除筛选条件</Button>
            <Button type="primary" icon={isLoading ? <LoaderCircle className="size-4 animate-spin" /> : <Search className="size-4" />} onClick={() => void loadLogs()} disabled={isLoading}>
              查询
            </Button>
          </Space>
        </div>
      </Card>

      <Card
        title={
          <Space wrap>
            <span>日志列表</span>
            <Tag color="default">共 {items.length} 条</Tag>
            {selectedIds.length > 0 ? <Tag color="blue">已选 {selectedIds.length} 条</Tag> : null}
          </Space>
        }
        extra={
          <Space wrap>
            <Checkbox checked={currentPageSelected} onChange={(event) => toggleIds(currentRows.map((item) => item.id), event.target.checked)}>本页全选</Checkbox>
            <Checkbox checked={allSelected} onChange={(event) => toggleIds(items.map((item) => item.id), event.target.checked)}>全选结果</Checkbox>
            <Button onClick={() => setSelectedIds([])} disabled={selectedIds.length === 0 || isDeleting}>取消选择</Button>
            <Button icon={<RefreshCw className={`size-4 ${isLoading ? "animate-spin" : ""}`} />} onClick={() => void loadLogs()} disabled={isLoading}>刷新</Button>
            <Button danger icon={<Trash2 className="size-4" />} onClick={() => setDeletingItems(items.filter((item) => selectedSet.has(item.id)))} disabled={selectedIds.length === 0 || isDeleting}>
              删除所选
            </Button>
          </Space>
        }
        styles={{ body: { padding: 0 } }}
      >
        <Table
          rowKey="id"
          columns={columns}
          dataSource={currentRows}
          loading={isLoading}
          pagination={false}
          scroll={{ x: 980 }}
          locale={{ emptyText: <Empty description="没有找到日志" /> }}
        />
        <div className="flex items-center justify-end border-t border-slate-100 px-4 py-3">
          <Pagination
            current={safePage}
            pageSize={pageSize}
            total={items.length}
            showSizeChanger={false}
            showTotal={(total) => `共 ${total} 条`}
            onChange={setPage}
          />
        </div>
      </Card>

      <Modal
        title="日志详情"
        open={detailOpen}
        onCancel={() => setDetailOpen(false)}
        footer={null}
        width={920}
        styles={{ body: { maxHeight: "72vh", overflow: "auto" } }}
      >
        <div className="space-y-4">
          <div className="grid gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600 md:grid-cols-2">
            {Object.entries(detailLog?.detail || {})
              .filter(([, value]) => typeof value !== "object")
              .map(([key, value]) => (
                <div key={key} className="flex items-start justify-between gap-4">
                  <span className="text-slate-400">{key}</span>
                  <span className="text-right font-medium break-all text-slate-700">{String(value)}</span>
                </div>
              ))}
          </div>
          <pre className="max-h-[72vh] overflow-auto rounded-xl border border-slate-200 bg-slate-950 p-4 text-xs leading-6 text-slate-100">
            {JSON.stringify(detailLog?.detail || {}, null, 2)}
          </pre>
        </div>
      </Modal>

      <Modal
        title={deletingItems.length === 1 ? "删除日志" : "删除所选日志"}
        open={deletingItems.length > 0}
        onCancel={() => setDeletingItems([])}
        onOk={() => void confirmDelete()}
        okText="确认删除"
        cancelText="取消"
        okButtonProps={{ danger: true, loading: isDeleting, disabled: deletingItems.length === 0 }}
        cancelButtonProps={{ disabled: isDeleting }}
      >
        <p>确认删除 {deletingItems.length} 条日志吗？删除后无法恢复。</p>
      </Modal>
    </section>
  );
}

export default function LogsPage() {
  const { isCheckingAuth, session } = useAuthGuard(["admin"]);
  if (isCheckingAuth || !session || session.role !== "admin") {
    return <div className="flex min-h-[40vh] items-center justify-center"><Spin /></div>;
  }
  return <LogsContent />;
}
