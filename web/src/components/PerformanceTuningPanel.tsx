import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  applyPerformanceConfig,
  diagnosePerformance,
  getPerformanceBudget,
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
};

const PARAM_COPY: Record<string, ParamCopy> = {
  "camera.frame_interval": {
    zh: "摄像头取帧间隔",
    en: "Camera frame interval",
    hint: "数值越大越省 CPU。低配 NAS 建议 3000ms 左右。",
  },
  "camera.max_cache_images": {
    zh: "每路摄像头缓存图片数",
    en: "Camera cache images",
    hint: "数值越小越省内存，但可回看的画面更少。",
  },
  "perception.collect.window_size": {
    zh: "单次感知窗口长度",
    en: "Collect window size",
    hint: "窗口越短，每次送给 Omni 的图片越少，延迟和负载更低。",
  },
  "perception.collect.max_windows": {
    zh: "最多排队窗口数",
    en: "Collect max windows",
    hint: "低配机器建议 1-2，避免堆积导致 CPU 越跑越高。",
  },
  "perception.collect.full_action": {
    zh: "队列满时怎么处理",
    en: "Window full action",
    hint: "低配机器建议 clear 或 drop，优先保护运行稳定。",
  },
  "perception.engine.input.fps": {
    zh: "感知输入帧率",
    en: "Pipeline FPS",
    hint: "最影响 CPU。低配 NAS 建议 1 FPS。",
  },
  "perception.engine.input.omni_fps": {
    zh: "送给 Omni 的帧率",
    en: "Omni FPS",
    hint: "越低越省 Omni 推理时间和 token，通常 1 就够。",
  },
  "perception.engine.identity.tracking_service_mode": {
    zh: "身份跟踪模式",
    en: "Tracking mode",
    hint: "deep_sort 更准但更吃 CPU；mock 最省但基本不做真实跟踪。",
  },
  "perception.engine.identity_engine.enabled": {
    zh: "身份识别开关",
    en: "Identity engine",
    hint: "关闭最省资源，但 Miloco 就不能识别是谁。",
  },
  "perception.engine.identity_engine.deep_sort.mode": {
    zh: "DeepSORT 省电模式",
    en: "DeepSORT mode",
    hint: "fast 更适合低配机器，会减少重复 ReID。",
  },
  "perception.engine.identity_engine.deep_sort.human_reid_skip_windows": {
    zh: "人体 ReID 跳过窗口数",
    en: "ReID skip windows",
    hint: "数值越大越省 CPU，但身份刷新会更慢。",
  },
  "perception.snapshot_max_disk_mb": {
    zh: "快照磁盘上限",
    en: "Snapshot disk cap",
    hint: "限制截图/片段占用空间，旧数据会更快清理。",
  },
  "perf.enabled": {
    zh: "性能采集开关",
    en: "Perf metrics",
    hint: "调优期间建议保持开启。",
  },
  "perf.retention.traces_days": {
    zh: "Trace 保留天数",
    en: "Trace retention days",
    hint: "越短数据库越小。",
  },
  "perf.retention.events_days": {
    zh: "事件保留天数",
    en: "Event retention days",
    hint: "越短数据库越小。",
  },
  "perf.retention.agent_runs_days": {
    zh: "Agent 记录保留天数",
    en: "Agent run retention days",
    hint: "越短数据库越小。",
  },
  "perf.retention.trace_jsonl_days": {
    zh: "Agent 原始日志保留天数",
    en: "Agent trace JSONL retention days",
    hint: "越短越省磁盘。",
  },
  "perf.retention.omni_log_days": {
    zh: "Omni 日志保留天数",
    en: "Omni log retention days",
    hint: "越短越省磁盘。",
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

function tradeoffText(path: string): string {
  if (path === "perception.engine.input.fps") {
    return "摄像头感知刷新会变慢，但 CPU 会明显下降。";
  }
  if (path === "perception.collect.window_size") {
    return "每次分析的画面更少，细节描述会少一些。";
  }
  if (path === "perception.collect.max_windows") {
    return "积压窗口会更快被丢弃，优先保证系统不卡死。";
  }
  if (path === "camera.max_cache_images") {
    return "可回看的缓存画面更少，但内存占用会下降。";
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

async function waitForBackendReady(): Promise<void> {
  const deadline = Date.now() + 60_000;
  let lastError: unknown;
  while (Date.now() < deadline) {
    try {
      await getPerformanceBudget();
      return;
    } catch (e) {
      lastError = e;
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }
  }
  throw lastError instanceof Error ? lastError : new Error("backend restart timeout");
}

function BudgetCard({
  title,
  current,
  budget,
  ratio,
  over,
}: {
  title: string;
  current: string;
  budget: string;
  ratio: string;
  over: boolean;
}) {
  return (
    <div
      className={`rounded-lg border p-3 ${
        over ? "border-red-300 bg-red-50" : "border-border bg-bg-primary"
      }`}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="text-caption text-text-secondary">{title}</div>
        <div
          className={`text-caption font-medium ${
            over ? "text-red-700" : "text-emerald-700"
          }`}
        >
          {over ? "OVER" : "OK"}
        </div>
      </div>
      <div className="mt-2 text-title text-text-primary">{current}</div>
      <div className="mt-1 text-caption text-text-tertiary">
        {budget} · {ratio}
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
    setMessage(null);
    try {
      const result = await diagnosePerformance();
      setDiagnosis(result);
      setUserTouchedDraft(true);
      setDraft((prev) => ({ ...prev, ...result.recommended_config }));
      setMessage(t("perf.tuningDiagnosisReady"));
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
      setMessage(t("perf.tuningAppliedRestarting", { count: Object.keys(values).length }));
      await waitForBackendReady();
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

  const budget = budgetState.data;
  const noviceText = noviceDiagnosisText(diagnosis, budget, pendingCount);

  return (
    <section className="rounded-xl bg-bg-secondary border border-border shadow-sm p-4 space-y-4">
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
            budget={`${t("perf.tuningBudget")} ${budget.cpu_budget_pct.toFixed(1)}%`}
            ratio={fmtPct(budget.cpu_ratio)}
            over={budget.cpu_over_budget}
          />
          <BudgetCard
            title={t("perf.tuningRamBudget")}
            current={fmtMb(budget.rss_mb)}
            budget={`${t("perf.tuningBudget")} ${fmtMb(budget.memory_budget_mb)}`}
            ratio={fmtPct(budget.memory_ratio)}
            over={budget.memory_over_budget}
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
            ? "border-amber-200 bg-amber-50"
            : "border-border bg-bg-primary"
        }`}
      >
        <div className="text-caption font-medium text-text-secondary mb-1">
          {t("perf.tuningNoviceTitle")}
        </div>
        <div className="text-body text-text-primary">{noviceText}</div>
      </div>

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
        </div>
      ) : null}

      {message ? (
        <div className="rounded-lg border border-border bg-bg-primary px-3 py-2 text-caption text-text-secondary">
          {message}
        </div>
      ) : null}

      {dirty ? (
        <div className="rounded-lg border border-brand-primary/30 bg-brand-soft px-3 py-2 text-caption text-text-secondary">
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

      <div className="overflow-x-auto">
        <table className="min-w-full text-caption">
          <thead>
            <tr className="text-left text-text-tertiary border-b border-border">
              <th className="py-2 pr-4">{t("perf.tuningParam")}</th>
              <th className="py-2 pr-4">{t("perf.tuningCurrent")}</th>
              <th className="py-2 pr-4">{t("perf.tuningValue")}</th>
              <th className="py-2 pr-4">{t("perf.tuningImpact")}</th>
            </tr>
          </thead>
          <tbody>
            {params.map((param) => {
              const current = draft[param.path] ?? "";
              const recommended =
                diagnosis?.recommended_config[param.path] !== undefined;
              const changed = current !== (param.value ?? "");
              const copy = PARAM_COPY[param.path] ?? {
                zh: param.label,
                en: param.label,
                hint: param.impact || param.description,
              };
              return (
                <tr key={param.path} className="border-b border-border/60">
                  <td className="py-2 pr-4 min-w-64">
                    <div className="text-text-primary font-medium">{copy.zh}</div>
                    <div className="text-text-tertiary opacity-60">{copy.en}</div>
                    <div className="text-text-tertiary">{param.path}</div>
                  </td>
                  <td className="py-2 pr-4 text-text-secondary">
                    {String(param.value ?? "")}
                  </td>
                  <td className="py-2 pr-4">
                    <div className="flex items-center gap-2">
                      {param.options ? (
                        <select
                          value={String(current)}
                          onChange={(e) =>
                            updateDraft(param.path, valueFromInput(param, e.target.value))
                          }
                          className={`rounded-md border px-2 py-1 bg-bg-primary text-text-primary ${
                            changed || recommended
                              ? "border-brand-primary"
                              : "border-border"
                          }`}
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
                          className={`rounded-md border px-2 py-1 bg-bg-primary text-text-primary ${
                            changed || recommended
                              ? "border-brand-primary"
                              : "border-border"
                          }`}
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
                          className={`w-32 rounded-md border px-2 py-1 bg-bg-primary text-text-primary ${
                            changed || recommended
                              ? "border-brand-primary"
                              : "border-border"
                          }`}
                        />
                      )}
                      {changed ? (
                        <span className="rounded-full bg-brand-soft text-brand-primary border border-brand-primary/30 px-2 py-0.5">
                          {t("perf.tuningChanged")}
                        </span>
                      ) : null}
                    </div>
                  </td>
                  <td className="py-2 pr-4 min-w-72">
                    <div className="text-text-secondary">{copy.hint}</div>
                    <div className="text-text-tertiary opacity-60 mt-1">
                      {param.impact || param.description}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
