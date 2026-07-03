/**
 * 阶段统计表:7 阶段 × AVG / P50 / P75 / P95 / P99 / 样本数。
 *
 * P95 列按耗时降序排出 top3,分别用 1st/2nd/3rd 三档色高亮,定位"哪个阶段最慢"。
 * 颜色:1st=error 红 / 2nd=info 蓝 / 3rd=success 绿。
 */

import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import type { AsyncState } from "@/hooks/useAsync";
import type { PerfStageKey, PerfStagePercentiles } from "@/lib/types";

interface Props {
  state: AsyncState<PerfStagePercentiles>;
}

const STAGE_ORDER: PerfStageKey[] = [
  "decode_ms",
  "collect_ms",
  "convert_ms",
  "gate_ms",
  "identity_ms",
  "omni_ms",
  "log_ms",
];

const STAGE_LABEL: Record<PerfStageKey, string> = {
  decode_ms: "decode",
  collect_ms: "collect",
  convert_ms: "convert",
  gate_ms: "gate",
  identity_ms: "identity",
  omni_ms: "omni",
  log_ms: "log",
};

const STAGE_COPY: Record<
  PerfStageKey,
  { zh: string; en: string; plain: string }
> = {
  decode_ms: {
    zh: "拉流解码",
    en: "decode",
    plain: "把摄像头视频还原成图片帧，本地 CPU 压力源之一。",
  },
  collect_ms: {
    zh: "窗口收集",
    en: "collect",
    plain: "把一段时间内的画面整理成一次待分析窗口。",
  },
  convert_ms: {
    zh: "格式转换",
    en: "convert",
    plain: "把图片或视频整理成后续算法可用的格式。",
  },
  gate_ms: {
    zh: "画面变化检测",
    en: "gate",
    plain: "先判断画面有没有明显变化，避免每次都进重模型。",
  },
  identity_ms: {
    zh: "身份识别",
    en: "identity",
    plain: "识别人和跟踪人，开销取决于人数、摄像头数量和模型模式。",
  },
  omni_ms: {
    zh: "云端理解",
    en: "omni",
    plain: "上传给多模态模型并等待回答，更多反映网络/API等待。",
  },
  log_ms: {
    zh: "写日志",
    en: "log",
    plain: "把结果写入数据库和日志，通常不应成为主要瓶颈。",
  },
};

const STAGE_COLORS: Record<PerfStageKey, string> = {
  decode_ms: "#F97316",
  collect_ms: "#0EA5E9",
  convert_ms: "#8B5CF6",
  gate_ms: "#14B8A6",
  identity_ms: "#EF4444",
  omni_ms: "#6366F1",
  log_ms: "#64748B",
};

const RANK_TEXT_CLASS = ["text-error", "text-info", "text-success"];

export function PerfStageTable({ state }: Props) {
  const { t } = useTranslation();
  return (
    <section
      className="rounded-xl bg-bg-secondary border border-border shadow-sm p-5 md:p-6"
      aria-labelledby="perf-stage-title"
    >
      <div className="flex items-baseline justify-between flex-wrap gap-2 mb-4">
        <h2 id="perf-stage-title" className="text-title">
          {t("perf.stageTitle")}
        </h2>
        <span className="text-caption text-text-secondary">
          {t("perf.stageP95Top3")}
          <span className="text-error mx-1">● {t("perf.stageRank1st")}</span>
          <span className="text-info mx-1">● {t("perf.stageRank2nd")}</span>
          <span className="text-success mx-1">● {t("perf.stageRank3rd")}</span>
        </span>
      </div>

      {state.loading && !state.data ? (
        <div className="py-8 text-center text-text-secondary">{t("perf.loading")}</div>
      ) : state.error ? (
        <div className="py-8 text-center text-error">{state.error.message}</div>
      ) : state.data ? (
        <Table data={state.data} t={t} />
      ) : null}
    </section>
  );
}

