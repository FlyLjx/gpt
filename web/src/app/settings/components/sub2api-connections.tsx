"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Card, Empty, Form, Input, List, Modal, Progress, Select, Space, Spin, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { Import, Layers, Pencil, Plus, RefreshCcw, ServerCog, Trash2 } from "lucide-react";
import { toast } from "sonner";

import {
  createSub2APIServer,
  deleteSub2APIServer,
  fetchSub2APIServerAccounts,
  fetchSub2APIServerGroups,
  fetchSub2APIServers,
  startSub2APIImport,
  updateSub2APIServer,
  type Sub2APIRemoteAccount,
  type Sub2APIRemoteGroup,
  type Sub2APIServer,
} from "@/lib/api";

const PAGE_SIZE_OPTIONS = ["50", "100", "200"] as const;

type AuthMode = "password" | "api_key";

function normalizeAccounts(items: Sub2APIRemoteAccount[]) {
  const seen = new Set<string>();
  const accounts: Sub2APIRemoteAccount[] = [];
  for (const item of items) {
    const id = String(item.id || "").trim();
    if (!id || seen.has(id)) {
      continue;
    }
    seen.add(id);
    accounts.push({
      id,
      name: String(item.name || "").trim(),
      email: String(item.email || "").trim(),
      plan_type: String(item.plan_type || "").trim(),
      status: String(item.status || "").trim(),
      expires_at: String(item.expires_at || "").trim(),
      has_refresh_token: Boolean(item.has_refresh_token),
    });
  }
  return accounts;
}

function getJobColor(status: string) {
  if (status === "completed") {
    return "success";
  }
  if (status === "failed") {
    return "error";
  }
  return "processing";
}

