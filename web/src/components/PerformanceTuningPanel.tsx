import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  applyPerformanceConfig,
  applyPerformanceSafeMode,
  diagnosePerformance,
  getPerformanceBudget,
  listScopeCameras,
  pausePerception,
  toggleScopeCamera,
} from "@/api";
import type { AsyncState } from "@/hooks/useAsync";
import type {
  PerformanceBudget,
  PerformanceConfigParam,
  PerformanceConfigState,
  PerformanceDiagnosis,
  PerformanceParamValue,
} from "@/lib/types";

type Props = {
  budgetState: AsyncState<PerformanceBudget>;
  configState: AsyncState<PerformanceConfigState>;
  onReady: () => void;
};

type ParamCopy = {
  zh: string;
  en: string;
  hint: string;
  purpose: string;
  effect: string;
};

const PARAM_COPY: Record<string, ParamCopy> = {
  "camera.frame_interval": {
    zh: "摄像头取帧间隔",
    en: "Camera frame interval",
    hint: "数值越大越省 CPU。低配 NAS 建议 3000ms 左右。",
    purpose: "控制每路摄像头多久取一帧画面。",
    effect: "调大后更省 CPU，但家里变化会更晚被看到。",
  },
  "camera.max_cache_images": {
    zh: "每路摄像头缓存图片数",
    en: "Camera cache images",
    hint: "数值越小越省内存，但可回看的画面更少。",
    purpose: "控制每路摄像头最多在内存里留多少张历史画面。",
    effect: "调小后内存下降，但能回看的画面更少。",
  },
  "camera.video_quality": {
    zh: "摄像头拉流质量",
    en: "Camera stream quality",
    hint: "低配 NAS 建议 LOW。它会从源头减少视频解码和缩图压力。",
    purpose: "控制摄像头启动时优先拉低清流还是高清流。",
    effect: "LOW 更省 CPU、内存和带宽，但画面细节更少；HIGH 更清楚但更吃资源。",
  },
  "perception.collect.window_size": {
    zh: "单次感知窗口长度",
    en: "Collect window size",
    hint: "低配 NAS 建议 30-60 秒，用更慢的刷新换稳定。",
    purpose: "控制一次视觉分析会打包多少个时间片。",
    effect: "调大后分析次数减少，CPU 更稳，但发现变化会更慢。",
  },
  "perception.collect.max_windows": {
    zh: "最多排队窗口数",
    en: "Collect max windows",
    hint: "低配机器建议 1-2，避免堆积导致 CPU 越跑越高。",
    purpose: "控制处理不过来时最多允许积压多少个分析任务。",
    effect: "调小后不容易越积越卡，但忙不过来时会更早丢弃旧画面。",
  },
  "perception.collect.full_action": {
    zh: "队列满时怎么处理",
    en: "Window full action",
    hint: "低配机器建议 clear 或 drop，优先保护运行稳定。",
    purpose: "控制分析队列满了以后，是清空、丢弃，还是继续保留。",
    effect: "clear/drop 更适合低配机器；keep 保留更多数据但可能越跑越卡。",
  },
  "perception.engine.input.fps": {
    zh: "感知输入帧率",
    en: "Pipeline FPS",
    hint: "最影响 CPU。低配 NAS 建议 1 FPS。",
    purpose: "控制每秒送入感知流水线的画面数量。",
    effect: "调低后 CPU 会明显下降，但实时性会变差。",
  },
  "perception.engine.input.omni_fps": {
    zh: "送给 Omni 的帧率",
    en: "Omni FPS",
    hint: "越低越省 Omni 推理时间和 token，通常 1 就够。",
    purpose: "控制每秒最多送多少帧给多模态模型分析。",
    effect: "调低后模型调用更轻，但细节变化可能被跳过。",
  },
  "perception.engine.input.period_sec": {
    zh: "感知处理间隔",
    en: "Pipeline period",
    hint: "低配 NAS 建议 30-60 秒；数值越大，后台越不容易持续满载。",
    purpose: "控制 Miloco 多久跑一次完整视觉感知流程。",
    effect: "调大后 CPU 和 Omni 调用次数会下降，但家里变化会更晚被分析。",
  },
  "perception.engine.gate.hold_duration_sec": {
    zh: "画面变化保持时长",
    en: "Gate hold duration",
    hint: "低配 NAS 建议 0-30 秒；0 表示不把一次变化延长成持续视频分析。",
    purpose: "控制画面刚有变化后，Miloco 继续保持视觉分析的时间。",
    effect: "调小后能阻止长时间视频/Omni 堆积，但连续慢动作可能被拆散。",
  },
  "perception.engine.identity.tracking_service_mode": {
    zh: "身份跟踪模式",
    en: "Tracking mode",
    hint: "deep_sort 更准但更吃 CPU；mock 最省但基本不做真实跟踪。",
    purpose: "控制 Miloco 用哪种方式持续跟踪画面里的人。",
    effect: "deep_sort 更准但吃 CPU；mock 最省但身份连续性会变弱。",
  },
  "perception.engine.identity_engine.enabled": {
    zh: "身份识别开关",
    en: "Identity engine",
    hint: "关闭最省资源，但 Miloco 就不能识别是谁。",
    purpose: "控制是否识别画面里的人是谁。",
    effect: "关闭后最省资源，但家庭成员身份识别能力会不可用。",
  },
  "perception.engine.identity_engine.deep_sort.mode": {
    zh: "DeepSORT 省电模式",
    en: "DeepSORT mode",
    hint: "fast 更适合低配机器，会减少重复 ReID。",
    purpose: "控制 DeepSORT 身份跟踪的精细程度。",
    effect: "fast 更省 CPU；normal 更稳但更重。",
  },
  "perception.engine.identity_engine.deep_sort.human_reid_skip_windows": {
    zh: "人体 ReID 跳过窗口数",
    en: "ReID skip windows",
    hint: "数值越大越省 CPU，但身份刷新会更慢。",
    purpose: "控制隔多少个窗口才重新做一次人体身份匹配。",
    effect: "调大后更省 CPU，但身份更新会更慢。",
  },
  "perception.snapshot_max_disk_mb": {
    zh: "快照磁盘上限",
    en: "Snapshot disk cap",
    hint: "限制截图/片段占用空间，旧数据会更快清理。",
    purpose: "控制截图和短片最多占用多少磁盘空间。",
    effect: "调小后更省磁盘，但旧记录会更快被清理。",
  },
  "perf.enabled": {
    zh: "性能采集开关",
    en: "Perf metrics",
    hint: "调优期间建议保持开启。",
    purpose: "控制是否记录性能数据，用来生成当前这个页面。",
    effect: "关闭后略微省资源，但后续很难判断哪里卡。",
  },
  "perf.retention.traces_days": {
    zh: "Trace 保留天数",
    en: "Trace retention days",
    hint: "越短数据库越小。",
    purpose: "控制处理链路明细保留多少天。",
    effect: "调小后数据库更轻，但历史排障信息更少。",
  },
  "perf.retention.events_days": {
    zh: "事件保留天数",
    en: "Event retention days",
    hint: "越短数据库越小。",
    purpose: "控制性能事件记录保留多少天。",
    effect: "调小后数据库更轻，但历史趋势更短。",
  },
  "perf.retention.agent_runs_days": {
    zh: "Agent 记录保留天数",
    en: "Agent run retention days",
    hint: "越短数据库越小。",
    purpose: "控制 Agent 调用记录保留多少天。",
    effect: "调小后数据库更轻，但无法回看更早的 Agent 调用。",
  },
  "perf.retention.trace_jsonl_days": {
    zh: "Agent 原始日志保留天数",
    en: "Agent trace JSONL retention days",
    hint: "越短越省磁盘。",
    purpose: "控制 Agent 原始 JSONL 日志保留多少天。",
    effect: "调小后更省磁盘，但深度排障材料更少。",
  },
  "perf.retention.omni_log_days": {
    zh: "Omni 日志保留天数",
    en: "Omni log retention days",
    hint: "越短越省磁盘。",
    purpose: "控制 Omni 调用日志保留多少天。",
    effect: "调小后更省磁盘，但模型调用历史更短。",
  },
};

