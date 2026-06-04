"use client";

import { useState } from "react";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Divider,
  Form,
  Input,
  Row,
  Select,
  Space,
  Switch,
  Tag,
  Typography,
} from "antd";
import { Cloud, LoaderCircle, PlugZap, RefreshCw, Save, ShieldCheck } from "lucide-react";
import { toast } from "sonner";

import type { ImageStorageMode } from "@/lib/api";
import { testProxy, type ProxyTestResult } from "@/lib/api";

import { useSettingsStore } from "../store";

const logLevelOptions = ["debug", "info", "warning", "error"];

function SectionTitle({ title, description }: { title: string; description: string }) {
  return (
    <div className="mb-4">
      <Typography.Title level={5} className="!mb-1">{title}</Typography.Title>
      <Typography.Text type="secondary">{description}</Typography.Text>
    </div>
  );
}

function NumberInput({
  label,
  value,
  onChange,
  placeholder,
  help,
  disabled,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  help?: string;
  disabled?: boolean;
}) {
  return (
    <Form.Item label={label} extra={help}>
      <Input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} disabled={disabled} />
    </Form.Item>
  );
}

function formatProxyExit(result: ProxyTestResult) {
  const exit = result.exit_ip;
  if (!exit?.ip) {
    return "出口信息未返回";
  }
  const location = [exit.city, exit.region, exit.country].filter(Boolean).join(" / ");
  const parts = [`出口 IP：${exit.ip}`];
  if (location) {
    parts.push(`地区：${location}`);
  }
  if (exit.org) {
    parts.push(`运营商：${exit.org}`);
  }
  if (exit.timezone) {
    parts.push(`时区：${exit.timezone}`);
  }
  return parts.join("，");
}