function Table({ data, t }: { data: PerfStagePercentiles; t: TFunction }) {
  // 按 P95 降序排出 top3
  const sortedByP95 = [...STAGE_ORDER].sort(
    (a, b) => data[b].p95 - data[a].p95,
  );
  const rankOf = new Map<PerfStageKey, number>();
  sortedByP95.slice(0, 3).forEach((k, i) => rankOf.set(k, i));

  // 占比基准:所有非空阶段 avg 之和作为 100%(表内自洽口径)。
  const totalAvg = STAGE_ORDER.reduce(
    (sum, k) => sum + (data[k].sample_size > 0 ? data[k].avg : 0),
    0,
  );

  return (
    <div className="space-y-5">
      <StageAttributionCharts data={data} totalAvg={totalAvg} t={t} />
      <div className="text-caption overflow-x-auto -mx-5 md:-mx-6">
        <table className="w-full">
          <thead>
            <tr className="text-text-secondary border-b border-border">
              <th className="text-left px-5 md:px-6 py-2">{t("perf.colStage")}</th>
              <th className="text-right px-3 py-2 num">{t("perf.colAvgMs")}</th>
              <th className="text-right px-3 py-2 num">{t("perf.colAvgPct")}</th>
              <th className="text-right px-3 py-2 num">{t("perf.colP50Ms")}</th>
              <th className="text-right px-3 py-2 num">{t("perf.colP75Ms")}</th>
              <th className="text-right px-3 py-2 num">{t("perf.colP95Ms")}</th>
              <th className="text-right px-3 py-2 num">{t("perf.colP99Ms")}</th>
              <th className="text-right px-5 md:px-6 py-2 num">{t("perf.colSampleSize")}</th>
            </tr>
          </thead>
          <tbody>
            {STAGE_ORDER.map((k) => {
              const row = data[k];
              const rank = rankOf.get(k);
              const rankCls =
                rank !== undefined ? RANK_TEXT_CLASS[rank] : "text-text-primary";
              const isEmpty = row.sample_size === 0;
              const pct = !isEmpty && totalAvg > 0 ? (row.avg / totalAvg) * 100 : 0;
              return (
                <tr
                  key={k}
                  className="border-b border-border last:border-b-0"
                >
                  <td className="px-5 md:px-6 py-2.5 text-text-primary">
                    <span className="font-medium">{STAGE_COPY[k].zh}</span>
                    <span className="ml-2 text-text-tertiary opacity-70 mono">
                      {STAGE_LABEL[k]}
                    </span>
                  </td>
                  <td
                    className={`px-3 py-2.5 text-right num ${
                      isEmpty ? "text-text-tertiary" : "text-text-secondary"
                    }`}
                  >
                    {isEmpty ? "—" : row.avg.toFixed(1)}
                  </td>
                  <td
                    className={`px-3 py-2.5 text-right num ${
                      isEmpty ? "text-text-tertiary" : "text-text-secondary"
                    }`}
                  >
                    {isEmpty ? "—" : `${pct.toFixed(2)}%`}
                  </td>
                  <td
                    className={`px-3 py-2.5 text-right num ${
                      isEmpty ? "text-text-tertiary" : "text-text-secondary"
                    }`}
                  >
                    {isEmpty ? "—" : row.p50.toFixed(1)}
                  </td>
                  <td
                    className={`px-3 py-2.5 text-right num ${
                      isEmpty ? "text-text-tertiary" : "text-text-secondary"
                    }`}
                  >
                    {isEmpty ? "—" : row.p75.toFixed(1)}
                  </td>
                  <td
                    className={`px-3 py-2.5 text-right num font-semibold ${
                      isEmpty ? "text-text-tertiary" : rankCls
                    }`}
                  >
                    {isEmpty ? "—" : row.p95.toFixed(1)}
                  </td>
                  <td
                    className={`px-3 py-2.5 text-right num ${
                      isEmpty ? "text-text-tertiary" : "text-text-secondary"
                    }`}
                  >
                    {isEmpty ? "—" : row.p99.toFixed(1)}
                  </td>
                  <td className="px-5 md:px-6 py-2.5 text-right num text-text-tertiary">
                    {row.sample_size.toLocaleString()}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function StageAttributionCharts({
  data,
  totalAvg,
  t,
}: {
  data: PerfStagePercentiles;
  totalAvg: number;
  t: TFunction;
}) {
  const rows = STAGE_ORDER.map((key) => ({
    key,
    row: data[key],
    share:
      data[key].sample_size > 0 && totalAvg > 0 ? data[key].avg / totalAvg : 0,
  })).sort((a, b) => b.row.p95 - a.row.p95);
  const maxP95 = Math.max(...rows.map((item) => item.row.p95), 1);
  const leading = rows.find((item) => item.row.sample_size > 0);

  return (
    <div className="grid grid-cols-1 xl:grid-cols-[minmax(260px,0.85fr)_minmax(420px,1.4fr)] gap-4">
      <div className="rounded-lg border border-border bg-bg-primary p-4">
        <div className="text-caption font-medium text-text-secondary mb-3">
          {t("perf.stageAttributionPie")}
        </div>
        <div className="flex items-center gap-4">
          <StageDonut rows={rows} />
          <div className="min-w-0 space-y-2 text-caption">
            {leading ? (
              <div>
                <div className="text-text-primary font-medium">
                  最主要压力：{STAGE_COPY[leading.key].zh}
                </div>
                <div className="text-text-secondary leading-relaxed">
                  {STAGE_COPY[leading.key].plain}
                </div>
              </div>
            ) : (
              <div className="text-text-tertiary">暂无阶段样本。</div>
            )}
            <div className="space-y-1">
              {rows.slice(0, 4).map((item) => (
                <div key={item.key} className="flex items-center gap-2">
                  <span
                    className="h-2.5 w-2.5 rounded-full shrink-0"
                    style={{ backgroundColor: STAGE_COLORS[item.key] }}
                  />
                  <span className="text-text-primary shrink-0">
                    {STAGE_COPY[item.key].zh}
                  </span>
                  <span className="text-text-tertiary opacity-70 mono">
                    {STAGE_COPY[item.key].en}
                  </span>
                  <span className="ml-auto text-text-secondary num">
                    {(item.share * 100).toFixed(1)}%
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="rounded-lg border border-border bg-bg-primary p-4">
        <div className="text-caption font-medium text-text-secondary mb-3">
          {t("perf.stageAttributionBars")}
        </div>
        <div className="space-y-2">
          {rows.map((item) => {
            const width = item.row.sample_size > 0 ? (item.row.p95 / maxP95) * 100 : 0;
            return (
              <div key={item.key} className="grid grid-cols-[116px_minmax(0,1fr)_72px] gap-3 items-center text-caption">
                <div className="min-w-0">
                  <div className="text-text-primary truncate">
                    {STAGE_COPY[item.key].zh}
                  </div>
                  <div className="text-text-tertiary opacity-70 mono truncate">
                    {STAGE_COPY[item.key].en}
                  </div>
                </div>
                <div className="h-7 rounded-md bg-bg-secondary border border-border overflow-hidden">
                  <div
                    className="h-full rounded-md"
                    style={{
                      width: `${width}%`,
                      backgroundColor: STAGE_COLORS[item.key],
                      minWidth: width > 0 ? 3 : 0,
                    }}
                    title={STAGE_COPY[item.key].plain}
                  />
                </div>
                <div className="text-right num text-text-secondary">
                  {item.row.sample_size > 0 ? `${item.row.p95.toFixed(0)}ms` : "—"}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function StageDonut({
  rows,
}: {
  rows: Array<{ key: PerfStageKey; share: number }>;
}) {
  const size = 112;
  const radius = 42;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;
  const segments = rows.filter((item) => item.share > 0);

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      className="shrink-0"
      aria-hidden
    >
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke="var(--color-bg-secondary)"
        strokeWidth="18"
      />
      {segments.map((item) => {
        const dash = item.share * circumference;
        const segment = (
          <circle
            key={item.key}
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke={STAGE_COLORS[item.key]}
            strokeWidth="18"
            strokeDasharray={`${dash} ${circumference - dash}`}
            strokeDashoffset={-offset}
            strokeLinecap="butt"
            transform={`rotate(-90 ${size / 2} ${size / 2})`}
          />
        );
        offset += dash;
        return segment;
      })}
      <text
        x="50%"
        y="47%"
        textAnchor="middle"
        className="fill-text-primary"
        style={{ fontSize: 18, fontWeight: 600 }}
      >
        P95
      </text>
      <text
        x="50%"
        y="62%"
        textAnchor="middle"
        className="fill-text-tertiary"
        style={{ fontSize: 10 }}
      >
        share
      </text>
    </svg>
  );
}