export function Sub2APIConnections() {
  const didLoadRef = useRef(false);
  const pollTimerRef = useRef<number | null>(null);

  const [servers, setServers] = useState<Sub2APIServer[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingServer, setEditingServer] = useState<Sub2APIServer | null>(null);
  const [formName, setFormName] = useState("");
  const [formBaseUrl, setFormBaseUrl] = useState("");
  const [formEmail, setFormEmail] = useState("");
  const [formPassword, setFormPassword] = useState("");
  const [formApiKey, setFormApiKey] = useState("");
  const [formGroupId, setFormGroupId] = useState("");
  const [authMode, setAuthMode] = useState<AuthMode>("password");
  const [isSaving, setIsSaving] = useState(false);
  const [remoteGroups, setRemoteGroups] = useState<Sub2APIRemoteGroup[] | null>(null);
  const [isLoadingGroups, setIsLoadingGroups] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [loadingAccountsId, setLoadingAccountsId] = useState<string | null>(null);
  const [browserOpen, setBrowserOpen] = useState(false);
  const [browserServer, setBrowserServer] = useState<Sub2APIServer | null>(null);
  const [remoteAccounts, setRemoteAccounts] = useState<Sub2APIRemoteAccount[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [accountQuery, setAccountQuery] = useState("");
  const [accountPage, setAccountPage] = useState(1);
  const [pageSize, setPageSize] = useState<(typeof PAGE_SIZE_OPTIONS)[number]>("100");
  const [isStartingImport, setIsStartingImport] = useState(false);

  const loadServers = async () => {
    setIsLoading(true);
    try {
      const data = await fetchSub2APIServers();
      setServers(data.servers);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "加载 Sub2API 连接失败");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (didLoadRef.current) {
      return;
    }
    didLoadRef.current = true;
    void loadServers();
  }, []);

  useEffect(() => {
    const hasRunningJobs = servers.some((server) => server.import_job?.status === "pending" || server.import_job?.status === "running");
    if (!hasRunningJobs) {
      if (pollTimerRef.current !== null) {
        window.clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
      return;
    }

    pollTimerRef.current = window.setInterval(() => {
      void fetchSub2APIServers()
        .then((data) => setServers(data.servers))
        .catch((error) => {
          if (pollTimerRef.current !== null) {
            window.clearInterval(pollTimerRef.current);
            pollTimerRef.current = null;
          }
          toast.error(error instanceof Error ? error.message : "查询导入进度失败");
        });
    }, 1500);

    return () => {
      if (pollTimerRef.current !== null) {
        window.clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
  }, [servers]);

  const openAddDialog = () => {
    setEditingServer(null);
    setFormName("");
    setFormBaseUrl("");
    setFormEmail("");
    setFormPassword("");
    setFormApiKey("");
    setFormGroupId("");
    setAuthMode("password");
    setRemoteGroups(null);
    setDialogOpen(true);
  };

  const openEditDialog = (server: Sub2APIServer) => {
    setEditingServer(server);
    setFormName(server.name);
    setFormBaseUrl(server.base_url);
    setFormEmail(server.email);
    setFormPassword("");
    setFormApiKey("");
    setFormGroupId(server.group_id || "");
    setAuthMode(server.has_api_key ? "api_key" : "password");
    setRemoteGroups(null);
    setDialogOpen(true);
  };

  const handleFetchGroups = async () => {
    if (!editingServer) {
      toast.error("请先保存连接后再拉取分组");
      return;
    }
    setIsLoadingGroups(true);
    try {
      const data = await fetchSub2APIServerGroups(editingServer.id);
      setRemoteGroups(data.groups);
      if (data.groups.length === 0) {
        toast.message("远端没有配置分组");
      } else {
        toast.success(`读取到 ${data.groups.length} 个分组`);
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "拉取分组失败");
    } finally {
      setIsLoadingGroups(false);
    }
  };

  const handleSave = async () => {
    if (!formBaseUrl.trim()) {
      toast.error("请输入 Sub2API 地址");
      return;
    }
    if (authMode === "password") {
      if (!formEmail.trim()) {
        toast.error("请输入管理员邮箱");
        return;
      }
      if (!editingServer && !formPassword.trim()) {
        toast.error("请输入管理员密码");
        return;
      }
    } else if (!editingServer && !formApiKey.trim()) {
      toast.error("请输入 Admin API Key");
      return;
    }

    setIsSaving(true);
    try {
      if (editingServer) {
        const updates: Parameters<typeof updateSub2APIServer>[1] = {
          name: formName.trim(),
          base_url: formBaseUrl.trim(),
          group_id: formGroupId.trim(),
        };
        if (authMode === "password") {
          updates.email = formEmail.trim();
          if (formPassword.trim()) {
            updates.password = formPassword.trim();
          }
          updates.api_key = "";
        } else {
          if (formApiKey.trim()) {
            updates.api_key = formApiKey.trim();
          }
          updates.email = "";
          updates.password = "";
        }
        const data = await updateSub2APIServer(editingServer.id, updates);
        setServers(data.servers);
        toast.success("连接已更新");
      } else {
        const data = await createSub2APIServer({
          name: formName.trim(),
          base_url: formBaseUrl.trim(),
          email: authMode === "password" ? formEmail.trim() : "",
          password: authMode === "password" ? formPassword.trim() : "",
          api_key: authMode === "api_key" ? formApiKey.trim() : "",
          group_id: formGroupId.trim(),
        });
        setServers(data.servers);
        toast.success("连接已添加");
      }
      setDialogOpen(false);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "保存失败");
    } finally {
      setIsSaving(false);
    }
  };

  const handleDelete = async (server: Sub2APIServer) => {
    setDeletingId(server.id);
    try {
      const data = await deleteSub2APIServer(server.id);
      setServers(data.servers);
      toast.success("连接已删除");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "删除失败");
    } finally {
      setDeletingId(null);
    }
  };

  const confirmDelete = (server: Sub2APIServer) => {
    Modal.confirm({
      title: "删除 Sub2API 连接",
      content: `确认删除「${server.name || server.base_url}」吗？`,
      okText: "删除",
      cancelText: "取消",
      okButtonProps: { danger: true },
      onOk: () => handleDelete(server),
    });
  };

  const handleBrowseAccounts = async (server: Sub2APIServer) => {
    setLoadingAccountsId(server.id);
    try {
      const data = await fetchSub2APIServerAccounts(server.id);
      const accounts = normalizeAccounts(data.accounts);
      setBrowserServer(server);
      setRemoteAccounts(accounts);
      setSelectedIds([]);
      setAccountQuery("");
      setAccountPage(1);
      setBrowserOpen(true);
      toast.success(`读取成功，共 ${accounts.length} 个 OpenAI 账号`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "读取 Sub2API 账号失败");
    } finally {
      setLoadingAccountsId(null);
    }
  };

  const filteredAccounts = useMemo(() => {
    const query = accountQuery.trim().toLowerCase();
    if (!query) {
      return remoteAccounts;
    }
    return remoteAccounts.filter((item) => {
      return (
        item.email.toLowerCase().includes(query) ||
        item.name.toLowerCase().includes(query) ||
        item.plan_type.toLowerCase().includes(query) ||
        item.id.toLowerCase().includes(query)
      );
    });
  }, [accountQuery, remoteAccounts]);

  const currentPageSize = Number(pageSize);
  const accountPageCount = Math.max(1, Math.ceil(filteredAccounts.length / currentPageSize));
  const safeAccountPage = Math.min(accountPage, accountPageCount);

  const handleStartImport = async () => {
    if (!browserServer) {
      return;
    }
    if (selectedIds.length === 0) {
      toast.error("请先选择要导入的账号");
      return;
    }

    setIsStartingImport(true);
    try {
      const result = await startSub2APIImport(browserServer.id, selectedIds);
      setServers((prev) => prev.map((server) => (server.id === browserServer.id ? { ...server, import_job: result.import_job } : server)));
      setBrowserOpen(false);
      toast.success("导入任务已启动");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "启动导入失败");
    } finally {
      setIsStartingImport(false);
    }
  };

  const accountColumns: ColumnsType<Sub2APIRemoteAccount> = [
    {
      title: "账号",
      dataIndex: "email",
      render: (_, item) => (
        <Space direction="vertical" size={2}>
          <Space wrap>
            <Typography.Text strong>{item.email || item.name || item.id}</Typography.Text>
            {item.plan_type ? <Tag>{item.plan_type}</Tag> : null}
            {item.status ? <Tag color={item.status === "active" ? "green" : "blue"}>{item.status}</Tag> : null}
          </Space>
          <Typography.Text type="secondary" className="break-all">
            id {item.id}
            {item.expires_at ? ` · 过期 ${item.expires_at}` : ""}
          </Typography.Text>
        </Space>
      ),
    },
  ];

  return (
    <>
      <Card
        title={
          <Space>
            <ServerCog className="size-4 text-blue-500" />
            <span>Sub2API 连接</span>
            {servers.length > 0 ? <Tag>{servers.length} 个</Tag> : null}
          </Space>
        }
        extra={
          <Button type="primary" icon={<Plus className="size-4" />} onClick={openAddDialog}>
            添加
          </Button>
        }
      >
        <Space direction="vertical" size={16} className="w-full">
          <Typography.Text type="secondary">
            配置 Sub2API 服务器后，可查询其中的 OpenAI OAuth 账号并批量导入本地号池。
          </Typography.Text>

          <Spin spinning={isLoading}>
            {servers.length === 0 && !isLoading ? (
              <Empty description="暂无 Sub2API 连接" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            ) : (
              <List
                itemLayout="vertical"
                dataSource={servers}
                split
                renderItem={(server) => {
                  const isBusy = deletingId === server.id || loadingAccountsId === server.id;
                  const importJob = server.import_job ?? null;
                  const progress = importJob?.total ? Math.round((importJob.completed / importJob.total) * 100) : 0;

                  return (
                    <List.Item
                      actions={[
                        <Button key="sync" size="small" icon={<Import className="size-3.5" />} loading={loadingAccountsId === server.id} disabled={isBusy} onClick={() => void handleBrowseAccounts(server)}>
                          同步
                        </Button>,
                        <Button key="edit" size="small" icon={<Pencil className="size-3.5" />} disabled={isBusy} onClick={() => openEditDialog(server)}>
                          编辑
                        </Button>,
                        <Button key="delete" size="small" danger icon={<Trash2 className="size-3.5" />} loading={deletingId === server.id} disabled={isBusy} onClick={() => confirmDelete(server)}>
                          删除
                        </Button>,
                      ]}
                    >
                      <List.Item.Meta
                        title={<Typography.Text strong>{server.name || server.base_url}</Typography.Text>}
                        description={
                          <Typography.Text type="secondary" className="break-all">
                            {server.base_url}
                            {server.email ? ` · ${server.email}` : server.has_api_key ? " · API Key" : ""}
                            {server.group_id ? ` · 分组 ${server.group_id}` : " · 全部分组"}
                          </Typography.Text>
                        }
                      />

                      {importJob ? (
                        <div className="mt-3 rounded-lg border border-slate-100 bg-slate-50 p-3">
                          <Space direction="vertical" size={8} className="w-full">
                            <Space wrap>
                              <Tag color={getJobColor(importJob.status)}>导入 {importJob.status}</Tag>
                              <Typography.Text type="secondary">
                                已处理 {importJob.completed}/{importJob.total}
                              </Typography.Text>
                            </Space>
                            <Progress percent={progress} size="small" status={importJob.status === "failed" ? "exception" : undefined} />
                            <Typography.Text type="secondary" className="text-xs">
                              新增 {importJob.added}，跳过 {importJob.skipped}，刷新 {importJob.refreshed}，失败 {importJob.failed}
                            </Typography.Text>
                          </Space>
                        </div>
                      ) : null}
                    </List.Item>
                  );
                }}
              />
            )}
          </Spin>

          <Alert
            type="info"
            showIcon
            title="使用说明"
            description="点击「同步」会拉取 platform=openai 且 type=oauth 的账号列表；勾选后端会并发拉取 access_token 并导入本地号池。"
          />
        </Space>
      </Card>

      <Modal
        title={editingServer ? "编辑 Sub2API 连接" : "添加 Sub2API 连接"}
        open={dialogOpen}
        onCancel={() => setDialogOpen(false)}
        onOk={() => void handleSave()}
        okText={editingServer ? "保存修改" : "添加"}
        cancelText="取消"
        confirmLoading={isSaving}
      >
        <Form layout="vertical" className="mt-4">
          <Form.Item label="名称（可选）">
            <Input value={formName} onChange={(event) => setFormName(event.target.value)} placeholder="例如：自建 sub2api" />
          </Form.Item>
          <Form.Item label="Sub2API 地址" required>
            <Input value={formBaseUrl} onChange={(event) => setFormBaseUrl(event.target.value)} placeholder="http://your-sub2api-host:8080" />
          </Form.Item>
          <Form.Item label="认证方式">
            <Select
              value={authMode}
              onChange={(value) => setAuthMode(value as AuthMode)}
              options={[
                { value: "password", label: "管理员邮箱 + 密码" },
                { value: "api_key", label: "Admin API Key" },
              ]}
            />
          </Form.Item>
          {authMode === "password" ? (
            <>
              <Form.Item label="管理员邮箱" required>
                <Input value={formEmail} onChange={(event) => setFormEmail(event.target.value)} placeholder="admin@example.com" />
              </Form.Item>
              <Form.Item label="管理员密码" required={!editingServer} extra={editingServer ? "留空则不修改密码。" : undefined}>
                <Input.Password value={formPassword} onChange={(event) => setFormPassword(event.target.value)} placeholder={editingServer ? "留空则不修改密码" : "管理员密码"} />
              </Form.Item>
            </>
          ) : (
            <Form.Item label="Admin API Key" required={!editingServer} extra={editingServer ? "留空则不修改密钥。" : undefined}>
              <Input.Password value={formApiKey} onChange={(event) => setFormApiKey(event.target.value)} placeholder={editingServer ? "留空则不修改密钥" : "Sub2API Admin API Key"} />
            </Form.Item>
          )}
          <Form.Item
            label={
              <Space size={6}>
                <Layers className="size-3.5" />
                <span>分组（可选）</span>
              </Space>
            }
            extra={editingServer ? "同步时会用分组 ID 过滤，留空 = 同步所有 OpenAI OAuth 账号。" : "添加完连接后可在编辑对话框里拉取分组。"}
          >
            <Space.Compact className="w-full">
              {remoteGroups && remoteGroups.length > 0 ? (
                <Select
                  value={formGroupId || "__all__"}
                  onChange={(value) => setFormGroupId(value === "__all__" ? "" : value)}
                  options={[
                    { value: "__all__", label: "全部分组（不限制）" },
                    { value: "ungrouped", label: "未分组" },
                    ...remoteGroups.map((group) => ({
                      value: group.id,
                      label: `${group.name || `Group ${group.id}`}${group.platform ? `（${group.platform}）` : ""}${group.account_count ? ` · ${group.active_account_count}/${group.account_count}` : ""}`,
                    })),
                  ]}
                  className="w-full"
                />
              ) : (
                <Input value={formGroupId} onChange={(event) => setFormGroupId(event.target.value)} placeholder="留空则同步所有分组；或填写分组 ID / ungrouped" />
              )}
              {editingServer ? (
                <Button icon={<RefreshCcw className="size-4" />} loading={isLoadingGroups} onClick={() => void handleFetchGroups()}>
                  {remoteGroups ? "重拉" : "拉取"}
                </Button>
              ) : null}
            </Space.Compact>
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="选择要导入的账号"
        open={browserOpen}
        onCancel={() => setBrowserOpen(false)}
        width={920}
        okText="导入选中账号"
        cancelText="取消"
        confirmLoading={isStartingImport}
        okButtonProps={{ disabled: selectedIds.length === 0, icon: <Import className="size-4" /> }}
        onOk={() => void handleStartImport()}
      >
        <Space direction="vertical" size={16} className="mt-4 w-full">
          <Typography.Text type="secondary">
            {browserServer ? `来自 ${browserServer.name || browserServer.base_url}` : "Sub2API 上的 OpenAI OAuth 账号"}
          </Typography.Text>
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <Input
              value={accountQuery}
              onChange={(event) => {
                setAccountQuery(event.target.value);
                setAccountPage(1);
              }}
              placeholder="搜索邮箱、套餐、名称或 ID"
              className="max-w-sm"
            />
            <Space>
              <Select
                value={pageSize}
                onChange={(value) => {
                  setPageSize(value as (typeof PAGE_SIZE_OPTIONS)[number]);
                  setAccountPage(1);
                }}
                options={PAGE_SIZE_OPTIONS.map((item) => ({ value: item, label: `${item} / 页` }))}
                className="w-32"
              />
              <Button onClick={() => setSelectedIds(filteredAccounts.map((item) => item.id))}>全选筛选结果</Button>
              <Button onClick={() => setSelectedIds([])}>清空</Button>
            </Space>
          </div>

          <Table
            rowKey="id"
            columns={accountColumns}
            dataSource={filteredAccounts}
            size="small"
            scroll={{ y: 420 }}
            rowSelection={{
              selectedRowKeys: selectedIds,
              onChange: (keys) => setSelectedIds(keys.map(String)),
            }}
            pagination={{
              current: safeAccountPage,
              pageSize: currentPageSize,
              total: filteredAccounts.length,
              showSizeChanger: false,
              onChange: (page) => setAccountPage(page),
            }}
          />
        </Space>
      </Modal>
    </>
  );
}
