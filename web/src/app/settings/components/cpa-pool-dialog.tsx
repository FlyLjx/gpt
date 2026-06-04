"use client";

import { Form, Input, Modal } from "antd";

import { useSettingsStore } from "../store";

export function CPAPoolDialog() {
  const dialogOpen = useSettingsStore((state) => state.dialogOpen);
  const editingPool = useSettingsStore((state) => state.editingPool);
  const formName = useSettingsStore((state) => state.formName);
  const formBaseUrl = useSettingsStore((state) => state.formBaseUrl);
  const formSecretKey = useSettingsStore((state) => state.formSecretKey);
  const isSavingPool = useSettingsStore((state) => state.isSavingPool);
  const setDialogOpen = useSettingsStore((state) => state.setDialogOpen);
  const setFormName = useSettingsStore((state) => state.setFormName);
  const setFormBaseUrl = useSettingsStore((state) => state.setFormBaseUrl);
  const setFormSecretKey = useSettingsStore((state) => state.setFormSecretKey);
  const savePool = useSettingsStore((state) => state.savePool);

  return (
    <Modal
      title={editingPool ? "编辑 CPA 连接" : "添加 CPA 连接"}
      open={dialogOpen}
      onCancel={() => setDialogOpen(false)}
      onOk={() => void savePool()}
      okText={editingPool ? "保存修改" : "添加"}
      cancelText="取消"
      confirmLoading={isSavingPool}
    >
      <Form layout="vertical" className="mt-4">
        <Form.Item label="名称（可选）">
          <Input value={formName} onChange={(event) => setFormName(event.target.value)} placeholder="例如：主号池、备用池" />
        </Form.Item>
        <Form.Item label="CPA 地址" required>
          <Input value={formBaseUrl} onChange={(event) => setFormBaseUrl(event.target.value)} placeholder="http://your-cpa-host:8317" />
        </Form.Item>
        <Form.Item label="Management Secret Key" extra={editingPool ? "留空则不修改密钥。" : undefined} required={!editingPool}>
          <Input.Password value={formSecretKey} onChange={(event) => setFormSecretKey(event.target.value)} placeholder={editingPool ? "留空则不修改密钥" : "CPA 管理密钥"} />
        </Form.Item>
      </Form>
    </Modal>
  );
}
