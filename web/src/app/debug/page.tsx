"use client";

import { Card, Spin, Tabs, Typography } from "antd";

import { useAuthGuard } from "@/lib/use-auth-guard";

import { ChatPanel } from "./components/chat-panel";
import { PptPanel } from "./components/ppt-panel";
import { PsdPanel } from "./components/psd-panel";
import { SearchPanel } from "./components/search-panel";
import { SkillPanel } from "./components/skill-panel";

const tabs = [
  { value: "skills", title: "搜索Skills" },
  { value: "search", title: "搜索" },
  { value: "ppt", title: "PPT生成" },
  { value: "psd", title: "PSD生成" },
  { value: "chat", title: "对话" },
];

export default function DebugPage() {
  const { isCheckingAuth, session } = useAuthGuard(["admin"]);

  if (isCheckingAuth || !session || session.role !== "admin") {
    return (
      <div className="flex min-h-[calc(100vh-49px)] items-center justify-center">
        <Spin />
      </div>
    );
  }

  return (
    <section className="space-y-4">
      <Card>
        <Typography.Text type="secondary" className="text-xs font-semibold uppercase tracking-[0.18em]">Debug</Typography.Text>
        <Typography.Title level={3} className="!mb-0 !mt-1">调试工具</Typography.Title>
        <Typography.Text type="secondary">集中测试搜索、生成和对话相关接口。</Typography.Text>
      </Card>
      <Card styles={{ body: { paddingTop: 8 } }}>
        <Tabs
          defaultActiveKey="skills"
          items={[
            { key: "skills", label: "搜索Skills", children: <SkillPanel /> },
            { key: "search", label: "搜索", children: <SearchPanel /> },
            { key: "ppt", label: "PPT生成", children: <PptPanel /> },
            { key: "psd", label: "PSD生成", children: <PsdPanel /> },
            { key: "chat", label: "对话", children: <ChatPanel /> },
          ]}
        />
      </Card>
    </section>
  );
}
