"use client";

import { Alert, Button, Card, Empty, List, Progress, Space, Spin, Tag, Typography } from "antd";
import { Import, Pencil, Plus, ServerCog, Trash2 } from "lucide-react";

import { useSettingsStore } from "../store";

function getJobColor(status: string) {
  if (status === "completed") {
    return "success";
  }
  if (status === "failed") {
    return "error";
  }
  return "processing";
}

export function CPAPoolsCard() {
  const pools = useSettingsStore((state) => state.pools);
  const isLoadingPools = useSettingsStore((state) => state.isLoadingPools);
  const deletingId = useSettingsStore((state) => state.deletingId);
  const loadingFilesId = useSettingsStore((state) => state.loadingFilesId);
  const openAddDialog = useSettingsStore((state) => state.openAddDialog);
  const openEditDialog = useSettingsStore((state) => state.openEditDialog);
  const deletePool = useSettingsStore((state) => state.deletePool);
  const browseFiles = useSettingsStore((state) => state.browseFiles);

  return (
    <Card
      title={
        <Space>
          <ServerCog className="size-4 text-blue-500" />
          <span>CPA 连接</span>
          {pools.length > 0 ? <Tag>{pools.length} 个</Tag> : null}
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
          先配置连接，再按需查询远程账号并选择导入到本地号池。
        </Typography.Text>

        <Spin spinning={isLoadingPools}>
          {pools.length === 0 && !isLoadingPools ? (
            <Empty description="暂无 CPA 连接" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          ) : (
            <List
              itemLayout="vertical"
              dataSource={pools}
              split
              renderItem={(pool) => {
                const isBusy = deletingId === pool.id || loadingFilesId === pool.id;
                const importJob = pool.import_job ?? null;
                const progress = importJob?.total ? Math.round((importJob.completed / importJob.total) * 100) : 0;

                return (
                  <List.Item
                    actions={[
                      <Button key="sync" size="small" icon={<Import className="size-3.5" />} loading={loadingFilesId === pool.id} disabled={isBusy} onClick={() => void browseFiles(pool)}>
                        同步
                      </Button>,
                      <Button key="edit" size="small" icon={<Pencil className="size-3.5" />} disabled={isBusy} onClick={() => openEditDialog(pool)}>
                        编辑
                      </Button>,
                      <Button key="delete" size="small" danger icon={<Trash2 className="size-3.5" />} loading={deletingId === pool.id} disabled={isBusy} onClick={() => void deletePool(pool)}>
                        删除
                      </Button>,
                    ]}
                  >
                    <List.Item.Meta
                      title={<Typography.Text strong>{pool.name || pool.base_url}</Typography.Text>}
                      description={<Typography.Text type="secondary" className="break-all">{pool.base_url}</Typography.Text>}
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
          description="点击某个连接的「同步」后，会先读取远程账号列表并展示给前端选择；确认选择后，后端后台下载 access_token 并导入本地号池。"
        />
      </Space>
    </Card>
  );
}
