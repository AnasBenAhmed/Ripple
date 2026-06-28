const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface Format {
  id: string;
  label: string;
  ext: string;
  thumbnail?: string | null;
  filesize?: number | null;
}

export interface MediaInfo {
  title: string;
  thumbnail: string;
  platform: string;
  formats: Format[];
  duration?: number | null;
}

export async function fetchInfo(url: string): Promise<MediaInfo> {
  const res = await fetch(`${BASE}/api/info`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(err.detail ?? "Failed to fetch media info");
  }
  return res.json();
}

export function buildDownloadUrl(url: string, formatId: string): string {
  const params = new URLSearchParams({ url, format_id: formatId });
  return `${BASE}/api/download?${params}`;
}

export function buildThumbnailUrl(thumbnail: string, platform: string): string {
  // Instagram blocks direct image loads — proxy through backend
  if ((platform === "instagram" || platform === "instagram_post") && thumbnail) {
    return `${BASE}/api/thumbnail?url=${encodeURIComponent(thumbnail)}`;
  }
  return thumbnail;
}
