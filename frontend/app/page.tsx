"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import {
  fetchInfo, buildDownloadUrl, buildThumbnailUrl,
  MediaInfo, Format,
} from "@/lib/api";

const PLATFORMS: Record<string, { label: string; color: string }> = {
  youtube:        { label: "YouTube",         color: "#FF4444" },
  youtube_short:  { label: "YouTube Short",   color: "#FF4444" },
  instagram:      { label: "Instagram Reels", color: "#E1306C" },
  instagram_post: { label: "Instagram Post",  color: "#E1306C" },
  tiktok:         { label: "TikTok",          color: "#69C9D0" },
  twitch:         { label: "Twitch",          color: "#9146FF" },
  twitch_clip:    { label: "Twitch Clip",     color: "#9146FF" },
  twitch_vod:     { label: "Twitch VOD",      color: "#9146FF" },
};

const PILLS = [
  { label: "YouTube Videos",  color: "#FF4444" },
  { label: "YouTube Shorts",  color: "#FF4444" },
  { label: "Instagram Reels", color: "#E1306C" },
  { label: "Instagram Posts", color: "#E1306C" },
  { label: "TikTok",          color: "#69C9D0" },
  { label: "Twitch Clips",    color: "#9146FF" },
  { label: "Twitch VODs",     color: "#9146FF" },
];

type ItemStatus = "fetching" | "ready" | "downloading" | "done" | "error";

interface QueueItem {
  id: string;
  url: string;
  status: ItemStatus;
  media: MediaInfo | null;
  selectedFormat: string;
  error: string | null;
  progress: number;
  speed: number;
  downloadedBytes: number;
  totalBytes: number;
}