function fmtPct(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function fmtMb(value: number): string {
  if (value >= 1024) return `${(value / 1024).toFixed(1)} GB`;
  return `${value.toFixed(0)} MB`;
}

function valueFromInput(param: PerformanceConfigParam, raw: string): PerformanceParamValue {
  if (param.type === "boolean") return raw === "true";
  if (param.type === "integer") return Number.parseInt(raw, 10);
  if (param.type === "number") return Number.parseFloat(raw);
  return raw;
}

function changedParams(
  params: PerformanceConfigParam[],
  draft: Record<string, PerformanceParamValue>,
): PerformanceConfigParam[] {
  return params.filter((p) => draft[p.path] !== (p.value ?? ""));
}

function summarizeConfigValue(path: string, value: PerformanceParamValue): string {
  const copy = PARAM_COPY[path]?.zh ?? path;
  return `${copy} -> ${String(value)}`;
}

function supportedRangeText(param: PerformanceConfigParam): string {
  if (param.options?.length) {
    return `可选：${param.options.map((item) => String(item)).join(" / ")}`;
  }
  if (param.type === "boolean") return "可选：true / false";
  const min = param.min ?? null;
  const max = param.max ?? null;
  const step = param.step ?? null;
  if (min !== null && max !== null) {
    return `范围：${min} - ${max}${step ? `，步进 ${step}` : ""}`;
  }
  if (min !== null) return `范围：不小于 ${min}${step ? `，步进 ${step}` : ""}`;
  if (max !== null) return `范围：不大于 ${max}${step ? `，步进 ${step}` : ""}`;
  if (param.type === "integer") return "范围：整数";
  if (param.type === "number") return "范围：数字";
  return "范围：文本";
}

function statusText(over: boolean): string {
  return over ? "超预算" : "正常";
}

function budgetCardTone(over: boolean): string {
  return over
    ? "border-error bg-error-bg text-text-primary"
    : "border-success bg-success-bg text-text-primary";
}

function readableNoticeTone(kind: "warning" | "info" | "brand"): string {
  if (kind === "warning") {
    return "border-warning bg-warning-bg text-text-primary";
  }
  if (kind === "info") {
    return "border-info bg-info-bg text-text-primary";
  }
  return "border-brand-primary/40 bg-brand-soft text-text-primary";
}

function tradeoffText(path: string): string {
  if (path === "perception.engine.input.fps") {
    return "摄像头感知刷新会变慢，但 CPU 会明显下降。";
  }
  if (path === "perception.collect.window_size") {
    return "后台分析频率会降低，CPU 更稳，但感知刷新更慢。";
  }
  if (path === "perception.engine.input.period_sec") {
    return "感知会按更长间隔运行，CPU 明显下降，但不是实时看家。";
  }
  if (path === "perception.engine.gate.hold_duration_sec") {
    return "减少持续视频分析，避免 Omni 堆积，但连续变化的上下文会变少。";
  }
  if (path === "perception.collect.max_windows") {
    return "积压窗口会更快被丢弃，优先保证系统不卡死。";
  }
  if (path === "camera.max_cache_images") {
    return "可回看的缓存画面更少，但内存占用会下降。";
  }
  if (path === "camera.video_quality") {
    return "从源头降低视频分辨率，解码和缩图都会变轻，但画面细节会减少。";
  }
  if (path.includes("identity") || path.includes("deep_sort")) {
    return "身份识别刷新会变慢，但能减少持续高 CPU。";
  }
  if (path.includes("retention") || path.includes("snapshot")) {
    return "历史诊断数据保留更少，但磁盘和数据库压力更低。";
  }
  return "会降低一部分实时性或历史保留，换取低配机器更稳定运行。";
}

function noviceDiagnosisText(
  diagnosis: PerformanceDiagnosis | null,
  budget: PerformanceBudget | undefined,
  pendingCount: number,
): string {
  if (!diagnosis) {
    if (budget?.cpu_over_budget && budget.memory_over_budget) {
      return "当前 CPU 和内存都超过低配预算。先点「性能诊断」，让 Agent 给出一组降载参数。";
    }
    if (budget?.cpu_over_budget) {
      return "当前主要是 CPU 超预算。优先降低摄像头帧率、感知窗口和身份识别频率。";
    }
    if (budget?.memory_over_budget) {
      return "当前主要是内存超预算。优先减少缓存图片、窗口队列和日志保留。";
    }
    return "当前没有超过 50% 预算。可以先观察，出现卡顿再诊断。";
  }
  if (pendingCount > 0) {
    return `Agent 已给出低配方案，并填好了 ${pendingCount} 个待应用参数。确认后点「应用 ${pendingCount} 项并重启」。`;
  }
  return "Agent 没有给出需要改动的参数。可以继续观察 CPU/RAM 是否下降。";
}

async function waitForBackendReady(onPoll?: (attempt: number) => void): Promise<void> {
  const deadline = Date.now() + 120_000;
  let lastError: unknown;
  let attempt = 0;
  while (Date.now() < deadline) {
    attempt += 1;
    onPoll?.(attempt);
    try {
      await getPerformanceBudget();
      return;
    } catch (e) {
      lastError = e;
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }
  }
  throw lastError instanceof Error
    ? lastError
    : new Error("backend restart timeout");
}

function BudgetCard({
  title,
  current,
  budgetLine,
  ratio,
  over,
  explanation,
  action,
}: {
  title: string;
  current: string;
  budgetLine: string;
  ratio: string;
  over: boolean;
  explanation: string;
  action: string;
}) {
  return (
    <div
      className={`rounded-lg border p-4 space-y-3 ${budgetCardTone(over)}`}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="text-caption text-text-secondary">{title}</div>
        <div
          className={`text-caption font-medium ${
            over ? "text-error" : "text-success"
          }`}
        >
          {statusText(over)}
        </div>
      </div>
      <div className="mt-2 text-title text-text-primary">{current}</div>
      <div className="space-y-1 text-caption text-text-secondary">
        <div>{budgetLine}</div>
        <div>占宿主预算：{ratio}</div>
        <div className="text-text-primary">{explanation}</div>
        {over ? <div className="text-error">{action}</div> : null}
      </div>
    </div>
  );
}

function RestartOverlay({
  applying,
  restartWaiting,
  pollAttempt,
}: {
  applying: boolean;
  restartWaiting: boolean;
  pollAttempt: number;
}) {
  if (!applying && !restartWaiting) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 px-4">
      <div className="w-full max-w-md rounded-xl border border-border bg-bg-secondary shadow-lg p-5 space-y-3">
        <div className="text-title text-text-primary">后端正在应用并重启</div>
        <p className="text-body text-text-secondary leading-relaxed">
          请等 1-3 分钟，不要重复点击按钮。页面会每 2 秒自动检测后端是否恢复，
          恢复后会自动刷新当前性能数据。
        </p>
        <div className={`rounded-lg px-3 py-2 text-caption ${readableNoticeTone("info")}`}>
          {restartWaiting
            ? `正在自动检测第 ${pollAttempt || 1} 次...`
            : "正在写入配置并准备重启..."}
        </div>
        <p className="text-caption text-text-tertiary">
          如果超过 3 分钟还没有恢复，再手动刷新浏览器或检查后端日志。
        </p>
      </div>
    </div>
  );
}

