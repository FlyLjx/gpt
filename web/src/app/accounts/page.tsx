"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Button as AntButton,
  Card as AntCard,
  Checkbox as AntCheckbox,
  Col,
  Empty,
  Grid,
  Input as AntInput,
  Modal,
  Pagination as AntPagination,
  Progress as AntProgress,
  Row,
  Select as AntSelect,
  Space,
  Spin,
  Steps,
  Table as AntTable,
  Tag,
  Tooltip,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  Ban,
  CheckCircle2,
  CircleAlert,
  CircleOff,
  Copy,
  Download,
  LoaderCircle,
  LogIn,
  Pencil,
  RefreshCw,
  Search,
  Trash2,
  UserRound,
} from "lucide-react";
import { toast } from "sonner";

import {
  deleteAccounts,
  fetchAccounts,
  fetchModels,
  fetchRefreshProgress,
  fetchReLoginProgress,
  reLoginAccounts,
  refreshAccounts,
  testProxy,
  updateAccount,
  type Account,
  type AccountRefreshResponse,
  type AccountStatus,
  type Model,
  type RefreshProgressResponse,
} from "@/lib/api";
import { useAuthGuard } from "@/lib/use-auth-guard";
import { cn } from "@/lib/utils";

import { AccountImportDialog } from "./components/account-import-dialog";

const accountStatusOptions: { label: string; value: AccountStatus | "all" }[] = [
  { label: "全部状态", value: "all" },
  { label: "正常", value: "正常" },
  { label: "限流", value: "限流" },
  { label: "异常", value: "异常" },
  { label: "禁用", value: "禁用" },
];

const statusMeta: Record<
  AccountStatus,
  {
    icon: typeof CheckCircle2;
    tagColor: string;
  }
> = {
  正常: { icon: CheckCircle2, tagColor: "success" },
  限流: { icon: CircleAlert, tagColor: "warning" },
  异常: { icon: CircleOff, tagColor: "error" },
  禁用: { icon: Ban, tagColor: "default" },
};

const metricCards = [
  { key: "total", label: "账户总数", color: "text-stone-900", icon: UserRound },
  { key: "active", label: "正常账户", color: "text-emerald-600", icon: CheckCircle2 },
  { key: "limited", label: "限流账户", color: "text-orange-500", icon: CircleAlert },
  { key: "abnormal", label: "异常账户", color: "text-rose-500", icon: CircleOff },
  { key: "disabled", label: "禁用账户", color: "text-stone-500", icon: Ban },
  { key: "cooling", label: "调度冷却", color: "text-amber-600", icon: LoaderCircle },
  { key: "proxyCooling", label: "代理冷却", color: "text-sky-600", icon: RefreshCw },
  { key: "quota", label: "剩余额度", color: "text-blue-500", icon: RefreshCw },
] as const;

const accountGroupMeta = {
  plus: { label: "Plus 账号", description: "ChatGPT Plus 类型账号" },
  free: { label: "Free 账号", description: "免费类型账号" },
  other: { label: "其他账号", description: "非 Plus / Free 类型账号" },
} as const;

type AccountGroupKey = keyof typeof accountGroupMeta;

const accountGroupOrder: AccountGroupKey[] = ["plus", "free", "other"];

function isUnlimitedImageQuotaAccount(account: Account) {
  return account.type === "pro" || account.type === "prolite";
}

function imageQuotaUnknown(account: Account) {
  return Boolean(account.image_quota_unknown);
}

function formatCompact(value: number) {
  if (value >= 1000) {
    return `${(value / 1000).toFixed(1)}k`;
  }
  return String(value);
}

function formatQuota(account: Account) {
  if (isUnlimitedImageQuotaAccount(account)) {
    return "∞";
  }
  if (imageQuotaUnknown(account)) {
    return "未知";
  }
  return String(Math.max(0, account.quota));
}