function fmtBytes(b: number): string {
  if (b <= 0) return "—";
  if (b < 1024) return `${b} B`;
  if (b < 1048576) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / 1048576).toFixed(1)} MB`;
}

function fmtSpeed(bps: number): string {
  if (bps < 512) return "";
  if (bps < 1048576) return `${(bps / 1024).toFixed(0)} KB/s`;
  return `${(bps / 1048576).toFixed(1)} MB/s`;
}

function safeHost(url: string): string {
  try { return new URL(url).hostname; } catch { return url.slice(0, 40); }
}

const GLOBAL_CSS = `
  @keyframes rpl-slide {
    from { opacity: 0; transform: translateY(-8px); }
    to   { opacity: 1; transform: translateY(0); }
  }
  @keyframes rpl-pulse {
    0%, 100% { opacity: 0.2; }
    50%       { opacity: 0.55; }
  }
  @keyframes rpl-spin {
    to { transform: rotate(360deg); }
  }
  @keyframes rpl-shimmer {
    0%   { background-position: -200% 0; }
    100% { background-position:  200% 0; }
  }
  @keyframes rpl-scan {
    0%   { transform: translateX(-100%); }
    100% { transform: translateX(500%); }
  }
  .rpl-item    { animation: rpl-slide 0.22s cubic-bezier(0.22,1,0.36,1); }
  .rpl-pulse   { animation: rpl-pulse 1.5s ease-in-out infinite; }
  .rpl-indeterminate { position: relative; overflow: hidden; }
  .rpl-indeterminate::after {
    content: ''; position: absolute; top: 0; bottom: 0; left: 0;
    width: 20%;
    background: linear-gradient(90deg, transparent, #E11B22 50%, transparent);
    animation: rpl-scan 1.4s ease-in-out infinite;
  }
  .rpl-spinner {
    width: 13px; height: 13px; border-radius: 50%;
    border: 2px solid #252525; border-top-color: #E11B22;
    animation: rpl-spin 0.7s linear infinite;
    flex-shrink: 0;
  }
  .rpl-bar {
    background: linear-gradient(90deg, #c0151b 20%, #E11B22 40%, #ff6060 55%, #E11B22 70%, #c0151b 90%);
    background-size: 200% 100%;
    animation: rpl-shimmer 1.4s linear infinite;
  }
  .rpl-rm { color: #252525; transition: color 0.15s; border: none; cursor: pointer; background: none; padding: 3px 5px; font-size: 13px; }
  .rpl-rm:hover { color: #666; }
  .rpl-pill { cursor: pointer; transition: border-color 0.12s, background 0.12s, color 0.12s; }
  .rpl-pill:hover { opacity: 0.8; }
  .rpl-btn-dl:hover { filter: brightness(1.08); transform: translateY(-1px); }
  .rpl-btn-stop:hover { border-color: #E11B22 !important; color: #E11B22 !important; }
  .rpl-link { color: #555; text-decoration: none; border-bottom: 1px solid #2a2a2a; padding-bottom: 1px; }
  .rpl-link:hover { color: #888; border-bottom-color: #666; }
`;

/* ── Error display ───────────────────────────────────────────────────── */

function ErrorCard({ item, onRetry }: { item: QueueItem; onRetry: () => void }) {
  return (
    <div>
      <p style={{ fontSize: 12, color: "#ef4444", margin: "0 0 5px", lineHeight: 1.4 }}>
        {item.error ?? "Failed"}
      </p>
      <p style={{ fontSize: 10, color: "#2a2a2a", margin: "0 0 6px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {safeHost(item.url)}
      </p>
      <button onClick={onRetry} style={{ fontSize: 11, color: "#555", background: "none", border: "none", cursor: "pointer", padding: 0, textDecoration: "underline", textUnderlineOffset: 2 }}>
        ↺ retry
      </button>
    </div>
  );
}

/* ── Queue item card ─────────────────────────────────────────────────── */

interface CardProps {
  item: QueueItem;
  isRunning: boolean;
  onRemove: () => void;
  onFormatChange: (id: string) => void;
  onRetry: () => void;
}

function QueueCard({ item, isRunning, onRemove, onFormatChange, onRetry }: CardProps) {
  const plat   = PLATFORMS[item.media?.platform ?? ""] ?? { label: item.media?.platform ?? "", color: "#777" };
  const isDone  = item.status === "done";
  const isDl    = item.status === "downloading";
  const isErr   = item.status === "error";
  const isRdy   = item.status === "ready";
  const isFetch = item.status === "fetching";

  const cardBorder = isDl   ? "1px solid rgba(225,27,34,0.22)"
                   : isDone ? "1px solid rgba(34,197,94,0.14)"
                   : isErr  ? "1px solid rgba(239,68,68,0.22)"
                   :           "1px solid #1c1c1c";
  const cardBg = isDl ? "rgba(225,27,34,0.022)" : "#0f0f0f";

  return (
    <div
      className="rpl-item"
      style={{
        borderRadius: 14, border: cardBorder, background: cardBg,
        overflow: "hidden", transition: "border-color 0.3s, background 0.3s, opacity 0.3s",
        opacity: isDone ? 0.68 : 1,
      }}
    >
      {/* Main row */}
      <div style={{ display: "flex", gap: 12, padding: "13px 14px", alignItems: "flex-start" }}>

        {/* Thumbnail */}
        <div style={{
          width: 72, height: 46, flexShrink: 0, borderRadius: 8,
          overflow: "hidden", background: "#191919", position: "relative",
        }}>
          {item.media?.thumbnail ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={buildThumbnailUrl(item.media.thumbnail, item.media.platform)}
              alt=""
              style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
            />
          ) : (
            <div
              className={isFetch ? "rpl-pulse" : ""}
              style={{ width: "100%", height: "100%", background: "#1e1e1e" }}
            />
          )}
          {isDone && (
            <div style={{
              position: "absolute", inset: 0, background: "rgba(34,197,94,0.52)",
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 16, fontWeight: 700, color: "#fff",
            }}>✓</div>
          )}
          {isErr && (
            <div style={{
              position: "absolute", inset: 0, background: "rgba(239,68,68,0.45)",
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 15, fontWeight: 700, color: "#fff",
            }}>!</div>
          )}
        </div>

        {/* Content */}
        <div style={{ flex: 1, minWidth: 0 }}>

          {/* Fetching skeleton */}
          {isFetch && (
            <div>
              <div className="rpl-pulse" style={{ height: 11, background: "#1e1e1e", borderRadius: 4, width: "52%", marginBottom: 7 }} />
              <div className="rpl-pulse" style={{ height: 9,  background: "#191919", borderRadius: 4, width: "32%" }} />
              <p style={{ fontSize: 10, color: "#2a2a2a", margin: "6px 0 0", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {safeHost(item.url)}
              </p>
            </div>
          )}

          {/* Error state */}
          {isErr && <ErrorCard item={item} onRetry={onRetry} />}

          {/* Ready / downloading / done */}
          {!isFetch && !isErr && item.media && (
            <div>
              {/* Platform badge + live status */}
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4, flexWrap: "wrap" }}>
                <span style={{
                  fontSize: 9, fontWeight: 700, padding: "2px 7px", borderRadius: 5, flexShrink: 0,
                  background: `${plat.color}18`, color: plat.color, border: `1px solid ${plat.color}30`,
                }}>
                  {plat.label}
                </span>
                {isDl && (
                  <span style={{ fontSize: 10, color: "#888", fontVariantNumeric: "tabular-nums" }}>
                    {item.progress > 0 ? `${item.progress.toFixed(0)}%` : item.downloadedBytes > 0 ? "Downloading…" : "Starting…"}
                    {item.speed > 512 ? ` · ${fmtSpeed(item.speed)}` : ""}
                  </span>
                )}
                {isDone && (
                  <span style={{ fontSize: 10, color: "#22c55e" }}>
                    ✓ {item.downloadedBytes > 0 ? fmtBytes(item.downloadedBytes) : "saved"}
                  </span>
                )}
              </div>

              {/* Title */}
              <p style={{
                fontSize: 12, fontWeight: 500,
                color: isDone ? "#363636" : "#bcbcbc",
                margin: "0 0 1px",
                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
              }}>
                {item.media.title || safeHost(item.url)}
              </p>

              {/* Format label (downloading / done) */}
              {(isDl || isDone) && (
                <p style={{ fontSize: 10, color: "#2e2e2e", margin: 0 }}>
                  {item.media.formats.find((f: Format) => f.id === item.selectedFormat)?.label ?? ""}
                </p>
              )}

              {/* Format pills (ready only) */}
              {isRdy && (
                <div style={{ marginTop: 9, display: "flex", gap: 5, flexWrap: "wrap" }}>
                  {item.media.formats.map((fmt: Format) => {
                    const active = fmt.id === item.selectedFormat;
                    return (
                      <button
                        key={fmt.id}
                        className="rpl-pill"
                        onClick={() => onFormatChange(fmt.id)}
                        style={{
                          fontSize: 11, fontWeight: 600, padding: "3px 9px", borderRadius: 6,
                          border: `1px solid ${active ? "#E11B22" : "#242424"}`,
                          background: active ? "rgba(225,27,34,0.13)" : "#141414",
                          color: active ? "#f0f0f0" : "#484848",
                        }}
                      >
                        {fmt.label}
                        {fmt.filesize ? ` · ${fmtBytes(fmt.filesize)}` : ""}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Right: spinner or remove */}
        <div style={{ flexShrink: 0, paddingTop: 2 }}>
          {isDl
            ? <div className="rpl-spinner" />
            : !isRunning && <button className="rpl-rm" onClick={onRemove} title="Remove">✕</button>
          }
        </div>
      </div>

      {/* Progress bar (downloading) */}
      {isDl && (
        <>
          <div
            className={item.progress === 0 && item.downloadedBytes > 0 ? "rpl-indeterminate" : ""}
            style={{ height: 2, background: "#161616" }}
          >
            {(item.progress > 0 || item.downloadedBytes === 0) && (
              <div
                className={item.progress > 2 ? "rpl-bar" : ""}
                style={{
                  height: "100%",
                  width: item.progress > 0 ? `${item.progress}%` : "8%",
                  background: item.progress > 0 ? undefined : "#252525",
                  transition: "width 0.3s ease",
                }}
              />
            )}
          </div>
          <div style={{
            display: "flex", justifyContent: "space-between",
            padding: "5px 14px 10px",
            fontSize: 10, color: "#303030", fontVariantNumeric: "tabular-nums",
          }}>
            <span>
              {item.downloadedBytes > 0 ? fmtBytes(item.downloadedBytes) : ""}
              {item.totalBytes > 0 ? ` / ${fmtBytes(item.totalBytes)}` : ""}
            </span>
            <span>{fmtSpeed(item.speed)}</span>
          </div>
        </>
      )}
    </div>
  );
}

/* ── Main page ──────────────────────────────────────────────────────── */

export default function Home() {
  const [inputUrl, setInputUrl]   = useState("");
  const [items, setItems]         = useState<QueueItem[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const updateItem = useCallback((id: string, patch: Partial<QueueItem>) => {
    setItems(prev => prev.map(it => it.id === id ? { ...it, ...patch } : it));
  }, []);

  async function addUrl() {
    const url = inputUrl.trim();
    if (!url) return;
    setInputUrl("");
    setTimeout(() => inputRef.current?.focus(), 50);

    const id = crypto.randomUUID();
    setItems(prev => [...prev, {
      id, url, status: "fetching", media: null, selectedFormat: "",
      error: null, progress: 0, speed: 0, downloadedBytes: 0, totalBytes: 0,
    }]);

    try {
      const info = await fetchInfo(url);
      setItems(prev => prev.map(it => it.id === id ? {
        ...it, status: "ready", media: info,
        selectedFormat: info.formats[0]?.id ?? "",
      } : it));
    } catch (e) {
      setItems(prev => prev.map(it => it.id === id ? {
        ...it, status: "error",
        error: e instanceof Error ? e.message : "Failed to fetch info",
      } : it));
    }
  }

  async function retryItem(id: string) {
    const item = items.find(it => it.id === id);
    if (!item) return;
    if (item.media) {
      updateItem(id, { status: "ready", error: null, progress: 0 });
      return;
    }
    updateItem(id, { status: "fetching", error: null });
    try {
      const info = await fetchInfo(item.url);
      setItems(prev => prev.map(it => it.id === id ? {
        ...it, status: "ready", media: info, selectedFormat: info.formats[0]?.id ?? "",
      } : it));
    } catch (e) {
      setItems(prev => prev.map(it => it.id === id ? {
        ...it, status: "error", error: e instanceof Error ? e.message : "Failed",
      } : it));
    }
  }

  async function downloadOne(item: QueueItem, signal: AbortSignal): Promise<void> {
    updateItem(item.id, { status: "downloading", progress: 0, speed: 0, downloadedBytes: 0 });

    const response = await fetch(buildDownloadUrl(item.url, item.selectedFormat), { signal });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    if (!response.body) throw new Error("No response body");

    const knownSize = item.media?.formats.find(f => f.id === item.selectedFormat)?.filesize ?? 0;
    const contentLength = parseInt(response.headers.get("content-length") || "0") || knownSize;
    const reader = response.body.getReader();
    const chunks: Uint8Array[] = [];
    let received = 0;
    let lastTime = Date.now();
    let lastBytes = 0;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (signal.aborted) {
        reader.cancel();
        throw new DOMException("Aborted", "AbortError");
      }
      chunks.push(value);
      received += value.length;

      const now = Date.now();
      const elapsed = (now - lastTime) / 1000;
      if (elapsed >= 0.25) {
        updateItem(item.id, {
          progress: contentLength ? Math.min(99, (received / contentLength) * 100) : 0,
          speed: (received - lastBytes) / elapsed,
          downloadedBytes: received,
          totalBytes: contentLength,
        });
        lastTime = now;
        lastBytes = received;
      }
    }

    const fmt = item.media!.formats.find((f: Format) => f.id === item.selectedFormat)!;
    const mime = fmt.ext === "mp3" ? "audio/mpeg" : fmt.ext === "jpg" ? "image/jpeg" : "video/mp4";
    const blob = new Blob(chunks as BlobPart[], { type: mime });
    const blobUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = blobUrl;
    const safe = (item.media!.title || "download")
      .replace(/[^\w\s\-]/g, "").trim().replace(/\s+/g, "_").slice(0, 80) || "download";
    a.download = `${safe}.${fmt.ext}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(blobUrl), 4000);

    updateItem(item.id, { status: "done", progress: 100, downloadedBytes: received, totalBytes: received });
  }

  async function startQueue() {
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setIsRunning(true);

    const toDownload = items.filter(it => it.status === "ready" || it.status === "error");

    for (const item of toDownload) {
      if (ctrl.signal.aborted) break;
      if (item.status === "error" && !item.media) continue; // can't download without info
      try {
        await downloadOne(item, ctrl.signal);
      } catch (e) {
        if (ctrl.signal.aborted) {
          updateItem(item.id, { status: "ready", progress: 0, speed: 0 });
          break;
        }
        updateItem(item.id, {
          status: "error",
          error: e instanceof Error ? e.message : "Download failed",
        });
      }
    }

    setIsRunning(false);
  }

  function stopQueue() {
    abortRef.current?.abort();
  }

  const readyCount       = items.filter(it => it.status === "ready").length;
  const doneCount        = items.filter(it => it.status === "done").length;
  const totalDownloaded  = items.filter(it => it.status === "done").reduce((s, it) => s + it.downloadedBytes, 0);
  const estimatedPending = items
    .filter(it => it.status === "ready" && it.media)
    .reduce((s, it) => {
      const fmt = it.media!.formats.find((f: Format) => f.id === it.selectedFormat);
      return s + (fmt?.filesize ?? 0);
    }, 0);

  const hasItems = items.length > 0;

  return (
    <main style={{
      minHeight: "100vh",
      display: "flex", flexDirection: "column",
      alignItems: "center",
      justifyContent: hasItems ? "flex-start" : "center",
      padding: hasItems ? "60px 24px 80px" : "0 24px",
      transition: "padding 0.3s ease",
    }}>
      <style>{GLOBAL_CSS}</style>

      <div style={{
        width: "100%", maxWidth: 620,
        display: "flex", flexDirection: "column", alignItems: "center",
      }}>

        {/* ── Logo ── */}
        <div style={{ textAlign: "center", marginBottom: 36 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 14, marginBottom: 14 }}>
            <svg width="40" height="40" viewBox="0 0 40 40" fill="none">
              <circle cx="20" cy="20" r="18" stroke="#E11B22" strokeWidth="1.5" strokeDasharray="3 4" opacity="0.35"/>
              <circle cx="20" cy="20" r="11" stroke="#E11B22" strokeWidth="1.5" opacity="0.6"/>
              <circle cx="20" cy="20" r="5" fill="#E11B22"/>
            </svg>
            <h1 style={{
              fontSize: "clamp(3rem, 9vw, 5rem)", fontWeight: 900,
              color: "#ffffff", letterSpacing: "-0.04em", lineHeight: 1,
            }}>RIPPLE</h1>
          </div>
          <p style={{ color: "#555", fontSize: 14, letterSpacing: "0.01em" }}>
            Video &amp; audio downloader — no accounts, no limits
          </p>
        </div>

        {/* ── Platform pills ── */}
        <div style={{ display: "flex", gap: 7, flexWrap: "wrap", justifyContent: "center", marginBottom: 36 }}>
          {PILLS.map(p => (
            <span key={p.label} style={{
              display: "inline-flex", alignItems: "center",
              padding: "5px 13px", borderRadius: 999, fontSize: 12, fontWeight: 600,
              background: `${p.color}18`, color: p.color, border: `1px solid ${p.color}30`,
            }}>
              {p.label}
            </span>
          ))}
        </div>

        {/* ── URL input ── */}
        <div style={{
          width: "100%", marginBottom: 10,
          borderRadius: 16, padding: 1,
          background: "linear-gradient(135deg, #E11B2248, #2a080830)",
          border: "1px solid #E11B2222",
        }}>
          <div style={{
            borderRadius: 15, padding: "14px 18px",
            display: "flex", alignItems: "center", gap: 12,
            background: "#111",
          }}>
            <svg width="15" height="15" viewBox="0 0 16 16" fill="none" style={{ flexShrink: 0, opacity: 0.35 }}>
              <path d="M6.5 1.5L2 6l4.5 4.5M9.5 14.5L14 10l-4.5-4.5M9.5 1.5l-3 13"
                    stroke="#fff" strokeWidth="1.4" strokeLinecap="round"/>
            </svg>
            <input
              ref={inputRef}
              type="text"
              value={inputUrl}
              onChange={e => setInputUrl(e.target.value)}
              onKeyDown={e => e.key === "Enter" && addUrl()}
              placeholder="Paste a YouTube, TikTok, Instagram, or Twitch URL…"
              autoFocus spellCheck={false}
              style={{
                flex: 1, background: "transparent", outline: "none", border: "none",
                fontSize: 14, color: "#f0f0f0",
              }}
            />
            {inputUrl && (
              <button
                onClick={() => setInputUrl("")}
                style={{ background: "none", border: "none", cursor: "pointer", color: "#444", fontSize: 13, padding: "2px 4px" }}
              >✕</button>
            )}
          </div>
        </div>

        {/* ── Add button ── */}
        <button
          onClick={addUrl}
          disabled={!inputUrl.trim()}
          className={inputUrl.trim() ? "rpl-btn-dl" : ""}
          style={{
            width: "100%", padding: "14px 0", borderRadius: 13, border: "none",
            cursor: inputUrl.trim() ? "pointer" : "default",
            fontSize: 12, fontWeight: 700, letterSpacing: "0.15em", color: "#fff",
            marginBottom: hasItems ? 28 : 0,
            background: "linear-gradient(135deg, #E11B22, #c0151b)",
            boxShadow: inputUrl.trim() ? "0 6px 24px rgba(225,27,34,0.32)" : "none",
            opacity: inputUrl.trim() ? 1 : 0.3,
            transition: "opacity 0.2s, box-shadow 0.2s, transform 0.15s",
          }}
        >
          + ADD TO QUEUE
        </button>

        {/* ── Download queue ── */}
        {hasItems && (
          <div style={{ width: "100%" }}>

            {/* Queue header */}
            <div style={{
              display: "flex", justifyContent: "space-between", alignItems: "center",
              marginBottom: 12,
            }}>
              <span style={{
                fontSize: 9, fontWeight: 700, letterSpacing: "0.22em",
                color: "#303030", textTransform: "uppercase",
              }}>
                Queue · {items.length} {items.length === 1 ? "item" : "items"}
                {doneCount > 0 && (
                  <span style={{ color: "#22c55e40", marginLeft: 6 }}>· {doneCount} done</span>
                )}
              </span>
              {doneCount > 0 && !isRunning && (
                <button
                  onClick={() => setItems(prev => prev.filter(it => it.status !== "done"))}
                  style={{ background: "none", border: "none", cursor: "pointer", fontSize: 11, color: "#2e2e2e", padding: 0, transition: "color 0.15s" }}
                >
                  clear done
                </button>
              )}
            </div>

            {/* Queue items */}
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {items.map(item => (
                <QueueCard
                  key={item.id}
                  item={item}
                  isRunning={isRunning}
                  onRemove={() => setItems(prev => prev.filter(it => it.id !== item.id))}
                  onFormatChange={fmtId => updateItem(item.id, { selectedFormat: fmtId })}
                  onRetry={() => retryItem(item.id)}
                />
              ))}
            </div>

            {/* Action row */}
            <div style={{ marginTop: 18, display: "flex", gap: 10 }}>
              {isRunning ? (
                <button
                  className="rpl-btn-stop"
                  onClick={stopQueue}
                  style={{
                    flex: 1, padding: "14px 0", borderRadius: 12,
                    border: "1px solid #2a2a2a", cursor: "pointer",
                    fontSize: 12, fontWeight: 700, letterSpacing: "0.15em",
                    color: "#555", background: "#0d0d0d", transition: "all 0.15s",
                  }}
                >
                  ■ STOP
                </button>
              ) : readyCount > 0 ? (
                <button
                  className="rpl-btn-dl"
                  onClick={startQueue}
                  style={{
                    flex: 1, padding: "14px 0", borderRadius: 12, border: "none",
                    cursor: "pointer", fontSize: 12, fontWeight: 700, letterSpacing: "0.15em",
                    color: "#fff", background: "linear-gradient(135deg, #E11B22, #c0151b)",
                    boxShadow: "0 6px 28px rgba(225,27,34,0.32)",
                    transition: "filter 0.15s, transform 0.15s",
                  }}
                >
                  ↓ DOWNLOAD ALL ({readyCount})
                </button>
              ) : null}

              {doneCount > 0 && !isRunning && readyCount === 0 && items.every(it => it.status === "done" || it.status === "error") && (
                <button
                  onClick={() => setItems([])}
                  style={{
                    flex: 1, padding: "14px 0", borderRadius: 12,
                    border: "1px solid #1c1c1c", cursor: "pointer",
                    fontSize: 12, fontWeight: 700, letterSpacing: "0.15em",
                    color: "#2e2e2e", background: "#0a0a0a", transition: "all 0.15s",
                  }}
                >
                  CLEAR QUEUE
                </button>
              )}
            </div>

            {/* Stats footer */}
            <div style={{ marginTop: 10, textAlign: "center", minHeight: 16 }}>
              {isRunning && (
                <p style={{ fontSize: 10, color: "#2a2a2a", margin: 0 }}>
                  Downloading one at a time — each file saves to your downloads folder
                </p>
              )}
              {!isRunning && doneCount > 0 && totalDownloaded > 0 && (
                <p style={{ fontSize: 10, color: "#282828", margin: 0 }}>
                  {doneCount} {doneCount === 1 ? "file" : "files"} saved · {fmtBytes(totalDownloaded)} total
                </p>
              )}
              {!isRunning && estimatedPending > 0 && readyCount > 0 && (
                <p style={{ fontSize: 10, color: "#282828", margin: "4px 0 0" }}>
                  ~{fmtBytes(estimatedPending)} estimated
                </p>
              )}
            </div>
          </div>
        )}

        {/* ── Footer ── */}
        <div style={{ marginTop: hasItems ? 52 : 48, textAlign: "center" }}>
          <p style={{ fontSize: 11, color: "#333" }}>
            For personal use only · Respect content creators and platform terms
          </p>
          <p style={{ marginTop: 8, fontSize: 11, color: "#282828" }}>
            © {new Date().getFullYear()}{" "}
            <a
              href="https://annas.host"
              target="_blank"
              rel="noopener noreferrer"
              className="rpl-link"
            >
              Anas Ben Ahmed
            </a>
          </p>
        </div>

      </div>
    </main>
  );
}