export function PerformanceTuningPanel({
  budgetState,
  configState,
  onReady,
}: Props) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState<Record<string, PerformanceParamValue>>({});
  const [diagnosis, setDiagnosis] = useState<PerformanceDiagnosis | null>(null);
  const [diagnosing, setDiagnosing] = useState(false);
  const [applying, setApplying] = useState(false);
  const [restartWaiting, setRestartWaiting] = useState(false);
  const [hardActionRunning, setHardActionRunning] = useState(false);
  const [pollAttempt, setPollAttempt] = useState(0);
  const [message, setMessage] = useState<string | null>(null);
  const [userTouchedDraft, setUserTouchedDraft] = useState(false);
  const params = configState.data?.params ?? [];

  useEffect(() => {
    if (!configState.data) return;
    const config = configState.data;
    setDraft((prev) => {
      const currentValues = Object.fromEntries(
        config.params.map((p) => [p.path, p.value ?? ""]),
      );
      if (!userTouchedDraft) return currentValues;
      return { ...currentValues, ...prev };
    });
  }, [configState.data, userTouchedDraft]);

  const pendingParams = useMemo(() => changedParams(params, draft), [draft, params]);
  const pendingCount = pendingParams.length;
  const dirty = pendingCount > 0;

  const changedValues = (): Record<string, PerformanceParamValue> => {
    const out: Record<string, PerformanceParamValue> = {};
    for (const param of params) {
      const value = draft[param.path];
      if (value === (param.value ?? "")) continue;
      if (
        (param.type === "integer" || param.type === "number") &&
        (typeof value !== "number" || !Number.isFinite(value))
      ) {
        throw new Error(`${param.path}: ${t("perf.tuningInvalidNumber")}`);
      }
      out[param.path] = value;
    }
    return out;
  };

  const updateDraft = (path: string, value: PerformanceParamValue) => {
    setUserTouchedDraft(true);
    setDraft((prev) => ({ ...prev, [path]: value }));
  };

  const runDiagnosis = async () => {
    setDiagnosing(true);
    setMessage("正在诊断中，OpenClaw Agent 可能需要 30-60 秒，请不要重复点击。");
    try {
      const result = await diagnosePerformance();
      setDiagnosis(result);
      setUserTouchedDraft(true);
      setDraft((prev) => ({ ...prev, ...result.recommended_config }));
      const warningSuffix = result.warnings?.length
        ? ` 已自动修正 ${result.warnings.length} 个越界推荐值。`
        : "";
      setMessage(`${t("perf.tuningDiagnosisReady")}${warningSuffix}`);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setDiagnosing(false);
    }
  };

  const applyConfig = async () => {
    setApplying(true);
    setMessage(null);
    try {
      const values = changedValues();
      await applyPerformanceConfig(values);
      setRestartWaiting(true);
      setPollAttempt(0);
      setMessage(t("perf.tuningAppliedRestarting", { count: Object.keys(values).length }));
      await waitForBackendReady(setPollAttempt);
      setRestartWaiting(false);
      setMessage(t("perf.tuningRestarted"));
      setDiagnosis(null);
      setUserTouchedDraft(false);
      configState.reload();
      budgetState.reload();
      onReady();
    } catch (e) {
      setRestartWaiting(false);
      setMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setApplying(false);
    }
  };

  const reduceRealtimeCameras = async () => {
    setHardActionRunning(true);
    setMessage("正在把实时感知缩到 1 路摄像头，完成后 CPU 会在 1-2 个感知周期内下降。");
    try {
      const cameras = await listScopeCameras();
      const enabled = cameras.filter((cam) => cam.inUse);
      if (enabled.length <= 1) {
        setMessage("当前已经只启用 1 路或更少摄像头，不需要再缩减。");
        return;
      }
      const keep =
        enabled.find((cam) => cam.connected) ??
        enabled.find((cam) => cam.isOnline) ??
        enabled[0];
      const disableDids = enabled
        .filter((cam) => cam.did !== keep.did)
        .map((cam) => cam.did);
      await toggleScopeCamera(disableDids, false);
      setMessage(
        `已只保留「${keep.roomName || keep.name}」参与实时感知，其余 ${disableDids.length} 路已停用。CPU 会稍后刷新。`,
      );
      setTimeout(() => {
        budgetState.reload();
        onReady();
      }, 8000);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setHardActionRunning(false);
    }
  };

  const pauseRealtimePerception = async () => {
    setHardActionRunning(true);
    setMessage("正在暂停实时感知。这会立刻释放摄像头分析负载，但主动看家会停止。");
    try {
      await pausePerception();
      setMessage("实时感知已暂停。Miloco 面板和手动配置仍可用，CPU 应该快速下降。");
      setTimeout(() => {
        budgetState.reload();
        onReady();
      }, 5000);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setHardActionRunning(false);
    }
  };

  const applySafeMode = async () => {
    setApplying(true);
    setMessage("正在应用低配安全模式：保守参数、最多 1 路实时摄像头，并准备重启后端。");
    try {
      const result = await applyPerformanceSafeMode();
      const disabled = result.camera_action.disabled_count ?? 0;
      setRestartWaiting(true);
      setPollAttempt(0);
      setMessage(
        disabled > 0
          ? `低配安全模式已写入，并停用 ${disabled} 路实时摄像头。后端正在重启。`
          : "低配安全模式已写入。后端正在重启。",
      );
      await waitForBackendReady(setPollAttempt);
      setRestartWaiting(false);
      setMessage("低配安全模式已生效，正在刷新性能数据。");
      setDiagnosis(null);
      setUserTouchedDraft(false);
      configState.reload();
      budgetState.reload();
      onReady();
    } catch (e) {
      setRestartWaiting(false);
      setMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setApplying(false);
    }
  };

  const budget = budgetState.data;
  const noviceText = noviceDiagnosisText(diagnosis, budget, pendingCount);

  return (
    <section className="rounded-xl bg-bg-secondary border border-border shadow-sm p-4 space-y-4">
      <RestartOverlay
        applying={applying}
        restartWaiting={restartWaiting}
        pollAttempt={pollAttempt}
      />
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-title text-text-primary">
            {t("perf.tuningTitle")}
          </h2>
          <p className="text-caption text-text-tertiary mt-1">
            {t("perf.tuningSubtitle")}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={runDiagnosis}
            disabled={diagnosing || applying}
            className="text-caption px-3 py-1.5 rounded-md border border-border text-text-secondary hover:text-text-primary hover:border-border-strong disabled:opacity-50 transition-colors"
          >
            {diagnosing ? t("perf.tuningDiagnosing") : t("perf.tuningDiagnose")}
          </button>
          <button
            type="button"
            onClick={applyConfig}
            disabled={applying || restartWaiting || params.length === 0 || !dirty}
            className="text-caption px-3 py-1.5 rounded-md bg-brand-primary text-white disabled:opacity-50 transition-colors"
          >
            {applying || restartWaiting
              ? t("perf.tuningApplying")
              : dirty
                ? t("perf.tuningApplyCount", { count: pendingCount })
                : t("perf.tuningApply")}
          </button>
        </div>
      </div>

      {budget ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <BudgetCard
            title={t("perf.tuningCpuBudget")}
            current={`${budget.cpu_pct.toFixed(1)}%`}
            budgetLine={`低配目标：不超过 ${budget.cpu_budget_pct.toFixed(1)}%`}
            ratio={fmtPct(budget.cpu_ratio)}
            over={budget.cpu_over_budget}
            explanation="这就是 Miloco 让 NAS 忙到什么程度。超过目标时，网页会慢、SSH 会卡，摄像头分析也会排队。"
            action="处理办法：把感知输入帧率降到 1，把处理间隔拉长，并关闭重身份识别。"
          />
          <BudgetCard
            title={t("perf.tuningRamBudget")}
            current={fmtMb(budget.rss_mb)}
            budgetLine={`低配目标：不超过 ${fmtMb(budget.memory_budget_mb)}`}
            ratio={fmtPct(budget.memory_ratio)}
            over={budget.memory_over_budget}
            explanation={`这是 Miloco 占用的内存。宿主总内存约 ${fmtMb(budget.host_total_memory_mb)}，超过目标后系统会开始抢内存。`}
            action="处理办法：减少缓存图片、排队窗口和历史保留天数。"
          />
        </div>
      ) : (
        <div className="text-caption text-text-tertiary">
          {budgetState.loading ? t("perf.loading") : budgetState.error?.message}
        </div>
      )}

      <div
        className={`rounded-lg border px-3 py-3 ${
          budget?.cpu_over_budget || budget?.memory_over_budget
            ? readableNoticeTone("warning")
            : "border-border bg-bg-primary"
        }`}
      >
        <div className="text-caption font-medium text-text-secondary mb-1">
          {t("perf.tuningNoviceTitle")}
        </div>
        <div className="text-body text-text-primary">{noviceText}</div>
      </div>

      {budget?.cpu_over_budget ? (
        <div className={`rounded-lg px-3 py-3 text-caption ${readableNoticeTone("warning")}`}>
          <div className="text-body text-text-primary font-medium mb-1">
            参数应用后 CPU 仍然超预算时，优先做硬降载
          </div>
          <div className="text-text-secondary leading-relaxed mb-3">
            多路摄像头会让低配 NAS 持续解码和推理。下面两个操作不需要懂参数：
            先只保留 1 路实时摄像头；如果 NAS 已经卡到管理面板都慢，再暂停实时感知。
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={applySafeMode}
              disabled={hardActionRunning || applying || restartWaiting}
              className="px-3 py-1.5 rounded-md bg-brand-primary text-white disabled:opacity-50 transition-colors"
            >
              一键低配安全模式
            </button>
            <button
              type="button"
              onClick={reduceRealtimeCameras}
              disabled={hardActionRunning || applying || restartWaiting}
              className="px-3 py-1.5 rounded-md border border-border text-text-primary bg-bg-primary disabled:opacity-50 transition-colors"
            >
              只保留 1 路实时摄像头
            </button>
            <button
              type="button"
              onClick={pauseRealtimePerception}
              disabled={hardActionRunning || applying || restartWaiting}
              className="px-3 py-1.5 rounded-md border border-error text-error bg-error-bg disabled:opacity-50 transition-colors"
            >
              暂停实时感知
            </button>
          </div>
        </div>
      ) : null}

      {diagnosis ? (
        <div className="rounded-lg border border-border bg-bg-primary p-3 space-y-3">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div className="text-caption text-text-secondary">
              {t("perf.tuningAgentRawHint")}
            </div>
            <span className="text-caption text-text-tertiary">
              {diagnosis.recommended_preset} · {diagnosis.risk_level}
            </span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <div className="text-caption font-medium text-text-secondary mb-1">
                {t("perf.tuningBottlenecks")}
              </div>
              <ul className="space-y-1 text-caption text-text-tertiary">
                {pendingParams.slice(0, 4).map((param) => (
                  <li key={param.path}>
                    {summarizeConfigValue(param.path, draft[param.path])}
                  </li>
                ))}
                {pendingParams.length === 0 ? (
                  <li>Agent 没有建议改参数，先继续观察。</li>
                ) : null}
              </ul>
            </div>
            <div>
              <div className="text-caption font-medium text-text-secondary mb-1">
                {t("perf.tuningTradeoffs")}
              </div>
              <ul className="space-y-1 text-caption text-text-tertiary">
                {pendingParams.slice(0, 4).map((param) => (
                  <li key={param.path}>{tradeoffText(param.path)}</li>
                ))}
                {pendingParams.length === 0 ? (
                  <li>暂无额外降级影响。</li>
                ) : null}
              </ul>
            </div>
          </div>
          <details className="text-caption text-text-tertiary">
            <summary className="cursor-pointer text-text-secondary">
              {t("perf.tuningAgentRaw")}
            </summary>
            <p className="mt-2 leading-relaxed">{diagnosis.summary}</p>
          </details>
          {diagnosis.warnings?.length ? (
            <div className={`rounded-lg px-3 py-2 text-caption ${readableNoticeTone("warning")}`}>
              Agent 推荐里有越界值，已按面板支持范围自动修正：
              {diagnosis.warnings.slice(0, 3).join("；")}
            </div>
          ) : null}
        </div>
      ) : null}

      {message ? (
        <div className="rounded-lg border border-border bg-bg-primary px-3 py-2 text-caption text-text-secondary">
          {message}
        </div>
      ) : null}

      {dirty ? (
        <div className={`rounded-lg px-3 py-2 text-caption ${readableNoticeTone("brand")}`}>
          <span className="font-medium text-text-primary">
            {t("perf.tuningPendingCount", { count: pendingCount })}
          </span>
          <span className="ml-2">
            {pendingParams
              .slice(0, 3)
              .map((p) => summarizeConfigValue(p.path, draft[p.path]))
              .join("；")}
          </span>
        </div>
      ) : null}

      <div className="space-y-3">
        <div className="grid grid-cols-1 lg:grid-cols-[minmax(220px,1fr)_120px_minmax(180px,220px)_minmax(280px,1.4fr)] gap-3 px-1 text-caption text-text-tertiary">
          <div>{t("perf.tuningParam")}</div>
          <div>{t("perf.tuningCurrent")}</div>
          <div>{t("perf.tuningValue")}</div>
          <div>{t("perf.tuningImpact")}</div>
        </div>
        {params.map((param) => {
          const current = draft[param.path] ?? "";
          const recommended =
            diagnosis?.recommended_config[param.path] !== undefined;
          const changed = current !== (param.value ?? "");
          const copy = PARAM_COPY[param.path] ?? {
            zh: param.label,
            en: param.label,
            hint: param.impact || param.description,
            purpose: param.description,
            effect: param.impact,
          };
          const controlClass = `w-full rounded-md border px-2 py-2 bg-bg-primary text-text-primary ${
            changed || recommended ? "border-brand-primary" : "border-border"
          }`;
          return (
            <div
              key={param.path}
              className={`grid grid-cols-1 lg:grid-cols-[minmax(220px,1fr)_120px_minmax(180px,220px)_minmax(280px,1.4fr)] gap-3 rounded-lg border p-3 ${
                changed
                  ? readableNoticeTone("brand")
                  : "border-border bg-bg-primary"
              }`}
            >
              <div className="min-w-0">
                <div className="flex items-start gap-2">
                  <div className="min-w-0">
                    <div className="text-text-primary font-medium break-words">
                      {copy.zh}
                    </div>
                    <div className="text-text-tertiary opacity-70 break-words">
                      {copy.en}
                    </div>
                    <div className="text-text-tertiary break-all">
                      {param.path}
                    </div>
                  </div>
                  {changed ? (
                    <span className="shrink-0 rounded-full bg-bg-secondary text-brand-primary border border-brand-primary/40 px-2 py-0.5 text-caption">
                      {t("perf.tuningChanged")}
                    </span>
                  ) : null}
                </div>
              </div>

              <div>
                <div className="lg:hidden text-caption text-text-tertiary mb-1">
                  {t("perf.tuningCurrent")}
                </div>
                <div className="text-text-primary break-all">
                  {String(param.value ?? "未设置")}
                </div>
              </div>

              <div>
                <div className="lg:hidden text-caption text-text-tertiary mb-1">
                  {t("perf.tuningValue")}
                </div>
                {param.options ? (
                  <select
                    value={String(current)}
                    onChange={(e) =>
                      updateDraft(param.path, valueFromInput(param, e.target.value))
                    }
                    className={controlClass}
                  >
                    {param.options.map((opt) => (
                      <option key={String(opt)} value={String(opt)}>
                        {String(opt)}
                      </option>
                    ))}
                  </select>
                ) : param.type === "boolean" ? (
                  <select
                    value={String(current)}
                    onChange={(e) =>
                      updateDraft(param.path, valueFromInput(param, e.target.value))
                    }
                    className={controlClass}
                  >
                    <option value="true">true</option>
                    <option value="false">false</option>
                  </select>
                ) : (
                  <input
                    type={param.type === "string" ? "text" : "number"}
                    min={param.min ?? undefined}
                    max={param.max ?? undefined}
                    step={param.step ?? undefined}
                    value={String(current)}
                    onChange={(e) =>
                      updateDraft(param.path, valueFromInput(param, e.target.value))
                    }
                    className={controlClass}
                  />
                )}
              </div>

              <div className="space-y-1 text-caption leading-relaxed">
                <div className="lg:hidden text-caption text-text-tertiary mb-1">
                  {t("perf.tuningImpact")}
                </div>
                <div className="text-text-primary">{copy.purpose}</div>
                <div className="text-text-secondary">{supportedRangeText(param)}</div>
                <div className="text-text-secondary">{copy.effect}</div>
                <div className="text-text-tertiary opacity-70">{copy.hint}</div>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
