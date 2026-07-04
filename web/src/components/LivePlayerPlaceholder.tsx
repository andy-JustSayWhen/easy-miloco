/**
 * Hero 摄像头画面组件。
 *
 * 低配 NAS 默认走 snapshot(快照,最近一张感知画面),避免首屏或放大预览为
 * 了一个展示画面常驻 H.264/H.265 直播转码。
 */

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { createPortal } from "react-dom";
import { IconCamera, IconX } from "@/lib/icons";
import { useEscClose } from "@/hooks/useEscClose";
import { cameraSnapshotUrl } from "@/api";

interface Props {
  cameraName: string;
  roomName?: string;
  cameraDid: string;
  channel: number;
  className?: string;
  disabled?: boolean;
  disabledMessage?: string;
  dimmed?: boolean;
  dimmedMessage?: string;
}

export function LivePlayerPlaceholder({
  cameraName,
  roomName,
  cameraDid,
  channel,
  className,
  disabled = false,
  disabledMessage,
  dimmed = false,
  dimmedMessage,
}: Props) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const [smallLoaded, setSmallLoaded] = useState(false);
  const [snapshotTick, setSnapshotTick] = useState(() => Date.now());

  useEscClose(expanded, () => setExpanded(false));

  const refKey = `${cameraDid}|${channel}`;
  const snapshotSrc = useMemo(
    () =>
      cameraSnapshotUrl(cameraDid, {
        maxWidth: expanded ? 1280 : 640,
        quality: expanded ? 76 : 72,
        ts: snapshotTick,
      }),
    [cameraDid, expanded, snapshotTick],
  );

  // refKey 变(cam 或 channel 切换)时重置 loading mask,让"等待画面"再显一次盖
  // 旧画面到新首帧之间的空隙。预览走轻量 snapshot,避免常驻 H.264 转码流。
  useEffect(() => {
    setSmallLoaded(false);
    setSnapshotTick(Date.now());
  }, [refKey]);

  useEffect(() => {
    if (disabled) return;
    const id = window.setInterval(() => {
      setSnapshotTick(Date.now());
    }, 2000);
    return () => window.clearInterval(id);
  }, [disabled, refKey]);

  // expanded 期间锁 body 滚动
  useEffect(() => {
    if (!expanded) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [expanded]);

  const handleOpen = () => {
    if (disabled) return;
    setSmallLoaded(false);
    setSnapshotTick(Date.now());
    setExpanded(true);
  };

  return (
    <>
      <div
        role="button"
        tabIndex={disabled ? -1 : 0}
        aria-disabled={disabled}
        aria-label={t("devices.watchCamera", { name: cameraName })}
        onClick={handleOpen}
        onKeyDown={(e) => {
          if (disabled) return;
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            setExpanded(true);
          }
        }}
        className={`relative aspect-video w-full overflow-hidden rounded-xl border border-border shadow-sm focus:outline-none focus:ring-2 focus:ring-brand-primary bg-black ${
          disabled ? "cursor-default opacity-60" : "cursor-pointer"
        } ${className ?? ""}`}
      >
        {disabled ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-white/70 pointer-events-none">
            <IconCamera width={36} height={36} />
            <div className="mt-2 text-body opacity-90">{cameraName}</div>
            {disabledMessage && (
              <div className="text-caption opacity-60">{disabledMessage}</div>
            )}
          </div>
        ) : (
          <>
            <img
              src={snapshotSrc}
              alt=""
              aria-hidden="true"
              className="absolute inset-0 w-full h-full object-cover"
              draggable={false}
              onLoad={() => setSmallLoaded(true)}
              onError={() => setSmallLoaded(false)}
            />
            {!smallLoaded && (
              <div className="absolute inset-0 flex items-center justify-center text-text-tertiary text-caption pointer-events-none">
                {t("devices.loadingSnapshot")}
              </div>
            )}
            {dimmed && smallLoaded && dimmedMessage && (
              <div className="absolute inset-0 flex items-end justify-center bg-black/30 pointer-events-none">
                <div className="mb-3 px-2 py-1 rounded-md bg-black/60 text-white/90 text-caption">
                  {dimmedMessage}
                </div>
              </div>
            )}
          </>
        )}

        {roomName && (
          <div className="absolute left-3 bottom-3 px-2 py-1 rounded-md bg-black/40 text-white text-caption pointer-events-none z-10">
            {roomName}
          </div>
        )}
        {!disabled && (
          <div className="absolute right-3 bottom-3 inline-flex items-center gap-1.5 px-2 py-1 rounded-md bg-black/40 text-white text-caption pointer-events-none z-10">
            <span className="w-1.5 h-1.5 rounded-full bg-success animate-pulse"></span>
            {t("devices.snapshotBadge")}
          </div>
        )}
      </div>

      {expanded &&
        createPortal(
          <div
            className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40"
            onClick={() => setExpanded(false)}
          >
            <div
              role="dialog"
              aria-modal="true"
              aria-label={t("devices.liveView", { name: cameraName })}
              className="w-full max-w-4xl max-h-[90vh] bg-bg-secondary rounded-xl border border-border shadow-sm overflow-hidden flex flex-col anim-in"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center gap-3 px-4 py-2 border-b border-border bg-bg-secondary min-w-0">
                <div className="text-title text-text-primary truncate">
                  {cameraName}
                  {roomName && (
                    <span className="text-caption text-text-secondary font-normal ml-2">
                      · {roomName}
                    </span>
                  )}
                </div>
                {dimmed && dimmedMessage && (
                  <span className="text-caption inline-flex items-center px-2 py-0.5 rounded-full bg-warning-bg text-warning shrink-0">
                    {dimmedMessage}
                  </span>
                )}
                <button
                  type="button"
                  onClick={() => setExpanded(false)}
                  className="ml-auto rounded-full p-1.5 text-text-secondary hover:text-text-primary hover:bg-bg-primary"
                  aria-label={t("devices.close")}
                >
                  <IconX />
                </button>
              </div>
              <div className="relative aspect-video w-full flex-1 min-h-0 bg-black">
                <img
                  src={snapshotSrc}
                  alt=""
                  aria-hidden="true"
                  className="absolute inset-0 w-full h-full object-contain"
                  draggable={false}
                  onLoad={() => setSmallLoaded(true)}
                  onError={() => setSmallLoaded(false)}
                />
                {!smallLoaded && (
                  <div className="absolute inset-0 flex items-center justify-center text-text-tertiary text-caption pointer-events-none">
                    {t("devices.loadingSnapshot")}
                  </div>
                )}
              </div>
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}