export function ConfigCard() {
  const [isTestingProxy, setIsTestingProxy] = useState(false);
  const [proxyTestResult, setProxyTestResult] = useState<ProxyTestResult | null>(null);
  const config = useSettingsStore((state) => state.config);
  const isLoadingConfig = useSettingsStore((state) => state.isLoadingConfig);
  const isSavingConfig = useSettingsStore((state) => state.isSavingConfig);
  const setRefreshAccountIntervalMinute = useSettingsStore((state) => state.setRefreshAccountIntervalMinute);
  const setRefreshAccountConcurrency = useSettingsStore((state) => state.setRefreshAccountConcurrency);
  const setImageRetentionDays = useSettingsStore((state) => state.setImageRetentionDays);
  const setImagePollTimeoutSecs = useSettingsStore((state) => state.setImagePollTimeoutSecs);
  const setImageAccountConcurrency = useSettingsStore((state) => state.setImageAccountConcurrency);
  const setImageSettleEnabled = useSettingsStore((state) => state.setImageSettleEnabled);
  const setImageSettleSecs = useSettingsStore((state) => state.setImageSettleSecs);
  const setImageTimeoutRetrySecs = useSettingsStore((state) => state.setImageTimeoutRetrySecs);
  const setAutoRemoveInvalidAccounts = useSettingsStore((state) => state.setAutoRemoveInvalidAccounts);
  const setAutoRemoveRateLimitedAccounts = useSettingsStore((state) => state.setAutoRemoveRateLimitedAccounts);
  const setAutoReloginAfterRefresh = useSettingsStore((state) => state.setAutoReloginAfterRefresh);
  const setAutoRefillEnabled = useSettingsStore((state) => state.setAutoRefillEnabled);
  const setAutoRefillThresholdPercent = useSettingsStore((state) => state.setAutoRefillThresholdPercent);
  const setAutoRefillTargetAvailable = useSettingsStore((state) => state.setAutoRefillTargetAvailable);
  const setAutoRefillIntervalMinutes = useSettingsStore((state) => state.setAutoRefillIntervalMinutes);
  const setLogLevel = useSettingsStore((state) => state.setLogLevel);
  const setProxy = useSettingsStore((state) => state.setProxy);
  const setBaseUrl = useSettingsStore((state) => state.setBaseUrl);
  const setGlobalSystemPrompt = useSettingsStore((state) => state.setGlobalSystemPrompt);
  const setSensitiveWordsText = useSettingsStore((state) => state.setSensitiveWordsText);
  const setAIReviewField = useSettingsStore((state) => state.setAIReviewField);
  const setImageStorageField = useSettingsStore((state) => state.setImageStorageField);
  const testImageStorage = useSettingsStore((state) => state.testImageStorage);
  const syncImagesToWebDAV = useSettingsStore((state) => state.syncImagesToWebDAV);
  const isTestingImageStorage = useSettingsStore((state) => state.isTestingImageStorage);
  const isSyncingImageStorage = useSettingsStore((state) => state.isSyncingImageStorage);
  const saveConfig = useSettingsStore((state) => state.saveConfig);

  const handleTestProxy = async () => {
    const candidate = String(config?.proxy || "").trim();
    if (!candidate) {
      toast.error("请先填写代理地址");
      return;
    }
    setIsTestingProxy(true);
    setProxyTestResult(null);
    try {
      const data = await testProxy(candidate);
      setProxyTestResult(data.result);
      if (data.result.ok) {
        toast.success(`代理可用（${data.result.latency_ms} ms，HTTP ${data.result.status}）`);
      } else {
        toast.error(`代理不可用：${data.result.error ?? "未知错误"}`);
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "测试代理失败");
    } finally {
      setIsTestingProxy(false);
    }
  };

  if (isLoadingConfig) {
    return (
      <Card>
        <div className="flex items-center justify-center py-12">
          <LoaderCircle className="size-5 animate-spin text-slate-400" />
        </div>
      </Card>
    );
  }

  if (!config) {
    return null;
  }

  const imageStorageEnabled = Boolean(config.image_storage?.enabled);
  const aiReviewEnabled = Boolean(config.ai_review?.enabled);

  return (
    <Card
      title={
        <Space>
          <ShieldCheck className="size-4 text-blue-500" />
          <span>系统配置</span>
        </Space>
      }
      extra={
        <Button type="primary" icon={isSavingConfig ? <LoaderCircle className="size-4 animate-spin" /> : <Save className="size-4" />} onClick={() => void saveConfig()} disabled={isSavingConfig}>
          保存配置
        </Button>
      }
    >
      <Form layout="vertical" requiredMark={false}>
        <Alert
          type="info"
          showIcon
          className="mb-5"
          title="管理员登录密钥继续从部署配置读取，不在页面展示。需要分发访问权限时，请在用户密钥管理里创建普通用户密钥。"
        />

        <SectionTitle title="基础运行" description="控制账号刷新、代理、图片访问地址和本地图片保留策略。" />
        <Row gutter={[16, 16]}>
          <Col xs={24} md={12} xl={6}>
            <NumberInput label="账号刷新间隔" value={String(config.refresh_account_interval_minute || "")} onChange={setRefreshAccountIntervalMinute} placeholder="60" help="单位分钟，控制账号自动刷新频率。" />
          </Col>
          <Col xs={24} md={12} xl={6}>
            <NumberInput label="账号刷新并发" value={String(config.refresh_account_concurrency || "")} onChange={setRefreshAccountConcurrency} placeholder="20" help="同时检测账号信息和额度的线程数，最高 100。过高可能触发代理或上游限流。" />
          </Col>
          <Col xs={24} md={12} xl={6}>
            <NumberInput label="图片自动清理" value={String(config.image_retention_days || "")} onChange={setImageRetentionDays} placeholder="30" help="自动删除多少天前的本地图片。" />
          </Col>
          <Col xs={24} md={12} xl={6}>
            <NumberInput label="图片轮询超时" value={String(config.image_poll_timeout_secs || "")} onChange={setImagePollTimeoutSecs} placeholder="120" help="单位秒，等待上游图片结果的最长时间。" />
          </Col>
          <Col xs={24} md={12} xl={6}>
            <NumberInput label="单账号图片并发" value={String(config.image_account_concurrency || "")} onChange={setImageAccountConcurrency} placeholder="1" help="每个账号同时处理的图片请求数量。" />
          </Col>
          <Col xs={24} lg={12}>
            <Form.Item label="全局代理" extra="留空表示不使用代理。">
              <Space.Compact className="w-full">
                <Input
                  value={String(config.proxy || "")}
                  onChange={(event) => {
                    setProxy(event.target.value);
                    setProxyTestResult(null);
                  }}
                  placeholder="http://127.0.0.1:7890"
                />
                <Button icon={isTestingProxy ? <LoaderCircle className="size-4 animate-spin" /> : <PlugZap className="size-4" />} onClick={() => void handleTestProxy()} disabled={isTestingProxy}>
                  测试
                </Button>
              </Space.Compact>
            </Form.Item>
            {proxyTestResult ? (
              <Alert
                type={proxyTestResult.ok ? "success" : "error"}
                showIcon
                title={proxyTestResult.ok ? `代理可用：HTTP ${proxyTestResult.status}，用时 ${proxyTestResult.latency_ms} ms` : `代理不可用：${proxyTestResult.error ?? "未知错误"}（用时 ${proxyTestResult.latency_ms} ms）`}
                description={proxyTestResult.ok ? formatProxyExit(proxyTestResult) : undefined}
              />
            ) : null}
          </Col>
          <Col xs={24} lg={12}>
            <Form.Item label="图片访问地址" extra="用于生成图片结果的访问前缀地址。">
              <Input value={String(config.base_url || "")} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://example.com" />
            </Form.Item>
          </Col>
        </Row>

        <Divider />
        <SectionTitle title="账号策略" description="控制异常账号、限流账号、刷新后的恢复行为。谨慎开启自动删除，避免刷新时误删账号。" />
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={8}>
            <Card size="small" className="h-full">
              <Space direction="vertical" size={8}>
                <Switch checked={Boolean(config.auto_remove_invalid_accounts)} onChange={setAutoRemoveInvalidAccounts} />
                <Typography.Text strong>自动移除异常账号</Typography.Text>
                <Typography.Text type="secondary">刷新检测到 token 无效时会直接删除账号。一般建议关闭，只标记异常。</Typography.Text>
              </Space>
            </Card>
          </Col>
          <Col xs={24} lg={8}>
            <Card size="small" className="h-full">
              <Space direction="vertical" size={8}>
                <Switch checked={Boolean(config.auto_remove_rate_limited_accounts)} onChange={setAutoRemoveRateLimitedAccounts} />
                <Typography.Text strong>自动移除限流账号</Typography.Text>
                <Typography.Text type="secondary">账号额度为 0 时直接移除。建议关闭，等待额度恢复。</Typography.Text>
              </Space>
            </Card>
          </Col>
          <Col xs={24} lg={8}>
            <Card size="small" className="h-full">
              <Space direction="vertical" size={8}>
                <Switch checked={Boolean(config.auto_relogin_after_refresh)} onChange={setAutoReloginAfterRefresh} />
                <Typography.Text strong>刷新后自动尝试恢复异常状态</Typography.Text>
                <Typography.Text type="secondary">刷新后对包含邮箱密码的异常账号尝试重新登录。</Typography.Text>
              </Space>
            </Card>
          </Col>
        </Row>

        <Row gutter={[16, 16]} className="mt-4">
          <Col xs={24}>
            <Card size="small">
              <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                <Space>
                  <Switch checked={Boolean(config.auto_refill_enabled)} onChange={setAutoRefillEnabled} />
                  <Typography.Text strong>自动补池</Typography.Text>
                  <Tag color={config.auto_refill_enabled ? "green" : "default"}>{config.auto_refill_enabled ? "已启用" : "未启用"}</Tag>
                </Space>
                <Typography.Text type="secondary">低于阈值后自动启动注册机，邮箱、代理、线程等配置仍在注册机页面维护。</Typography.Text>
              </div>
              <Row gutter={[16, 16]}>
                <Col xs={24} md={8}>
                  <NumberInput
                    label="低于正常号比例"
                    value={String(config.auto_refill_threshold_percent || "")}
                    onChange={setAutoRefillThresholdPercent}
                    placeholder="30"
                    help="单位百分比，例如 30 表示正常号少于总号池 30% 时触发。"
                    disabled={!config.auto_refill_enabled}
                  />
                </Col>
                <Col xs={24} md={8}>
                  <NumberInput
                    label="补到正常账号数"
                    value={String(config.auto_refill_target_available || "")}
                    onChange={setAutoRefillTargetAvailable}
                    placeholder="10"
                    help="触发后注册机会使用“正常账号数达到该值”为目标。"
                    disabled={!config.auto_refill_enabled}
                  />
                </Col>
                <Col xs={24} md={8}>
                  <NumberInput
                    label="检查间隔"
                    value={String(config.auto_refill_interval_minutes || "")}
                    onChange={setAutoRefillIntervalMinutes}
                    placeholder="5"
                    help="单位分钟，服务启动后按这个间隔检查号池。"
                    disabled={!config.auto_refill_enabled}
                  />
                </Col>
              </Row>
            </Card>
          </Col>
        </Row>

        <Divider />
        <SectionTitle title="图片任务" description="控制图片结果确认、超时后继续等待和控制台日志输出。" />
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={8}>
            <Card size="small" className="h-full">
              <Space direction="vertical" size={8} className="w-full">
                <Switch checked={Boolean(config.image_settle_enabled !== false)} onChange={setImageSettleEnabled} />
                <Typography.Text strong>图片二次确认机制</Typography.Text>
                <Typography.Text type="secondary">找到图片后等待短时间再次确认，提升获取稳定性。</Typography.Text>
                <Input value={String(config.image_settle_secs || "2.0")} onChange={(event) => setImageSettleSecs(event.target.value)} placeholder="2.0" disabled={!config.image_settle_enabled} addonAfter="秒" />
              </Space>
            </Card>
          </Col>
          <Col xs={24} lg={8}>
            <NumberInput label="图片超时继续等待时间" value={String(config.image_timeout_retry_secs || "30")} onChange={setImageTimeoutRetrySecs} placeholder="30" help="单位秒，超时后点击继续等待的额外等待时间。" />
          </Col>
          <Col xs={24} lg={8}>
            <Form.Item label="控制台日志级别" extra="不选择时使用默认 info / warning / error。">
              <Checkbox.Group value={config.log_levels || []} onChange={(values) => {
                for (const level of logLevelOptions) {
                  setLogLevel(level, values.includes(level));
                }
              }}>
                <Space wrap>
                  {logLevelOptions.map((level) => (
                    <Checkbox key={level} value={level}>
                      <span className="capitalize">{level}</span>
                    </Checkbox>
                  ))}
                </Space>
              </Checkbox.Group>
            </Form.Item>
          </Col>
        </Row>

        <Divider />
        <SectionTitle title="WebDAV 图片存储" description="可选择只保存在本机、只保存到 WebDAV，或两边都保留。" />
        <Card size="small">
          <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <Space>
              <Switch checked={imageStorageEnabled} onChange={(checked) => setImageStorageField("enabled", checked)} />
              <Typography.Text strong>启用 WebDAV 图片存储</Typography.Text>
              <Tag color={imageStorageEnabled ? "blue" : "default"}>{imageStorageEnabled ? "已启用" : "仅本机"}</Tag>
            </Space>
            <Space wrap>
              <Button icon={isTestingImageStorage ? <LoaderCircle className="size-4 animate-spin" /> : <Cloud className="size-4" />} onClick={() => void testImageStorage()} disabled={isTestingImageStorage || !imageStorageEnabled}>
                测试 WebDAV
              </Button>
              <Button icon={isSyncingImageStorage ? <LoaderCircle className="size-4 animate-spin" /> : <RefreshCw className="size-4" />} onClick={() => void syncImagesToWebDAV()} disabled={isSyncingImageStorage || !imageStorageEnabled || config.image_storage?.mode === "local"}>
                全量同步
              </Button>
            </Space>
          </div>
          <Row gutter={[16, 16]}>
            <Col xs={24} md={8}>
              <Form.Item label="保存模式">
                <Select
                  value={String(config.image_storage?.mode || "local")}
                  onChange={(value) => setImageStorageField("mode", value as ImageStorageMode)}
                  disabled={!imageStorageEnabled}
                  options={[
                    { value: "local", label: "仅本机" },
                    { value: "webdav", label: "仅 WebDAV" },
                    { value: "both", label: "本机 + WebDAV" },
                  ]}
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={16}>
              <Form.Item label="WebDAV URL">
                <Input value={String(config.image_storage?.webdav_url || "")} onChange={(event) => setImageStorageField("webdav_url", event.target.value)} placeholder="https://example.com/dav" disabled={!imageStorageEnabled} />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item label="用户名">
                <Input value={String(config.image_storage?.webdav_username || "")} onChange={(event) => setImageStorageField("webdav_username", event.target.value)} disabled={!imageStorageEnabled} />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item label="密码">
                <Input.Password value={String(config.image_storage?.webdav_password || "")} onChange={(event) => setImageStorageField("webdav_password", event.target.value)} disabled={!imageStorageEnabled} />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item label="远端目录">
                <Input value={String(config.image_storage?.webdav_root_path || "")} onChange={(event) => setImageStorageField("webdav_root_path", event.target.value)} placeholder="chatgpt2api/images" disabled={!imageStorageEnabled} />
              </Form.Item>
            </Col>
            <Col xs={24}>
              <Form.Item label="公开访问前缀" extra="留空时返回本应用 /images/... 代理地址；填入后直接返回公开图片地址。">
                <Input value={String(config.image_storage?.public_base_url || "")} onChange={(event) => setImageStorageField("public_base_url", event.target.value)} placeholder="https://cdn.example.com/chatgpt2api/images" disabled={!imageStorageEnabled} />
              </Form.Item>
            </Col>
          </Row>
        </Card>

        <Divider />
        <SectionTitle title="内容安全" description="在请求进入账号池前进行全局提示词约束、敏感词拦截或 AI 审核。" />
        <Row gutter={[16, 16]}>
          <Col xs={24}>
            <Form.Item label="全局附加指令" extra="每次请求都会作为 system 消息注入。">
              <Input.TextArea value={String(config.global_system_prompt || "")} onChange={(event) => setGlobalSystemPrompt(event.target.value)} autoSize={{ minRows: 4, maxRows: 8 }} placeholder="例如：遇到违法、色情、暴力、仇恨等请求时拒绝回答。" />
            </Form.Item>
          </Col>
          <Col xs={24}>
            <Form.Item label="敏感词" extra="一行一个，命中任意敏感词会直接拒绝请求。">
              <Input.TextArea value={(config.sensitive_words || []).join("\n")} onChange={(event) => setSensitiveWordsText(event.target.value)} autoSize={{ minRows: 4, maxRows: 8 }} placeholder="一行一个，命中即拒绝" />
            </Form.Item>
          </Col>
        </Row>

        <Card size="small">
          <div className="mb-4 flex items-center justify-between gap-3">
            <Space>
              <Switch checked={aiReviewEnabled} onChange={(checked) => setAIReviewField("enabled", checked)} />
              <Typography.Text strong>启用 AI 审核</Typography.Text>
              <Tag color={aiReviewEnabled ? "green" : "default"}>{aiReviewEnabled ? "审核开启" : "未开启"}</Tag>
            </Space>
          </div>
          <Row gutter={[16, 16]}>
            <Col xs={24} md={8}>
              <Form.Item label="Base URL">
                <Input value={String(config.ai_review?.base_url || "")} onChange={(event) => setAIReviewField("base_url", event.target.value)} placeholder="https://api.openai.com" />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item label="API Key">
                <Input.Password value={String(config.ai_review?.api_key || "")} onChange={(event) => setAIReviewField("api_key", event.target.value)} placeholder="sk-..." />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item label="Model">
                <Input value={String(config.ai_review?.model || "")} onChange={(event) => setAIReviewField("model", event.target.value)} placeholder="gpt-5.4-mini" />
              </Form.Item>
            </Col>
            <Col xs={24}>
              <Form.Item label="审核提示词">
                <Input.TextArea value={String(config.ai_review?.prompt || "")} onChange={(event) => setAIReviewField("prompt", event.target.value)} autoSize={{ minRows: 3, maxRows: 6 }} placeholder="判断用户请求是否允许。只回答 ALLOW 或 REJECT。" />
              </Form.Item>
            </Col>
          </Row>
        </Card>
      </Form>
    </Card>
  );
}