function stringifyUsage(value: unknown) {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  if (typeof value === "number") {
    return formatCompact(value);
  }
  if (typeof value === "string") {
    return value;
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function usagePercent(value: unknown) {
  if (!value || typeof value !== "object") {
    return "";
  }
  const utilization = (value as { utilization?: unknown }).utilization;
  if (typeof utilization !== "number") {
    const numeric = Number(utilization);
    if (!Number.isFinite(numeric)) {
      return "";
    }
    return `${Math.round(numeric * 10) / 10}%`;
  }
  return `${Math.round(utilization * 10) / 10}%`;
}

function usagePercentValue(value: unknown) {
  if (!value || typeof value !== "object") {
    return null;
  }
  const utilization = (value as { utilization?: unknown }).utilization;
  const numeric = typeof utilization === "number" ? utilization : Number(utilization);
  if (!Number.isFinite(numeric)) {
    return null;
  }
  return Math.min(100, Math.max(0, numeric));
}

function usageResetText(value: unknown) {
  if (!value || typeof value !== "object") {
    return "";
  }
  const resetsAt = (value as { resets_at?: unknown }).resets_at;
  if (!resetsAt) {
    return "";
  }
  const date = new Date(String(resetsAt));
  if (Number.isNaN(date.getTime())) {
    return String(resetsAt);
  }
  const now = new Date();
  const sameDay = date.toDateString() === now.toDateString();
  const pad = (num: number) => String(num).padStart(2, "0");
  const time = `${pad(date.getHours())}:${pad(date.getMinutes())}`;
  if (sameDay) {
    return `${time} 重置`;
  }
  return `${pad(date.getMonth() + 1)}/${pad(date.getDate())} ${time}`;
}

function formatUsage(value: unknown) {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  if (typeof value !== "object") {
    return stringifyUsage(value);
  }

  const usage = value as {
    five_hour?: unknown;
    seven_day?: unknown;
    image_gen_used?: unknown;
  };
  const parts: string[] = [];
  const fiveHour = usagePercent(usage.five_hour);
  const sevenDay = usagePercent(usage.seven_day);
  if (fiveHour) {
    parts.push(`5h ${fiveHour}`);
  }
  if (sevenDay) {
    parts.push(`7d ${sevenDay}`);
  }
  if (usage.image_gen_used !== undefined && usage.image_gen_used !== null) {
    parts.push(`图 ${formatCompact(Number(usage.image_gen_used) || 0)}`);
  }
  return parts.length ? parts.join(" / ") : stringifyUsage(value);
}

function usageBarColor(value: number) {
  if (value >= 85) {
    return "#f5222d";
  }
  if (value >= 60) {
    return "#fa8c16";
  }
  return "#52c41a";
}

function UsageProgressCell({ usage }: { usage: unknown }) {
  const usageObject = usage && typeof usage === "object" ? usage as {
    five_hour?: unknown;
    seven_day?: unknown;
    image_gen_used?: unknown;
  } : null;
  const items = usageObject ? [
    { label: "5h", value: usagePercentValue(usageObject.five_hour), resetText: usageResetText(usageObject.five_hour) },
    { label: "7d", value: usagePercentValue(usageObject.seven_day), resetText: usageResetText(usageObject.seven_day) },
  ].filter((item): item is { label: string; value: number; resetText: string } => item.value !== null) : [];

  if (items.length === 0) {
    return (
      <span className="inline-flex rounded-md bg-stone-100 px-2 py-1 font-mono text-[11px] font-medium text-stone-700">
        {formatUsage(usage)}
      </span>
    );
  }

  return (
    <div className="w-[150px] space-y-1" title={stringifyUsage(usage)}>
      {items.map((item) => (
        <div key={item.label} className="leading-none">
          <div className="mb-0.5 flex items-center justify-between gap-1">
            <Tag color="blue" className="m-0 rounded px-1 py-0 text-[10px] leading-4">{item.label}</Tag>
            <span className="font-mono text-[10px] font-semibold text-slate-700">{item.value}%</span>
            {item.resetText ? (
              <span className="ml-auto truncate text-[10px] font-medium text-slate-400">{item.resetText}</span>
            ) : null}
          </div>
          <AntProgress
            percent={item.value}
            showInfo={false}
            size={[150, 4]}
            strokeColor={usageBarColor(item.value)}
            railColor="#eef2f7"
          />
        </div>
      ))}
    </div>
  );
}

function formatRestoreAt(value?: string | null) {
  if (!value) {
    return { absolute: "—", relative: "" };
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return { absolute: value, relative: "" };
  }

  const diffMs = Math.max(0, date.getTime() - Date.now());
  const totalHours = Math.ceil(diffMs / (1000 * 60 * 60));
  const days = Math.floor(totalHours / 24);
  const hours = totalHours % 24;
  const relative = diffMs > 0 ? `剩余 ${days}d ${hours}h` : "已到恢复时间";

  const pad = (num: number) => String(num).padStart(2, "0");
  const absolute = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;

  return { absolute, relative };
}

function formatShortRelative(value?: string | null) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  const diffMs = date.getTime() - Date.now();
  const absMs = Math.abs(diffMs);
  const minutes = Math.ceil(absMs / (1000 * 60));
  if (minutes < 60) {
    return diffMs >= 0 ? `剩 ${minutes}m` : `${minutes}m前`;
  }
  const hours = Math.ceil(minutes / 60);
  if (hours < 24) {
    return diffMs >= 0 ? `剩 ${hours}h` : `${hours}h前`;
  }
  const days = Math.ceil(hours / 24);
  return diffMs >= 0 ? `剩 ${days}d` : `${days}d前`;
}

function errorTypeLabel(value?: string | null) {
  const key = String(value || "").trim();
  if (!key) {
    return "";
  }
  const labels: Record<string, string> = {
    cloudflare: "Cloudflare",
    rate_limited: "限流",
    token_invalid: "Token 无效",
    timeout: "超时",
    poll_timeout: "轮询超时",
    network: "网络",
    upstream: "上游",
    no_image: "无图",
    generic: "通用",
    content_policy: "内容策略",
  };
  return labels[key] || key;
}

function formatQuotaSummary(accounts: Account[]) {
  const availableAccounts = accounts.filter((account) => account.status === "正常");
  if (availableAccounts.some(isUnlimitedImageQuotaAccount)) {
    return "∞";
  }
  if (availableAccounts.some(imageQuotaUnknown)) {
    return "未知";
  }
  return formatCompact(availableAccounts.reduce((sum, account) => sum + Math.max(0, account.quota), 0));
}

function maskToken(token?: string) {
  if (!token) return "—";
  if (token.length <= 18) return token;
  return `${token.slice(0, 16)}...${token.slice(-8)}`;
}

function downloadTokens(accounts: Account[]) {
  const content = `${accounts.map((account) => account.access_token).join("\n")}\n`;
  const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `accounts-${Date.now()}.txt`;
  link.click();
  URL.revokeObjectURL(url);
}

function displayAccountType(account: Account) {
  return account.type || "Free";
}

function getAccountGroupKey(account: Account): AccountGroupKey {
  const type = String(account.type || "").trim().toLowerCase();
  if (type === "plus") {
    return "plus";
  }
  if (!type || type === "free") {
    return "free";
  }
  return "other";
}

function compareAccountsByGroup(a: Account, b: Account) {
  const groupDiff = accountGroupOrder.indexOf(getAccountGroupKey(a)) - accountGroupOrder.indexOf(getAccountGroupKey(b));
  if (groupDiff !== 0) {
    return groupDiff;
  }

  const typeDiff = displayAccountType(a).localeCompare(displayAccountType(b), "zh-CN");
  if (typeDiff !== 0) {
    return typeDiff;
  }

  return (a.email || a.access_token).localeCompare(b.email || b.access_token, "zh-CN");
}

function displayAccountSource(account: Account) {
  const source = String(account.source_type || "").trim().toLowerCase();
  if (!source) {
    return "web";
  }
  if (source === "web") {
    return "web";
  }
  return source;
}

function AccountsPageContent() {
  const didLoadRef = useRef(false);
  const screens = Grid.useBreakpoint();
  const isCompactTable = !screens.md;
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [availableModels, setAvailableModels] = useState<Model[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState<AccountStatus | "all">("all");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState("10");
  const [editingAccount, setEditingAccount] = useState<Account | null>(null);
  const [editStatus, setEditStatus] = useState<AccountStatus>("正常");
  const [editProxy, setEditProxy] = useState("");
  const [isTestingProxy, setIsTestingProxy] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingModels, setIsLoadingModels] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [refreshingTokens, setRefreshingTokens] = useState<Set<string>>(new Set());
  const [isDeleting, setIsDeleting] = useState(false);
  const [isUpdating, setIsUpdating] = useState(false);
  const [isRelogining, setIsRelogining] = useState(false);
  const [progress, setProgress] = useState<{
    visible: boolean;
    current: number;
    total: number;
    message: string;
    email: string;
  }>({
    visible: false,
    current: 0,
    total: 0,
    message: "",
    email: "",
  });
  const progressRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [refreshSummary, setRefreshSummary] = useState<Record<string, number | string> | null>(null);
  const [progressResults, setProgressResults] = useState<NonNullable<RefreshProgressResponse["results"]>>([]);

  const resetProgress = () => {
    if (progressRef.current) {
      clearInterval(progressRef.current);
      progressRef.current = null;
    }
    setProgress({ visible: false, current: 0, total: 0, message: "", email: "" });
    setProgressResults([]);
  };

  const animateProgressTo = (target: number) => {
    setProgress((prev) => {
      const safeTarget = Math.min(prev.total || target, Math.max(prev.current, target));
      if (safeTarget <= prev.current) {
        return prev;
      }
      if (progressRef.current) {
        clearInterval(progressRef.current);
      }
      progressRef.current = setInterval(() => {
        setProgress((current) => {
          const nextValue = Math.min(safeTarget, current.current + 1);
          if (nextValue >= safeTarget && progressRef.current) {
            clearInterval(progressRef.current);
            progressRef.current = null;
          }
          return { ...current, current: nextValue };
        });
      }, 80);
      return prev;
    });
  };

  const loadAccounts = async (silent = false) => {
    if (!silent) {
      setIsLoading(true);
    }
    try {
      const data = await fetchAccounts();
      setAccounts(data.items);
      setSelectedIds((prev) => prev.filter((id) => data.items.some((item) => item.access_token === id)));
    } catch (error) {
      const message = error instanceof Error ? error.message : "加载账户失败";
      toast.error(message);
    } finally {
      if (!silent) {
        setIsLoading(false);
      }
    }
  };

  const loadModels = async () => {
    setIsLoadingModels(true);
    try {
      const data = await fetchModels();
      setAvailableModels(Array.isArray(data.data) ? data.data : []);
    } catch (error) {
      const message = error instanceof Error ? error.message : "加载模型列表失败";
      toast.error(message);
    } finally {
      setIsLoadingModels(false);
    }
  };

  useEffect(() => {
    if (didLoadRef.current) {
      return;
    }
    didLoadRef.current = true;
    void loadAccounts();
    void loadModels();

    // 清理进度条定时器
    return () => {
      if (progressRef.current) clearInterval(progressRef.current);
    };
  }, []);

  const filteredAccounts = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return accounts.filter((account) => {
      const searchMatched =
        normalizedQuery.length === 0 || (account.email ?? "").toLowerCase().includes(normalizedQuery);
      const typeMatched = typeFilter === "all" || displayAccountType(account) === typeFilter;
      const statusMatched = statusFilter === "all" || account.status === statusFilter;
      return searchMatched && typeMatched && statusMatched;
    });
  }, [accounts, query, statusFilter, typeFilter]);

  const groupedAccounts = useMemo(() => {
    return [...filteredAccounts].sort(compareAccountsByGroup);
  }, [filteredAccounts]);

  const pageCount = Math.max(1, Math.ceil(groupedAccounts.length / Number(pageSize)));
  const safePage = Math.min(page, pageCount);
  const startIndex = (safePage - 1) * Number(pageSize);
  const currentRows = groupedAccounts.slice(startIndex, startIndex + Number(pageSize));
  const allCurrentSelected =
    currentRows.length > 0 && currentRows.every((row) => selectedIds.includes(row.access_token));

  const summary = useMemo(() => {
    const total = accounts.length;
    const active = accounts.filter((item) => item.status === "正常").length;
    const limited = accounts.filter((item) => item.status === "限流").length;
    const abnormal = accounts.filter((item) => item.status === "异常").length;
    const disabled = accounts.filter((item) => item.status === "禁用").length;
    const cooling = accounts.filter((item) => item.cooldown_active || item.proxy_cooldown_active).length;
    const proxyCooling = accounts.filter((item) => item.proxy_cooldown_active).length;
    const quota = formatQuotaSummary(accounts);

    return { total, active, limited, abnormal, disabled, cooling, proxyCooling, quota };
  }, [accounts]);

  const accountTypeOptions = useMemo(
    () => [
      { label: "全部类型", value: "all" },
      ...Array.from(new Set(accounts.map(displayAccountType))).map((type) => ({ label: type, value: type })),
    ],
    [accounts],
  );

  const selectedTokens = useMemo(() => {
    const selectedSet = new Set(selectedIds);
    return accounts.filter((item) => selectedSet.has(item.access_token)).map((item) => item.access_token);
  }, [accounts, selectedIds]);

  const abnormalTokens = useMemo(() => {
    return accounts.filter((item) => item.status === "异常").map((item) => item.access_token);
  }, [accounts]);

  const handleDeleteTokens = async (tokens: string[]) => {
    if (tokens.length === 0) {
      toast.error("请先选择要删除的账户");
      return;
    }

    setIsDeleting(true);
    try {
      const data = await deleteAccounts(tokens);
      setAccounts(data.items);
      setSelectedIds((prev) => prev.filter((id) => data.items.some((item) => item.access_token === id)));
      toast.success(`删除 ${data.removed ?? 0} 个账户`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "删除账户失败";
      toast.error(message);
    } finally {
      setIsDeleting(false);
    }
  };

  const handleRefreshAccounts = async (accessTokens: string[]) => {
    if (accessTokens.length === 0) {
      toast.error("没有需要刷新的账户");
      return;
    }

    if (accessTokens.length === 1) {
      setRefreshingTokens((prev) => new Set([...prev, accessTokens[0]]));
      setProgress({
        visible: true,
        current: 0,
        total: 1,
        message: "正在刷新账号信息...",
        email: accounts.find((item) => item.access_token === accessTokens[0])?.email || "",
      });
      try {
        const { progress_id } = await refreshAccounts(accessTokens);
        // 单账号：轮询等待完成
        await pollRefreshProgress(progress_id, (progress) => {
          setProgress((prev) => ({
            ...prev,
            current: progress.done ? 1 : Math.min(1, progress.processed || 0),
            message: progress.done ? "刷新完成" : "正在刷新账号信息...",
          }));
          if (progress.done && progress.result) {
            setAccounts(progress.result.items);
            setSelectedIds((prev) => prev.filter((id) => progress.result!.items.some((item) => item.access_token === id)));
          }
        });
        setTimeout(resetProgress, 800);
      } catch (error) {
        resetProgress();
        const message = error instanceof Error ? error.message : "刷新账户失败";
        toast.error(message);
      } finally {
        setRefreshingTokens((prev) => {
          const next = new Set(prev);
          next.delete(accessTokens[0]);
          return next;
        });
      }
      return;
    }

    setIsRefreshing(true);

    // 计算非选中账号的基数（统计卡片联动用）
    const selectedTokenSet = new Set(accessTokens);
    const baseAccountsList = accounts.filter((a) => !selectedTokenSet.has(a.access_token));
    const baseActive = baseAccountsList.filter((a) => a.status === "正常").length;
    const baseLimited = baseAccountsList.filter((a) => a.status === "限流").length;
    const baseAbnormal = baseAccountsList.filter((a) => a.status === "异常").length;
    const baseDisabled = baseAccountsList.filter((a) => a.status === "禁用").length;
    const baseNormalAccounts = baseAccountsList.filter((a) => a.status === "正常");
    const baseHasUnlimited = baseNormalAccounts.some(isUnlimitedImageQuotaAccount);
    const baseHasUnknown = baseNormalAccounts.some(imageQuotaUnknown);
    const baseQuotaNum = baseNormalAccounts.reduce((s, a) => s + Math.max(0, a.quota), 0);

    // 显示进度条（只显示当前任务，不含分类统计）
    const total = accessTokens.length;
    setProgress({
      visible: true,
      current: 0,
      total,
      message: "正在刷新账号信息...",
      email: "",
    });
    setProgressResults([]);

    try {
      const { progress_id } = await refreshAccounts(accessTokens);

      // 轮询进度到完成
      const data = await new Promise<AccountRefreshResponse>((resolve, reject) => {
        const pollTimer = setInterval(async () => {
          try {
            const p = await fetchRefreshProgress(progress_id);
            if (p.done) {
              clearInterval(pollTimer);
              if (p.error) {
                reject(new Error(p.error));
                return;
              }
              if (!p.result) {
                reject(new Error("刷新结果为空"));
                return;
              }
              // 更新最终进度显示
              if (progressRef.current) {
                clearInterval(progressRef.current);
                progressRef.current = null;
              }
              setProgress((prev) => ({
                ...prev,
                current: prev.total,
                message: "刷新完成",
                email: "",
              }));
              setProgressResults(p.results ?? []);
              // 清除联动统计
              setRefreshSummary(null);
              resolve(p.result);
            } else {
              // 实时更新进度
              setProgressResults(p.results ?? []);
              const latest = p.results?.[p.results.length - 1];
              setProgress((prev) => ({
                ...prev,
                message: latest ? `已处理 ${p.processed}/${p.total}` : "正在刷新账号信息...",
                email: latest?.email || latest?.token || "",
              }));
              animateProgressTo(p.processed);
              // 实时更新统计卡片：基数 + 已刷新的累加结果
              const runningActive = baseActive + ((p.status_counts?.["正常"]) ?? 0);
              const runningLimited = baseLimited + ((p.status_counts?.["限流"]) ?? 0);
              const runningAbnormal = baseAbnormal + ((p.status_counts?.["异常"]) ?? 0);
              const runningDisabled = baseDisabled + ((p.status_counts?.["禁用"]) ?? 0);
              let runningQuota: string | number;
              if (baseHasUnlimited) {
                runningQuota = "∞";
              } else if (baseHasUnknown) {
                runningQuota = "未知";
              } else {
                runningQuota = formatCompact(baseQuotaNum + (p.total_quota ?? 0));
              }
              setRefreshSummary({
                total: accounts.length,
                active: runningActive,
                limited: runningLimited,
                abnormal: runningAbnormal,
                disabled: runningDisabled,
                quota: runningQuota,
              });
            }
          } catch (err) {
            clearInterval(pollTimer);
            reject(err);
          }
        }, 300);
      });

      // 刷新完成，更新数据
      setAccounts(data.items);
      setSelectedIds((prev) => prev.filter((id) => data.items.some((item) => item.access_token === id)));

      const relogined = data.relogined ?? 0;

      // 显示重新登录进度
      if (relogined > 0) {
        setProgress({
          visible: true,
          current: 0,
          total: relogined,
          message: `正在尝试对 ${relogined} 个账号进行移除异常状态`,
          email: "",
        });
        // 模拟重新登录进度
        let reCount = 0;
        await new Promise<void>((resolve) => {
          const timer = setInterval(() => {
            reCount += 1;
            if (reCount >= relogined) {
              clearInterval(timer);
              setProgress({
                visible: true,
                current: relogined,
                total: relogined,
                message: "移除异常状态完成",
                email: "",
              });
              setTimeout(resetProgress, 800);
              resolve();
            } else {
              setProgress((prev) => ({ ...prev, current: reCount }));
            }
          }, 150);
          setTimeout(resolve, 2000);
        });
      } else {
        setProgress({
          visible: true,
          current: total,
          total,
          message: "刷新完成",
          email: "",
        });
        setTimeout(resetProgress, 800);
      }

      if ((data.errors ?? []).length > 0) {
        const firstError = data.errors?.[0]?.error;
        toast.error(
          `刷新成功 ${data.refreshed} 个，失败 ${(data.errors ?? []).length} 个${firstError ? `，首个错误：${firstError}` : ""}`,
        );
      } else {
        toast.success(`刷新成功 ${data.refreshed} 个账户${relogined > 0 ? `，已触发 ${relogined} 个账号重新登录` : ""}`);
      }
    } catch (error) {
      resetProgress();
      setRefreshSummary(null);
      const message = error instanceof Error ? error.message : "刷新账户失败";
      toast.error(message);
    } finally {
      setIsRefreshing(false);
    }
  };

  const pollRefreshProgress = async (
    progressId: string,
    onUpdate: (p: RefreshProgressResponse) => void,
  ): Promise<void> => {
    return new Promise<void>((resolve, reject) => {
      const timer = setInterval(async () => {
        try {
          const p = await fetchRefreshProgress(progressId);
          onUpdate(p);
          if (p.done) {
            clearInterval(timer);
            if (p.error) {
              reject(new Error(p.error));
            } else {
              resolve();
            }
          }
        } catch (err) {
          clearInterval(timer);
          reject(err);
        }
      }, 500);
    });
  };

  const handleReLogin = async (accessTokens: string[]) => {
    if (accessTokens.length === 0) {
      toast.error("请先选择要恢复的账户");
      return;
    }

    // 只处理异常账号，过滤非异常账号
    const abnormalTokens = accessTokens.filter((token) => {
      const account = accounts.find((a) => a.access_token === token);
      return account?.status === "异常";
    });

    if (abnormalTokens.length === 0) {
      toast.error("选中账号中没有异常账号");
      return;
    }

    if (abnormalTokens.length < accessTokens.length) {
      toast.info(`已过滤 ${accessTokens.length - abnormalTokens.length} 个非异常账号`);
    }

    setIsRelogining(true);

    // 计算非选中账号的基数（统计卡片联动用）
    const selectedTokenSet = new Set(abnormalTokens);
    const baseAccountsList = accounts.filter((a) => !selectedTokenSet.has(a.access_token));
    const baseActive = baseAccountsList.filter((a) => a.status === "正常").length;
    const baseLimited = baseAccountsList.filter((a) => a.status === "限流").length;
    const baseAbnormal = baseAccountsList.filter((a) => a.status === "异常").length;
    const baseDisabled = baseAccountsList.filter((a) => a.status === "禁用").length;

    // 显示进度条（真实进度）
    const total = abnormalTokens.length;
    setProgress({ visible: true, current: 0, total, message: "正在尝试恢复异常账号...", email: "" });

    try {
      const { progress_id } = await reLoginAccounts(abnormalTokens);

      // 轮询进度到完成
      await new Promise<void>((resolve, reject) => {
        const pollTimer = setInterval(async () => {
          try {
            const p = await fetchReLoginProgress(progress_id);
            if (p.done) {
              clearInterval(pollTimer);
              if (p.error) {
                reject(new Error(p.error));
                return;
              }
              setProgress((prev) => ({ ...prev, current: prev.total, message: "恢复流程已完成" }));
              setRefreshSummary(null);
              resolve();
            } else {
              // 实时更新进度
              const results = p.results ?? [];
              // 找到最新一条有错误的结果
              const lastErrorResult = [...results].reverse().find((r) => r.error);
              const emailHint = lastErrorResult
                ? `失败: ${lastErrorResult.token} ${lastErrorResult.error ?? ""}`
                : `已处理 ${p.processed}/${p.total}`;
              setProgress((prev) => ({
                ...prev,
                current: p.processed,
                email: emailHint,
                message: "正在尝试恢复异常账号...",
              }));

              // 实时更新统计卡片：基数 + 已处理的恢复结果
              let runningActive = baseActive;
              let runningAbnormal = baseAbnormal;
              let runningDisabled = baseDisabled;
              for (const r of results) {
                if (r.status === "成功") {
                  runningActive += 1;
                  runningAbnormal -= 1;
                } else if (r.status === "禁用") {
                  runningDisabled += 1;
                  runningAbnormal -= 1;
                }
                // "异常"或"跳过"：保持异常状态不变
              }
              setRefreshSummary({
                total: accounts.length,
                active: runningActive,
                limited: baseLimited,
                abnormal: runningAbnormal,
                disabled: runningDisabled,
                quota: summary.quota,
              });
            }
          } catch (err) {
            clearInterval(pollTimer);
            reject(err);
          }
        }, 300);
      });

      // 等待后台线程完成，再拉取最新数据
      await new Promise<void>((resolve) => setTimeout(resolve, 500));
      try {
        const freshData = await fetchAccounts();
        setAccounts(freshData.items);
        setSelectedIds((prev) => prev.filter((id) => freshData.items.some((item) => item.access_token === id)));
      } catch { /* 静默失败 */ }

      setProgress({
        visible: true,
        current: total,
        total,
        message: "恢复完成",
        email: "",
      });
      setTimeout(resetProgress, 800);

      toast.success(`恢复流程已全部完成`);
    } catch (error) {
      resetProgress();
      setRefreshSummary(null);
      const message = error instanceof Error ? error.message : "重新登录失败";
      toast.error(message);
    } finally {
      setIsRelogining(false);
    }
  };

  const openEditDialog = (account: Account) => {
    setEditingAccount(account);
    setEditStatus(account.status);
    setEditProxy(account.proxy ?? "");
  };

  const handleTestAccountProxy = async () => {
    const candidate = editProxy.trim();
    if (!candidate) {
      toast.error("请先填写代理地址");
      return;
    }
    setIsTestingProxy(true);
    try {
      const data = await testProxy(candidate);
      data.result.ok
        ? toast.success(`代理可用（${data.result.latency_ms} ms，HTTP ${data.result.status}）`)
        : toast.error(`代理不可用：${data.result.error ?? "未知错误"}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "测试代理失败");
    } finally {
      setIsTestingProxy(false);
    }
  };

  const handleUpdateAccount = async () => {
    if (!editingAccount) {
      return;
    }

    setIsUpdating(true);
    try {
      const data = await updateAccount(editingAccount.access_token, {
        status: editStatus,
        proxy: editProxy.trim(),
      });
      setAccounts(data.items);
      setSelectedIds((prev) => prev.filter((id) => data.items.some((item) => item.access_token === id)));
      setEditingAccount(null);
      toast.success("账号信息已更新");
    } catch (error) {
      const message = error instanceof Error ? error.message : "更新账号失败";
      toast.error(message);
    } finally {
      setIsUpdating(false);
    }
  };

  const toggleSelectAll = (checked: boolean) => {
    if (checked) {
      setSelectedIds((prev) => Array.from(new Set([...prev, ...currentRows.map((item) => item.access_token)])));
      return;
    }
    setSelectedIds((prev) => prev.filter((id) => !currentRows.some((row) => row.access_token === id)));
  };

  const accountColumns: ColumnsType<Account> = [
    {
      title: (
        <div className="flex items-center justify-center">
          <AntCheckbox
            checked={allCurrentSelected}
            indeterminate={currentRows.some((row) => selectedIds.includes(row.access_token)) && !allCurrentSelected}
            onChange={(event) => toggleSelectAll(event.target.checked)}
          />
        </div>
      ),
      dataIndex: "access_token",
      width: 56,
      align: "center",
      fixed: isCompactTable ? undefined : "left",
      render: (_value, account) => (
        <div className="flex items-center justify-center">
          <AntCheckbox
            checked={selectedIds.includes(account.access_token)}
            onChange={(event) => {
              setSelectedIds((prev) =>
                event.target.checked
                  ? Array.from(new Set([...prev, account.access_token]))
                  : prev.filter((item) => item !== account.access_token),
              );
            }}
          />
        </div>
      ),
    },
    {
      title: "Token",
      dataIndex: "access_token",
      width: isCompactTable ? 210 : 230,
      fixed: isCompactTable ? undefined : "left",
      render: (token: string) => (
        <Space size={6}>
          <span className="font-mono text-xs font-medium text-slate-700">{maskToken(token)}</span>
          <AntButton
            type="text"
            size="small"
            icon={<Copy className="size-3.5" />}
            onClick={() => {
              void navigator.clipboard.writeText(token);
              toast.success("token 已复制");
            }}
          />
        </Space>
      ),
    },
    {
      title: "分组",
      key: "group",
      width: 112,
      render: (_value, account) => {
        const groupKey = getAccountGroupKey(account);
        const color = groupKey === "plus" ? "gold" : groupKey === "free" ? "blue" : "default";
        return <Tag color={color}>{accountGroupMeta[groupKey].label}</Tag>;
      },
    },
    {
      title: "类型",
      key: "type",
      width: 96,
      render: (_value, account) => <Tag>{displayAccountType(account)}</Tag>,
    },
    {
      title: "来源",
      key: "source",
      width: 90,
      render: (_value, account) => <Tag color={displayAccountSource(account) === "codex" ? "purple" : "default"}>{displayAccountSource(account)}</Tag>,
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 92,
      render: (status: AccountStatus) => {
        const StatusIcon = statusMeta[status]?.icon ?? CircleAlert;
        const statusClass =
          status === "正常"
            ? "bg-[#f6ffed] text-[#52c41a] ring-[#b7eb8f]"
            : status === "限流"
              ? "bg-amber-50 text-amber-700 ring-amber-200"
              : status === "异常"
                ? "bg-rose-50 text-rose-700 ring-rose-200"
                : "bg-slate-100 text-slate-600 ring-slate-200";
        return (
          <span className={cn("inline-flex h-7 min-w-[62px] items-center justify-center gap-1 rounded-md px-2 text-xs font-medium leading-none ring-1 whitespace-nowrap", statusClass)}>
            <StatusIcon className="size-3.5 shrink-0" />
            {status}
          </span>
        );
      },
    },
    {
      title: "账号信息",
      dataIndex: "email",
      width: 220,
      render: (email?: string | null) => <span className="text-xs text-slate-500">{email ?? "—"}</span>,
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      width: 132,
      render: (raw: unknown) => {
        if (!raw) return "—";
        try {
          const date = new Date(String(raw) + "Z");
          if (Number.isNaN(date.getTime())) return String(raw).slice(0, 10);
          return date.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
        } catch {
          return String(raw).slice(0, 10);
        }
      },
    },
    {
      title: "额度",
      key: "quota",
      width: 88,
      render: (_value, account) => <Tag color="blue">{formatQuota(account)}</Tag>,
    },
    {
      title: "Usage",
      dataIndex: "usage",
      width: 178,
      render: (usage: unknown) => (
        <Tooltip title={stringifyUsage(usage)} placement="topLeft">
          <div>
            <UsageProgressCell usage={usage} />
          </div>
        </Tooltip>
      ),
    },
    {
      title: "调度",
      key: "dispatch",
      width: 176,
      render: (_value, account) => {
        const score = typeof account.dispatch_score === "number" ? account.dispatch_score.toFixed(1) : "—";
        const cooldown = account.cooldown_active ? formatShortRelative(account.cooldown_until) : "";
        const recentRate = typeof account.recent_success_rate === "number" ? `${account.recent_success_rate}%` : "—";
        const error = errorTypeLabel(account.last_error_type);
        return (
          <Tooltip
            title={`最近成功率 ${recentRate}${account.recent_total ? ` (${account.recent_success || 0}/${account.recent_total})` : ""}${error ? `，最近错误 ${error}` : ""}`}
            placement="topLeft"
          >
            <div className="space-y-1 text-xs">
              <div className="flex items-center gap-1">
                <Tag color={account.cooldown_active ? "warning" : "green"} className="m-0">
                  {account.cooldown_active ? "冷却" : "可调度"}
                </Tag>
                <span className="font-mono text-slate-600">{score}</span>
                {cooldown ? <span className="text-amber-600">{cooldown}</span> : null}
              </div>
              <div className="truncate text-slate-500">
                连败 {account.consecutive_failures || 0}
                {error ? ` · ${error}` : ""}
              </div>
            </div>
          </Tooltip>
        );
      },
    },
    {
      title: "代理",
      key: "proxy",
      width: 150,
      render: (_value, account) => {
        const proxy = String(account.proxy || "").trim();
        if (!proxy) {
          return <span className="text-xs text-slate-400">—</span>;
        }
        const stats = account.proxy_stats || {};
        const success = Number(stats.success || 0);
        const fail = Number(stats.fail || 0);
        const error = errorTypeLabel(stats.last_error_type);
        return (
          <Tooltip title={`${proxy}${error ? `，最近错误 ${error}` : ""}`} placement="topLeft">
            <div className="space-y-1 text-xs">
              <Tag color={account.proxy_cooldown_active ? "warning" : "blue"} className="m-0 max-w-[128px] truncate">
                {account.proxy_cooldown_active ? "代理冷却" : "代理"}
              </Tag>
              <div className="font-mono text-slate-500">
                {success}/{fail}
                {account.proxy_cooldown_active ? ` · ${formatShortRelative(stats.cooldown_until)}` : ""}
              </div>
            </div>
          </Tooltip>
        );
      },
    },
    {
      title: "恢复时间",
      dataIndex: "restore_at",
      width: 170,
      render: (value?: string | null) => {
        const restore = formatRestoreAt(value);
        return (
          <div className="space-y-0.5 text-xs text-slate-500">
            {restore.relative ? <div className="font-medium text-slate-700">{restore.relative}</div> : null}
            <div>{restore.absolute}</div>
          </div>
        );
      },
    },
    {
      title: "成功",
      dataIndex: "success",
      width: 76,
    },
    {
      title: "失败",
      dataIndex: "fail",
      width: 76,
    },
    {
      title: "操作",
      key: "actions",
      width: 132,
      fixed: isCompactTable ? undefined : "right",
      render: (_value, account) => (
        <Space size={2}>
          <AntButton
            type="text"
            size="small"
            icon={<Pencil className="size-4" />}
            onClick={() => openEditDialog(account)}
            disabled={isUpdating}
          />
          <AntButton
            type="text"
            size="small"
            icon={<RefreshCw className={cn("size-4", (isRefreshing || refreshingTokens.has(account.access_token)) ? "animate-spin" : "")} />}
            onClick={() => void handleRefreshAccounts([account.access_token])}
            disabled={isRefreshing || refreshingTokens.has(account.access_token)}
          />
          <AntButton
            danger
            type="text"
            size="small"
            icon={<Trash2 className="size-4" />}
            onClick={() => void handleDeleteTokens([account.access_token])}
            disabled={isDeleting}
          />
        </Space>
      ),
    },
  ];

  return (
    <div className="space-y-5">
      <section className="rounded-lg bg-white p-5 shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="space-y-1">
            <div className="text-xs font-semibold tracking-[0.18em] text-slate-400 uppercase">
              Account Pool
            </div>
            <h1 className="text-2xl font-semibold tracking-tight text-slate-950">号池管理</h1>
            <p className="text-sm text-slate-500">管理账号状态、额度、Codex 使用率和批量刷新任务。</p>
          </div>

          <Space wrap>
            <AntButton
              icon={<RefreshCw className={cn("size-4", isLoading ? "animate-spin" : "")} />}
              onClick={() => void loadAccounts()}
              disabled={isLoading || isRefreshing || isDeleting}
            >
              刷新
            </AntButton>
            <AntButton
              type="primary"
              icon={<RefreshCw className={cn("size-4", isRefreshing ? "animate-spin" : "")} />}
              onClick={() => void handleRefreshAccounts(accounts.map((item) => item.access_token))}
              disabled={isLoading || isRefreshing || isDeleting || accounts.length === 0}
            >
              一键刷新所有账号信息和额度
            </AntButton>
            <AccountImportDialog
              disabled={isLoading || isRefreshing || isDeleting}
              onImported={(items) => {
                setAccounts(items);
                setSelectedIds([]);
                setPage(1);
              }}
            />
            <AntButton
              icon={<Download className="size-4" />}
              onClick={() => downloadTokens(accounts)}
              disabled={accounts.length === 0}
            >
              导出全部 Token
            </AntButton>
          </Space>
        </div>
      </section>

      {/* 进度条 */}
      {progress.visible && (
        <AntCard className="!mb-5">
          <div className="space-y-4">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-4 text-sm">
                  <span className="truncate text-slate-600">
                    {progress.message}
                    {progress.email ? <span className="ml-1 font-medium text-slate-800">{progress.email}</span> : null}
                  </span>
                  <span className="shrink-0 font-medium text-slate-700">
                    {progress.current}/{progress.total}
                  </span>
                </div>
                <AntProgress
                  className="mt-2"
                  percent={progress.total > 0 ? Math.round((progress.current / progress.total) * 100) : 0}
                  strokeColor="#1677ff"
                />
              </div>
              <Steps
                className="lg:max-w-md"
                size="small"
                current={progress.total > 0 && progress.current >= progress.total ? 2 : progress.current > 0 ? 1 : 0}
                items={[
                  { title: "启动刷新" },
                  { title: "实时处理" },
                  { title: "完成同步" },
                ]}
              />
            </div>
            {progressResults.length > 0 ? (
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {progressResults.slice(-6).reverse().map((item, index) => (
                  <div key={`${item.token}-${index}`} className="flex items-center justify-between gap-3 rounded-lg border border-slate-100 bg-slate-50 px-3 py-2 text-xs">
                    <span className="min-w-0 truncate text-slate-600">{item.email || item.token}</span>
                    <Tag color={item.error ? "error" : statusMeta[(item.status as AccountStatus) || "正常"]?.tagColor || "default"} className="m-0 shrink-0">
                      {item.error ? "失败" : item.status}
                    </Tag>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        </AntCard>
      )}

      <Modal
        title="编辑账户"
        open={Boolean(editingAccount)}
        onCancel={() => setEditingAccount(null)}
        footer={[
          <AntButton key="cancel" onClick={() => setEditingAccount(null)} disabled={isUpdating}>
            取消
          </AntButton>,
          <AntButton key="submit" type="primary" loading={isUpdating} onClick={() => void handleUpdateAccount()}>
            保存修改
          </AntButton>,
        ]}
      >
        <div className="pt-2">
          <p className="mb-4 text-sm text-slate-500">手动修改账号状态和专属代理。</p>
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-700">状态</label>
              <AntSelect
                value={editStatus}
                onChange={(value) => setEditStatus(value as AccountStatus)}
                className="w-full"
                options={accountStatusOptions
                  .filter((option) => option.value !== "all")
                  .map((option) => ({ label: option.label, value: option.value }))}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-700">账号代理</label>
              <div className="flex flex-col gap-2 sm:flex-row">
                <AntInput
                  value={editProxy}
                  onChange={(event) => setEditProxy(event.target.value)}
                  placeholder="留空走全局代理，例如 http://127.0.0.1:7890"
                />
                <AntButton
                  className="sm:w-24"
                  onClick={() => void handleTestAccountProxy()}
                  loading={isTestingProxy}
                >
                  测试
                </AntButton>
              </div>
            </div>
          </div>
        </div>
      </Modal>

      <section className="space-y-5">
        <Row gutter={[18, 18]}>
          {metricCards.map((item) => {
            const Icon = item.icon;
            const value = (refreshSummary ?? summary)[item.key];
            return (
              <Col key={item.key} xs={24} sm={12} lg={8} xl={4}>
              <AntCard size="small" styles={{ body: { minHeight: 92, padding: 16 } }}>
                <div className="mb-3 flex items-center justify-between">
                  <span className="text-xs text-slate-400">{item.label}</span>
                  <Icon className="size-4 text-slate-400" />
                </div>
                <div className={cn("text-2xl font-semibold tracking-tight", item.color)}>
                  {typeof value === "number" ? formatCompact(value) : value}
                </div>
              </AntCard>
              </Col>
            );
          })}
        </Row>
        <AntCard size="small">
          <div className="mb-3 text-sm font-medium text-slate-700">
              系统可用模型
            <span className="ml-1 text-slate-400">({availableModels.length})</span>
          </div>
          <div className="flex flex-wrap gap-2">
            {availableModels.length > 0 ? (
              availableModels.map((model) => (
                <Tag
                  key={model.id}
                  className="cursor-pointer rounded-full px-2.5 py-1"
                  onClick={() => {
                    void navigator.clipboard.writeText(model.id);
                    toast.success("模型名已复制");
                  }}
                >
                  {model.id}
                </Tag>
              ))
            ) : isLoadingModels ? (
              <Spin size="small" />
            ) : (
              <span className="text-sm text-slate-400">当前暂无可用模型</span>
            )}
          </div>
        </AntCard>
      </section>

      <section>

        {isLoading && accounts.length === 0 ? (
          <AntCard>
            <div className="flex flex-col items-center justify-center gap-3 px-6 py-14 text-center">
              <Spin />
              <div className="space-y-1">
                <p className="text-sm font-medium text-slate-700">正在加载账户</p>
                <p className="text-sm text-slate-500">从后端同步账号列表和状态。</p>
              </div>
            </div>
          </AntCard>
        ) : null}

        <AntCard
          className={cn("accounts-table-card", isLoading && accounts.length === 0 ? "hidden" : "")}
          title={
            <Space>
              <span>账户列表</span>
              <Tag color="blue" className="m-0">{filteredAccounts.length}</Tag>
            </Space>
          }
          extra={
            <Space wrap>
              <AntInput
                allowClear
                prefix={<Search className="size-4 text-slate-400" />}
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setPage(1);
                }}
                placeholder="搜索邮箱"
                style={{ width: 260 }}
              />
              <AntSelect
                value={typeFilter}
                onChange={(value) => {
                  setTypeFilter(value);
                  setPage(1);
                }}
                style={{ width: 150 }}
                options={accountTypeOptions}
              />
              <AntSelect
                value={statusFilter}
                onChange={(value) => {
                  setStatusFilter(value as AccountStatus | "all");
                  setPage(1);
                }}
                style={{ width: 150 }}
                options={accountStatusOptions}
              />
            </Space>
          }
          styles={{ body: { padding: 0 } }}
        >
            <div className="flex flex-col gap-3 border-b border-slate-100 bg-slate-50/60 px-4 py-3 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex flex-wrap items-center gap-2">
                <span className="mr-1 text-xs font-medium text-slate-400">批量操作</span>
                <AntButton
                  size="small"
                  icon={isRefreshing ? <LoaderCircle className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
                  onClick={() => void handleRefreshAccounts(selectedTokens)}
                  disabled={selectedTokens.length === 0 || isRefreshing}
                >
                  刷新选中
                </AntButton>
                <AntButton
                  size="small"
                  icon={isRelogining ? <LoaderCircle className="size-4 animate-spin" /> : <LogIn className="size-4" />}
                  onClick={() => void handleReLogin(selectedTokens)}
                  disabled={selectedTokens.length === 0 || isRelogining}
                  title="尝试密码登录恢复账号"
                >
                  恢复异常
                </AntButton>
                <span className="mx-1 h-5 w-px bg-slate-200" />
                <AntButton
                  danger
                  size="small"
                  icon={isDeleting ? <LoaderCircle className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
                  onClick={() => void handleDeleteTokens(abnormalTokens)}
                  disabled={abnormalTokens.length === 0 || isDeleting}
                >
                  移除异常账号
                </AntButton>
                <AntButton
                  danger
                  size="small"
                  icon={isDeleting ? <LoaderCircle className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
                  onClick={() => void handleDeleteTokens(selectedTokens)}
                  disabled={selectedTokens.length === 0 || isDeleting}
                >
                  删除所选
                </AntButton>
                {selectedIds.length > 0 ? (
                  <Tag color="processing" className="m-0 rounded-md">
                    已选择 {selectedIds.length} 项
                  </Tag>
                ) : null}
              </div>
            </div>

            <AntTable
              className="accounts-table"
              rowKey="access_token"
              columns={accountColumns}
              dataSource={currentRows}
              loading={isLoading}
              pagination={false}
              size="small"
              scroll={{ x: isCompactTable ? 1420 : 1980 }}
              locale={{
                emptyText: (
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description="没有匹配的账户，调整筛选条件或搜索关键字后重试。"
                  />
                ),
              }}
            />

            <div className="flex flex-col gap-3 border-t border-slate-100 px-4 py-4 lg:flex-row lg:items-center lg:justify-between">
              <div className="text-sm text-slate-500">
                显示第 {groupedAccounts.length === 0 ? 0 : startIndex + 1} -{" "}
                {Math.min(startIndex + Number(pageSize), groupedAccounts.length)} 条，共{" "}
                {groupedAccounts.length} 条
              </div>
              <AntPagination
                current={safePage}
                pageSize={Number(pageSize)}
                total={groupedAccounts.length}
                showSizeChanger
                pageSizeOptions={[10, 20, 50, 100]}
                showTotal={(total) => `共 ${total} 条`}
                onChange={(nextPage, nextPageSize) => {
                  setPage(nextPage);
                  setPageSize(String(nextPageSize));
                }}
              />
            </div>
        </AntCard>
      </section>
    </div>
  );
}

export default function AccountsPage() {
  const { isCheckingAuth, session } = useAuthGuard(["admin"]);

  if (isCheckingAuth || !session || session.role !== "admin") {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-stone-400" />
      </div>
    );
  }

  return <AccountsPageContent />;
}
