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
  const params = configState.data?.params ?? [];

  useEffect(() => {
    if (!configState.data) return;
    setDraft(
      Object.fromEntries(
        configState.data.params.map((p) => [p.path, p.value ?? ""]),
      ),
    );
  }, [configState.data]);

  const dirty = useMemo(() => {
    return params.some((p) => draft[p.path] !== (p.value ?? ""));
  }, [draft, params]);

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
    setDraft((prev) => ({ ...prev, [path]: value }));
  };

  const runDiagnosis = async () => {
    setDiagnosing(true);
    setMessage(null);
    try {
      const result = await diagnosePerformance();
      setDiagnosis(result);
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
      await applyPerformanceConfig(changedValues());
      setRestartWaiting(true);
      setMessage(t("perf.tuningRestarting"));
      await waitForBackendReady();
      setRestartWaiting(false);
      setMessage(t("perf.tuningRestarted"));
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

      {diagnosis ? (
        <div className="rounded-lg border border-border bg-bg-primary p-3 space-y-3">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div className="text-body text-text-primary">{diagnosis.summary}</div>
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
                {diagnosis.bottlenecks.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
            <div>
              <div className="text-caption font-medium text-text-secondary mb-1">
                {t("perf.tuningTradeoffs")}
              </div>
              <ul className="space-y-1 text-caption text-text-tertiary">
                {diagnosis.expected_tradeoffs.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      ) : null}

      {message ? (
        <div className="rounded-lg border border-border bg-bg-primary px-3 py-2 text-caption text-text-secondary">
          {message}
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
              return (
                <tr key={param.path} className="border-b border-border/60">
                  <td className="py-2 pr-4 min-w-56">
                    <div className="text-text-primary font-medium">{param.label}</div>
                    <div className="text-text-tertiary">{param.path}</div>
                  </td>
                  <td className="py-2 pr-4 text-text-secondary">
                    {String(param.value ?? "")}
                  </td>
                  <td className="py-2 pr-4">
                    {param.options ? (
                      <select
                        value={String(current)}
                        onChange={(e) =>
                          updateDraft(param.path, valueFromInput(param, e.target.value))
                        }
                        className={`rounded-md border px-2 py-1 bg-bg-primary text-text-primary ${
                          recommended ? "border-brand-primary" : "border-border"
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
                          recommended ? "border-brand-primary" : "border-border"
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
                          recommended ? "border-brand-primary" : "border-border"
                        }`}
                      />
                    )}
                  </td>
                  <td className="py-2 pr-4 text-text-tertiary min-w-64">
                    {param.impact || param.description}
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
