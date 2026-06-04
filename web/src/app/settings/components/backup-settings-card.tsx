"use client";

import { useState } from "react";
import { Alert, Button, Card, Checkbox, Descriptions, Empty, Form, Input, Modal, Space, Spin, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { CloudUpload, Download, Eye, Play, RefreshCcw, Shield, Trash2 } from "lucide-react";
import { toast } from "sonner";

import webConfig from "@/constants/common-env";
import { fetchBackupDetail, getBackupDownloadUrl, type BackupDetail, type BackupInclude, type BackupItem } from "@/lib/api";
import { getStoredAuthKey } from "@/store/auth";
import { useSettingsStore } from "../store";

function formatDateTime(value?: string | null) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatBytes(value: number) {
  if (!Number.isFinite(value) || value <= 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB"];
  let size = value;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size >= 10 || index === 0 ? size.toFixed(0) : size.toFixed(1)} ${units[index]}`;
}

function getFilenameFromContentDisposition(value: string | null) {
  const header = String(value || "").trim();
  if (!header) {
    return "";
  }
  const utf8Match = header.match(/filename\*\s*=\s*UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1]);
    } catch {
      return utf8Match[1];
    }
  }
  const plainMatch = header.match(/filename\s*=\s*"?([^";]+)"?/i);
  return plainMatch?.[1] || "";
}

const includeLabels: Array<{ key: keyof BackupInclude; label: string }> = [
  { key: "config", label: "系统配置" },
  { key: "register", label: "注册配置" },
  { key: "cpa", label: "CPA 配置" },
  { key: "sub2api", label: "Sub2API 配置" },
  { key: "logs", label: "调度与调用日志" },
  { key: "image_tasks", label: "图片任务记录" },
  { key: "accounts_snapshot", label: "账号快照" },
  { key: "auth_keys_snapshot", label: "用户密钥快照" },
  { key: "images", label: "图片文件目录" },
];

export function BackupSettingsCard() {
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detail, setDetail] = useState<BackupDetail | null>(null);
  const config = useSettingsStore((state) => state.config);
  const backups = useSettingsStore((state) => state.backups);
  const backupState = useSettingsStore((state) => state.backupState);
  const isLoadingConfig = useSettingsStore((state) => state.isLoadingConfig);
  const isSavingConfig = useSettingsStore((state) => state.isSavingConfig);
  const isLoadingBackups = useSettingsStore((state) => state.isLoadingBackups);
  const isRunningBackup = useSettingsStore((state) => state.isRunningBackup);
  const deletingBackupKey = useSettingsStore((state) => state.deletingBackupKey);
  const isTestingBackup = useSettingsStore((state) => state.isTestingBackup);
  const saveConfig = useSettingsStore((state) => state.saveConfig);
  const loadBackups = useSettingsStore((state) => state.loadBackups);
  const runBackup = useSettingsStore((state) => state.runBackup);
  const removeBackup = useSettingsStore((state) => state.removeBackup);
  const testBackup = useSettingsStore((state) => state.testBackup);
  const setBackupField = useSettingsStore((state) => state.setBackupField);
  const setBackupInclude = useSettingsStore((state) => state.setBackupInclude);

  if (isLoadingConfig) {
    return (
      <Card>
        <div className="flex items-center justify-center py-12">
          <Spin />
        </div>
      </Card>
    );
  }

  const backup = config?.backup;
  if (!backup) {
    return null;
  }

  const statusColor = backupState?.running ? "processing" : backupState?.last_status === "success" ? "success" : backupState?.last_status === "error" ? "error" : "default";
  const statusText = backupState?.running ? "备份中" : backupState?.last_status === "success" ? "最近成功" : backupState?.last_status === "error" ? "最近失败" : "未执行";

  const handleOpenDetail = async (key: string) => {
    setDetailLoading(true);
    setDetailOpen(true);
    try {
      const data = await fetchBackupDetail(key);
      setDetail(data.item);
    } catch (error) {
      setDetail(null);
      toast.error(error instanceof Error ? error.message : "读取备份详情失败");
    } finally {
      setDetailLoading(false);
    }
  };

  const handleDownload = async (key: string, name: string) => {
    try {
      const authKey = await getStoredAuthKey();
      if (!authKey) {
        toast.error("当前登录态已失效，请重新登录后再下载");
        return;
      }
      const response = await fetch(`${webConfig.apiUrl.replace(/\/$/, "")}${getBackupDownloadUrl(key)}`, {
        headers: {
          Authorization: `Bearer ${authKey}`,
        },
      });
      if (!response.ok) {
        let message = "下载备份失败";
        try {
          const data = await response.json() as { detail?: { error?: string }; error?: string; message?: string };
          message = data.detail?.error || data.error || data.message || message;
        } catch {
          message = response.status === 401 ? "登录已失效，请重新登录后再试" : message;
        }
        throw new Error(message);
      }
      const downloadName = getFilenameFromContentDisposition(response.headers.get("Content-Disposition")) || name || "backup.bin";
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = downloadName;
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      window.URL.revokeObjectURL(url);
      toast.success("备份下载已开始");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "下载备份失败");
    }
  };

  const confirmRemove = (item: BackupItem) => {
    Modal.confirm({
      title: "删除远端备份",
      content: `确认删除「${item.name}」吗？`,
      okText: "删除",
      cancelText: "取消",
      okButtonProps: { danger: true },
      onOk: () => removeBackup(item.key),
    });
  };

  const columns: ColumnsType<BackupItem> = [
    {
      title: "备份对象",
      dataIndex: "name",
      render: (_, item) => (
        <Space direction="vertical" size={2}>
          <Space wrap>
            <Typography.Text strong className="break-all">{item.name}</Typography.Text>
            {item.encrypted ? <Tag>已加密</Tag> : null}
          </Space>
          <Typography.Text type="secondary" className="break-all">key {item.key}</Typography.Text>
        </Space>
      ),
    },
    {
      title: "大小",
      dataIndex: "size",
      width: 110,
      render: (value: number) => formatBytes(value),
    },
    {
      title: "更新时间",
      dataIndex: "updated_at",
      width: 170,
      render: (value?: string | null) => formatDateTime(value),
    },
    {
      title: "操作",
      key: "actions",
      width: 230,
      render: (_, item) => {
        const isDeleting = deletingBackupKey === item.key;
        return (
          <Space wrap>
            <Button size="small" icon={<Download className="size-3.5" />} onClick={() => void handleDownload(item.key, item.name)}>
              下载
            </Button>
            <Button size="small" icon={<Eye className="size-3.5" />} onClick={() => void handleOpenDetail(item.key)}>
              详情
            </Button>
            <Button size="small" danger icon={<Trash2 className="size-3.5" />} loading={isDeleting} onClick={() => confirmRemove(item)}>
              删除
            </Button>
          </Space>
        );
      },
    },
  ];

  return (
    <>
      <Card
        title={
          <Space>
            <CloudUpload className="size-4 text-blue-500" />
            <span>R2 备份管理</span>
            <Tag color={statusColor}>{statusText}</Tag>
          </Space>
        }
        extra={
          <Space wrap>
            <Button icon={<Shield className="size-4" />} loading={isTestingBackup} onClick={() => void testBackup()}>
              测试连接
            </Button>
            <Button icon={<RefreshCcw className="size-4" />} loading={isLoadingBackups} onClick={() => void loadBackups()}>
              刷新列表
            </Button>
            <Button icon={<Play className="size-4" />} loading={isRunningBackup || Boolean(backupState?.running)} disabled={isRunningBackup || Boolean(backupState?.running)} onClick={() => void runBackup()}>
              立即备份
            </Button>
            <Button type="primary" icon={<CloudUpload className="size-4" />} loading={isSavingConfig} onClick={() => void saveConfig()}>
              保存配置
            </Button>
          </Space>
        }
      >
        <Space direction="vertical" size={20} className="w-full">
          <Alert
            type="info"
            showIcon
            title="备份说明"
            description="账号与用户密钥会从当前存储后端导出逻辑快照，不依赖底层存储类型。图片目录默认不备份，避免备份体积过大。"
          />

          <Descriptions bordered size="small" column={{ xs: 1, md: 3 }}>
            <Descriptions.Item label="最近开始">{formatDateTime(backupState?.last_started_at)}</Descriptions.Item>
            <Descriptions.Item label="最近完成">{formatDateTime(backupState?.last_finished_at)}</Descriptions.Item>
            <Descriptions.Item label="最近对象">{backupState?.last_object_key || "-"}</Descriptions.Item>
          </Descriptions>
          {backupState?.last_error ? <Alert type="error" showIcon title="最近错误" description={backupState.last_error} /> : null}

          <Card size="small" title="R2 配置">
            <Form layout="vertical" requiredMark={false}>
              <div className="mb-4 grid gap-3 md:grid-cols-2">
                <Checkbox checked={Boolean(backup.enabled)} onChange={(event) => setBackupField("enabled", event.target.checked)}>
                  启用定时备份
                </Checkbox>
                <Checkbox checked={Boolean(backup.encrypt)} onChange={(event) => setBackupField("encrypt", event.target.checked)}>
                  启用备份加密
                </Checkbox>
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                <Form.Item label="Cloudflare Account ID" className="!mb-0">
                  <Input value={String(backup.account_id || "")} onChange={(event) => setBackupField("account_id", event.target.value)} />
                </Form.Item>
                <Form.Item label="Bucket 名称" className="!mb-0">
                  <Input value={String(backup.bucket || "")} onChange={(event) => setBackupField("bucket", event.target.value)} />
                </Form.Item>
                <Form.Item label="Access Key ID" className="!mb-0">
                  <Input value={String(backup.access_key_id || "")} onChange={(event) => setBackupField("access_key_id", event.target.value)} />
                </Form.Item>
                <Form.Item label="Secret Access Key" className="!mb-0">
                  <Input.Password value={String(backup.secret_access_key || "")} onChange={(event) => setBackupField("secret_access_key", event.target.value)} />
                </Form.Item>
                <Form.Item label="备份前缀" extra="R2 内对象前缀，例如 backups/prod。" className="!mb-0">
                  <Input value={String(backup.prefix || "")} onChange={(event) => setBackupField("prefix", event.target.value)} placeholder="backups" />
                </Form.Item>
                <Form.Item label="定时备份间隔" extra="单位分钟，服务启动后会按此间隔自动轮询执行。" className="!mb-0">
                  <Input value={String(backup.interval_minutes || "")} onChange={(event) => setBackupField("interval_minutes", event.target.value)} placeholder="360" />
                </Form.Item>
                <Form.Item label="保留备份数量" extra="填 0 表示不自动轮替。" className="!mb-0">
                  <Input value={String(backup.rotation_keep || "")} onChange={(event) => setBackupField("rotation_keep", event.target.value)} placeholder="10" />
                </Form.Item>
                <Form.Item label="加密口令" extra="仅在启用加密时使用；丢失后无法解密备份内容。" className="!mb-0">
                  <Input.Password value={String(backup.passphrase || "")} onChange={(event) => setBackupField("passphrase", event.target.value)} placeholder={backup.encrypt ? "启用加密后必填" : "留空"} />
                </Form.Item>
              </div>
            </Form>
          </Card>

          <Card size="small" title="备份内容">
            <Checkbox.Group
              value={includeLabels.filter((item) => backup.include[item.key]).map((item) => item.key)}
              onChange={(values) => {
                for (const item of includeLabels) {
                  setBackupInclude(item.key, values.includes(item.key));
                }
              }}
              className="grid gap-3 md:grid-cols-3"
            >
              {includeLabels.map((item) => (
                <Checkbox key={item.key} value={item.key}>
                  {item.label}
                </Checkbox>
              ))}
            </Checkbox.Group>
          </Card>

          <Card size="small" title="历史备份">
            {backups.length === 0 && !isLoadingBackups ? (
              <Empty description="暂无远端备份记录。保存配置并执行一次手动备份后会出现在这里。" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            ) : (
              <Table rowKey="key" loading={isLoadingBackups} columns={columns} dataSource={backups} pagination={false} scroll={{ x: 760 }} />
            )}
          </Card>
        </Space>
      </Card>

      <Modal
        title="备份详情"
        open={detailOpen}
        onCancel={() => setDetailOpen(false)}
        footer={null}
        width={760}
      >
        <Spin spinning={detailLoading}>
          {!detail && !detailLoading ? (
            <Empty description="暂时无法读取备份详情；如果这是加密备份，请确认当前已填写正确的加密口令并先保存配置。" />
          ) : detail ? (
            <Space direction="vertical" size={16} className="mt-4 w-full">
              <Descriptions bordered size="small" column={1}>
                <Descriptions.Item label="对象名称">{detail.name}</Descriptions.Item>
                <Descriptions.Item label="创建时间">{formatDateTime(detail.created_at)}</Descriptions.Item>
                <Descriptions.Item label="触发方式">{detail.trigger || "-"}</Descriptions.Item>
                <Descriptions.Item label="应用版本">{detail.app_version || "-"}</Descriptions.Item>
              </Descriptions>
              <Card size="small" title="存储后端">
                <pre className="max-h-56 overflow-auto rounded bg-slate-950 p-3 text-xs text-slate-100">{JSON.stringify(detail.storage_backend || {}, null, 2)}</pre>
              </Card>
              <Card size="small" title="文件内容">
                <Table
                  rowKey="name"
                  size="small"
                  pagination={false}
                  dataSource={detail.files}
                  columns={[
                    { title: "文件", dataIndex: "name", render: (value: string) => <Typography.Text className="break-all">{value}</Typography.Text> },
                    { title: "状态", dataIndex: "exists", width: 90, render: (value: boolean) => <Tag color={value ? "green" : "default"}>{value ? "已包含" : "缺失"}</Tag> },
                    { title: "大小", dataIndex: "size", width: 100, render: (value: number) => formatBytes(value) },
                  ]}
                  scroll={{ x: 620 }}
                />
              </Card>
              <Card size="small" title="快照内容">
                <Table
                  rowKey="name"
                  size="small"
                  pagination={false}
                  dataSource={detail.snapshots}
                  columns={[
                    { title: "快照", dataIndex: "name" },
                    { title: "记录数", dataIndex: "count", width: 120 },
                  ]}
                />
              </Card>
            </Space>
          ) : null}
        </Spin>
      </Modal>
    </>
  );
}
