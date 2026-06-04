"use client";

import { useEffect, useRef, useState } from "react";
import { Alert, Button, Card, Empty, Form, Input, List, Modal, Space, Spin, Tag, Typography } from "antd";
import { Ban, CheckCircle2, Copy, KeyRound, Pencil, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { createUserKey, deleteUserKey, fetchUserKeys, updateUserKey, type UserKey } from "@/lib/api";

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

export function UserKeysCard() {
  const didLoadRef = useRef(false);
  const [items, setItems] = useState<UserKey[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [name, setName] = useState("");
  const [isCreating, setIsCreating] = useState(false);
  const [pendingIds, setPendingIds] = useState<Set<string>>(() => new Set());
  const [revealedKey, setRevealedKey] = useState("");
  const [editingItem, setEditingItem] = useState<UserKey | null>(null);
  const [editName, setEditName] = useState("");
  const [editKey, setEditKey] = useState("");

  const load = async () => {
    setIsLoading(true);
    try {
      const data = await fetchUserKeys();
      setItems(data.items);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "加载用户密钥失败");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (didLoadRef.current) {
      return;
    }
    didLoadRef.current = true;
    void load();
  }, []);

  const handleCreate = async () => {
    setIsCreating(true);
    try {
      const data = await createUserKey(name.trim());
      setItems(data.items);
      setRevealedKey(data.key);
      setName("");
      setIsDialogOpen(false);
      toast.success("用户密钥已创建");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "创建用户密钥失败");
    } finally {
      setIsCreating(false);
    }
  };

  const setItemPending = (id: string, isPending: boolean) => {
    setPendingIds((current) => {
      const next = new Set(current);
      if (isPending) {
        next.add(id);
      } else {
        next.delete(id);
      }
      return next;
    });
  };

  const handleToggle = async (item: UserKey) => {
    setItemPending(item.id, true);
    try {
      const data = await updateUserKey(item.id, { enabled: !item.enabled });
      setItems(data.items);
      toast.success(item.enabled ? "用户密钥已禁用" : "用户密钥已启用");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "更新用户密钥失败");
    } finally {
      setItemPending(item.id, false);
    }
  };

  const handleDelete = async (item: UserKey) => {
    setItemPending(item.id, true);
    try {
      const data = await deleteUserKey(item.id);
      setItems(data.items);
      toast.success("用户密钥已删除");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "删除用户密钥失败");
    } finally {
      setItemPending(item.id, false);
    }
  };

  const openEditDialog = (item: UserKey) => {
    setEditingItem(item);
    setEditName(item.name);
    setEditKey("");
  };

  const handleEdit = async () => {
    if (!editingItem) {
      return;
    }
    const item = editingItem;
    const trimmedName = editName.trim();
    const trimmedKey = editKey.trim();
    if (trimmedName === item.name && !trimmedKey) {
      setEditingItem(null);
      return;
    }
    setItemPending(item.id, true);
    try {
      const data = await updateUserKey(item.id, {
        ...(trimmedName !== item.name ? { name: trimmedName } : {}),
        ...(trimmedKey ? { key: trimmedKey } : {}),
      });
      setItems(data.items);
      setEditingItem(null);
      setEditKey("");
      toast.success(trimmedKey ? "用户密钥已更新" : "用户名称已更新");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "更新用户密钥失败");
    } finally {
      setItemPending(item.id, false);
    }
  };

  const handleCopy = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      toast.success("已复制到剪贴板");
    } catch {
      toast.error("复制失败，请手动复制");
    }
  };

  const confirmDelete = (item: UserKey) => {
    Modal.confirm({
      title: "删除用户密钥",
      content: `确认删除用户密钥「${item.name}」吗？删除后该密钥将无法继续调用接口。`,
      okText: "删除",
      cancelText: "取消",
      okButtonProps: { danger: true },
      onOk: () => handleDelete(item),
    });
  };

  return (
    <>
      <Card
        title={
          <Space>
            <KeyRound className="size-4 text-blue-500" />
            <span>用户密钥</span>
          </Space>
        }
        extra={
          <Button type="primary" icon={<Plus className="size-4" />} onClick={() => setIsDialogOpen(true)}>
            创建
          </Button>
        }
      >
        <Space direction="vertical" size={16} className="w-full">
          <Typography.Text type="secondary">
            为普通用户创建专用密钥；普通用户只能进入画图页，不能查看设置和号池。
          </Typography.Text>

          {revealedKey ? (
            <Alert
              type="success"
              showIcon
              title="新密钥仅展示一次，请立即保存"
              description={
                <Space direction="vertical" size={10} className="w-full">
                  <Typography.Text code copyable={{ text: revealedKey }} className="break-all">
                    {revealedKey}
                  </Typography.Text>
                  <Button size="small" icon={<Copy className="size-3.5" />} onClick={() => void handleCopy(revealedKey)}>
                    复制密钥
                  </Button>
                </Space>
              }
            />
          ) : null}

          <Spin spinning={isLoading}>
            {items.length === 0 && !isLoading ? (
              <Empty description="暂无普通用户密钥" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            ) : (
              <List
                itemLayout="vertical"
                dataSource={items}
                split
                renderItem={(item) => {
                  const isPending = pendingIds.has(item.id);
                  return (
                    <List.Item
                      actions={[
                        <Button key="edit" size="small" icon={<Pencil className="size-3.5" />} disabled={isPending} onClick={() => openEditDialog(item)}>
                          编辑
                        </Button>,
                        <Button key="toggle" size="small" icon={item.enabled ? <Ban className="size-3.5" /> : <CheckCircle2 className="size-3.5" />} loading={isPending} onClick={() => void handleToggle(item)}>
                          {item.enabled ? "禁用" : "启用"}
                        </Button>,
                        <Button key="delete" size="small" danger icon={<Trash2 className="size-3.5" />} disabled={isPending} onClick={() => confirmDelete(item)}>
                          删除
                        </Button>,
                      ]}
                    >
                      <List.Item.Meta
                        title={
                          <Space size={8} wrap>
                            <Typography.Text strong>{item.name}</Typography.Text>
                            <Tag color={item.enabled ? "green" : "default"}>{item.enabled ? "已启用" : "已禁用"}</Tag>
                          </Space>
                        }
                        description={
                          <Space direction="vertical" size={2}>
                            <Typography.Text type="secondary">创建时间 {formatDateTime(item.created_at)}</Typography.Text>
                            <Typography.Text type="secondary">最近使用 {formatDateTime(item.last_used_at)}</Typography.Text>
                          </Space>
                        }
                      />
                    </List.Item>
                  );
                }}
              />
            )}
          </Spin>
        </Space>
      </Card>

      <Modal
        title="创建用户密钥"
        open={isDialogOpen}
        onCancel={() => setIsDialogOpen(false)}
        onOk={() => void handleCreate()}
        okText="创建"
        cancelText="取消"
        confirmLoading={isCreating}
      >
        <Form layout="vertical" className="mt-4">
          <Form.Item label="名称（可选）" extra="方便区分不同使用者；创建后会生成一条只能查看一次的原始密钥。">
            <Input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：设计同学 A、运营临时账号" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="编辑用户密钥"
        open={Boolean(editingItem)}
        onCancel={() => {
          setEditingItem(null);
          setEditKey("");
        }}
        onOk={() => void handleEdit()}
        okText="保存"
        cancelText="取消"
        confirmLoading={editingItem ? pendingIds.has(editingItem.id) : false}
      >
        <Form layout="vertical" className="mt-4">
          <Form.Item label="名称">
            <Input value={editName} onChange={(event) => setEditName(event.target.value)} placeholder="例如：设计同学 A、运营临时账号" />
          </Form.Item>
          <Form.Item label="新的专用密钥（可选）" extra="留空则保持当前密钥不变。保存后旧密钥会立即失效。">
            <Input value={editKey} onChange={(event) => setEditKey(event.target.value)} placeholder="例如：sk-your-custom-user-key" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
