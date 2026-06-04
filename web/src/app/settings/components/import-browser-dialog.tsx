"use client";

import { useMemo } from "react";
import { Button, Input, Modal, Select, Space, Table, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { Import, Search } from "lucide-react";

import type { CPARemoteFile } from "@/lib/api";

import { PAGE_SIZE_OPTIONS, useSettingsStore } from "../store";

export function ImportBrowserDialog() {
  const browserOpen = useSettingsStore((state) => state.browserOpen);
  const browserPool = useSettingsStore((state) => state.browserPool);
  const remoteFiles = useSettingsStore((state) => state.remoteFiles);
  const selectedNames = useSettingsStore((state) => state.selectedNames);
  const fileQuery = useSettingsStore((state) => state.fileQuery);
  const filePage = useSettingsStore((state) => state.filePage);
  const pageSize = useSettingsStore((state) => state.pageSize);
  const isStartingImport = useSettingsStore((state) => state.isStartingImport);
  const setBrowserOpen = useSettingsStore((state) => state.setBrowserOpen);
  const replaceSelectedNames = useSettingsStore((state) => state.replaceSelectedNames);
  const setFileQuery = useSettingsStore((state) => state.setFileQuery);
  const setFilePage = useSettingsStore((state) => state.setFilePage);
  const setPageSize = useSettingsStore((state) => state.setPageSize);
  const startImport = useSettingsStore((state) => state.startImport);

  const filteredFiles = useMemo(() => {
    const query = fileQuery.trim().toLowerCase();
    if (!query) {
      return remoteFiles;
    }
    return remoteFiles.filter((item) => item.email.toLowerCase().includes(query) || item.name.toLowerCase().includes(query));
  }, [fileQuery, remoteFiles]);

  const currentPageSize = Number(pageSize);
  const filePageCount = Math.max(1, Math.ceil(filteredFiles.length / currentPageSize));
  const safeFilePage = Math.min(filePage, filePageCount);

  const columns: ColumnsType<CPARemoteFile> = [
    {
      title: "账号",
      dataIndex: "email",
      render: (_, item) => (
        <Space direction="vertical" size={2}>
          <Typography.Text strong>{item.email || item.name}</Typography.Text>
          <Typography.Text type="secondary" className="break-all">{item.name}</Typography.Text>
        </Space>
      ),
    },
  ];

  return (
    <Modal
      title="选择要导入的账号"
      open={browserOpen}
      onCancel={() => setBrowserOpen(false)}
      width={920}
      okText="导入选中账号"
      cancelText="取消"
      confirmLoading={isStartingImport}
      okButtonProps={{ disabled: selectedNames.length === 0, icon: <Import className="size-4" /> }}
      onOk={() => void startImport()}
    >
      <Space direction="vertical" size={16} className="mt-4 w-full">
        <Typography.Text type="secondary">
          {browserPool ? `来自 ${browserPool.name || browserPool.base_url}` : "读取到的远程账号列表"}
        </Typography.Text>

        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <Input
            prefix={<Search className="size-4 text-slate-400" />}
            value={fileQuery}
            onChange={(event) => setFileQuery(event.target.value)}
            placeholder="搜索 email 或文件名"
            className="max-w-sm"
          />
          <Space>
            <Select
              value={pageSize}
              onChange={(value) => setPageSize(value)}
              options={PAGE_SIZE_OPTIONS.map((item) => ({ value: item, label: `${item} / 页` }))}
              className="w-32"
            />
            <Button onClick={() => replaceSelectedNames(filteredFiles.map((item) => item.name))}>
              全选筛选结果
            </Button>
            <Button onClick={() => replaceSelectedNames([])}>
              清空
            </Button>
          </Space>
        </div>

        <Table
          rowKey="name"
          columns={columns}
          dataSource={filteredFiles}
          size="small"
          scroll={{ y: 420 }}
          rowSelection={{
            selectedRowKeys: selectedNames,
            onChange: (keys) => replaceSelectedNames(keys.map(String)),
          }}
          pagination={{
            current: safeFilePage,
            pageSize: currentPageSize,
            total: filteredFiles.length,
            showSizeChanger: false,
            onChange: (page) => setFilePage(page),
          }}
        />
      </Space>
    </Modal>
  );
}
