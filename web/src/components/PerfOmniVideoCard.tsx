import type { AsyncState } from "@/hooks/useAsync";
import type { PerfOmniVideoSummary } from "@/lib/types";

interface Props {
  state: AsyncState<PerfOmniVideoSummary>;
}

type OmniVideoMode = NonNullable<PerfOmniVideoSummary["latest"]>["mode"];

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value >= 10 || unit === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[unit]}`;
}

function pct(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function modeCopy(mode: OmniVideoMode | undefined) {
  switch (mode) {
    case "remux":
      return {
        title: "正在复用摄像头原始视频包",
        badge: "省 CPU",
        tone: "text-success",
        desc: "这次上传只做转封装，不重新压缩画面。",
      };
    case "h265_reencode":
      return {
        title: "H.265 为保证回答质量正在重新编码",
        badge: "质量兜底",
        tone: "text-warning",
        desc: "当前摄像头是 H.265，直接转封装给 Omni 曾出现空回答，所以先回退到重新压缩。",
      };
    case "raw_not_remuxable":
      return {
        title: "原始视频包已拿到，但这次不能安全复用",
        badge: "缺关键帧",
        tone: "text-warning",
        desc: "同一次拉流的压缩包存在，但没有选出可从关键帧开始的片段，所以回退到重新压缩。",
      };
    case "reencode":
      return {
        title: "正在重新编码上传视频",
        badge: "吃 CPU",
        tone: "text-warning",
        desc: "上传前会把解码后的画面重新压成 MP4，本地 CPU 压力会更高。",
      };
    case "fallback":
      return {
        title: "原始包复用失败，已回退",
        badge: "回退",
        tone: "text-warning",
        desc: "可能缺关键帧、包格式不连续，或本次需要合入音频。",
      };
    default:
      return {
        title: "暂无上传视频样本",
        badge: "等待数据",
        tone: "text-text-tertiary",
        desc: "触发一次视觉理解后，这里会显示是否复用原始视频包。",
      };
  }
}

export function PerfOmniVideoCard({ state }: Props) {
  return (
    <section
      className="rounded-xl bg-bg-secondary border border-border shadow-sm p-5 md:p-6"
      aria-labelledby="perf-omni-video-title"
    >
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <h2 id="perf-omni-video-title" className="text-title">
            云端上传视频
          </h2>
          <p className="text-caption text-text-secondary mt-1">
            看 Miloco 上传给 Omni 前，是复用原始视频包，还是重新编码。
          </p>
        </div>
      </div>

      {state.loading && !state.data ? (
        <div className="py-8 text-center text-text-secondary">加载中...</div>
      ) : state.error ? (
        <div className="py-8 text-center text-error">{state.error.message}</div>
      ) : state.data ? (
        <OmniVideoContent data={state.data} />
      ) : null}
    </section>
  );
}

function OmniVideoContent({ data }: { data: PerfOmniVideoSummary }) {
  const latest = data.latest;
  const copy = modeCopy(latest?.mode);
  const reencodeWarn = data.reencode_count > data.remux_success_count;

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-border bg-bg-primary p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className={`text-section-title ${copy.tone}`}>{copy.title}</div>
            <div className="text-caption text-text-secondary mt-1 leading-relaxed">
              {copy.desc}
            </div>
            <div className="text-caption text-text-tertiary opacity-70 mono mt-2">
              latest mode: {latest?.mode ?? "none"}
            </div>
          </div>
          <span className={`shrink-0 text-caption font-medium ${copy.tone}`}>
            {copy.badge}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
        <Metric
          label="原始包复用率"
          hint="remux success rate"
          value={pct(data.remux_success_rate)}
          warn={false}
        />
        <Metric
          label="重新编码次数"
          hint="reencode count"
          value={data.reencode_count.toFixed(0)}
          warn={reencodeWarn}
        />
        <Metric
          label="P95 上传体积"
          hint="output bytes p95"
          value={formatBytes(data.output_bytes_p95)}
          warn={data.output_bytes_p95 > 3 * 1024 * 1024}
        />
        <Metric
          label="H.265 质量兜底"
          hint="h265 remux skipped"
          value={data.h265_remux_skipped_count.toFixed(0)}
          warn={data.h265_remux_skipped_count > 0}
        />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-caption">
        <Info label="样本数" sub="sample count" value={data.sample_count.toFixed(0)} />
        <Info
          label="最近上传体积"
          sub="latest output"
          value={formatBytes(latest?.output_bytes ?? 0)}
        />
        <Info
          label="最近原始包数量"
          sub="latest input packets"
          value={(latest?.input_packets ?? 0).toFixed(0)}
        />
        <Info
          label="窗口原始包"
          sub="raw packets in window"
          value={(latest?.raw_window_packets ?? 0).toFixed(0)}
        />
        <Info
          label="窗口关键帧"
          sub="raw keyframes"
          value={(latest?.raw_keyframes ?? 0).toFixed(0)}
        />
      </div>
    </div>
  );
}

function Metric({
  label,
  hint,
  value,
  warn,
}: {
  label: string;
  hint: string;
  value: string;
  warn: boolean;
}) {
  return (
    <div className="rounded-lg border border-border bg-bg-primary p-4 min-w-0">
      <div className="text-caption text-text-secondary">{label}</div>
      <div className="text-caption text-text-tertiary opacity-70 mono">{hint}</div>
      <div className={`text-2xl font-semibold num mt-2 ${warn ? "text-warning" : "text-text-primary"}`}>
        {value}
      </div>
    </div>
  );
}

function Info({
  label,
  sub,
  value,
}: {
  label: string;
  sub: string;
  value: string;
}) {
  return (
    <div className="rounded-lg border border-border bg-bg-primary px-4 py-3 flex items-center justify-between gap-3">
      <div className="min-w-0">
        <div className="text-text-primary truncate">{label}</div>
        <div className="text-text-tertiary opacity-70 mono truncate">{sub}</div>
      </div>
      <div className="num text-text-secondary shrink-0">{value}</div>
    </div>
  );
}
