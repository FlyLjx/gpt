"use client";

import { useEffect, useMemo, useState } from "react";
import { Button, Card, Empty, Modal, Space, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { Ban, LoaderCircle, RefreshCw, TimerReset } from "lucide-react";
import { toast } from "sonner";

import { cancelImageTask, fetchImageTasks, type ImageTask } from "@/lib/api";
import { useAuthGuard } from "@/lib/use-auth-guard";

function statusTag(status: ImageTask["status"]) {
  const color = {
    queued: "blue",
    running: "processing",
    success: "green",
    error: "red",
  }[status] || "default";
  const label = {
    queued: "排队",
    running: "运行中",
    success: "成功",
    error: "失败",
  }[status] || status;
  return <Tag color={color}>{label}</Tag>;
}

function modeTag(mode: ImageTask["mode"]) {
  return <Tag>{mode === "edit" ? "图生图" : "文生图"}</Tag>;
}

function TasksContent() {
  const [items, setItems] = useState<ImageTask[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [pendingId, setPendingId] = useState("");

  const load = async (silent = false) => {
    if (!silent) {
      setIsLoading(true);
    }
    try {
      const data = await fetchImageTasks([]);
      setItems(data.items);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "加载任务失败");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    const hasRunning = items.some((item) => item.status === "queued" || item.status === "running");
    if (!hasRunning) {
      return;
    }
    const timer = window.setInterval(() => {
      void load(true);
    }, 2500);
    return () => window.clearInterval(timer);
  }, [items]);

  const summary = useMemo(() => {
    return {
      total: items.length,
      running: items.filter((item) => item.status === "running").length,
      queued: items.filter((item) => item.status === "queued").length,
      error: items.filter((item) => item.status === "error").length,
    };
  }, [items]);

  const handleCancel = (item: ImageTask) => {
    Modal.confirm({
      title: "取消任务",
      content: `确认取消任务 ${item.id} 吗？已经发往上游的请求可能仍会消耗时间，但本地任务会停止更新。`,
      okText: "取消任务",
      cancelText: "返回",
      okButtonProps: { danger: true },
      onOk: async () => {
        setPendingId(item.id);
        try {
          await cancelImageTask(item.id);
          toast.success("任务已取消");
          await load(true);
        } catch (error) {
          toast.error(error instanceof Error ? error.message : "取消任务失败");
        } finally {
          setPendingId("");
        }
      },
    });
  };

  const columns = useMemo<ColumnsType<ImageTask>>(
    () => [
      { title: "任务 ID", dataIndex: "id", ellipsis: true },
      { title: "模式", dataIndex: "mode", width: 96, render: modeTag },
      { title: "状态", dataIndex: "status", width: 96, render: statusTag },
      { title: "模型", dataIndex: "model", width: 150, ellipsis: true },
      { title: "进度", dataIndex: "progress", width: 150, ellipsis: true, render: (value) => value || "-" },
      { title: "耗时", dataIndex: "duration_ms", width: 110, render: (value) => typeof value === "number" ? `${(value / 1000).toFixed(1)}s` : "-" },
      { title: "更新时间", dataIndex: "updated_at", width: 180 },
      {
        title: "操作",
        width: 120,
        render: (_, item) => {
          const cancellable = item.status === "queued" || item.status === "running";
          return (
            <Button
              size="small"
              danger
              icon={pendingId === item.id ? <LoaderCircle className="size-3.5 animate-spin" /> : <Ban className="size-3.5" />}
              disabled={!cancellable || Boolean(pendingId)}
              onClick={() => handleCancel(item)}
            >
              取消
            </Button>
          );
        },
      },
    ],
    [pendingId],
  );

  return (
    <div className="dashboard-console">
      <section className="flex flex-col gap-4 rounded-lg border border-slate-200 bg-white px-5 py-5 shadow-sm lg:flex-row lg:items-center lg:justify-between">
        <div>
          <Typography.Title level={2} className="!mb-1 !text-2xl">任务队列</Typography.Title>
          <Typography.Text type="secondary">统一查看图片任务状态，并取消排队或运行中的任务。</Typography.Text>
        </div>
        <Button icon={<RefreshCw className="size-4" />} onClick={() => void load(true)}>
          刷新
        </Button>
      </section>

      <section className="grid gap-4 md:grid-cols-4">
        <Card><Space><TimerReset className="size-5 text-blue-500" /><span>总任务</span><strong>{summary.total}</strong></Space></Card>
        <Card><Space><LoaderCircle className="size-5 text-blue-500" /><span>运行中</span><strong>{summary.running}</strong></Space></Card>
        <Card><Space><TimerReset className="size-5 text-amber-500" /><span>排队</span><strong>{summary.queued}</strong></Space></Card>
        <Card><Space><Ban className="size-5 text-rose-500" /><span>失败</span><strong>{summary.error}</strong></Space></Card>
      </section>

      <Card styles={{ body: { padding: 0 } }}>
        <Table
          rowKey="id"
          columns={columns}
          dataSource={items}
          loading={isLoading}
          size="small"
          pagination={{ pageSize: 20, showSizeChanger: true }}
          scroll={{ x: 980 }}
          locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无图片任务" /> }}
        />
      </Card>
    </div>
  );
}

export default function TasksPage() {
  const { isCheckingAuth, session } = useAuthGuard(["admin"]);

  if (isCheckingAuth || !session || session.role !== "admin") {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-stone-400" />
      </div>
    );
  }

  return <TasksContent />;
}
