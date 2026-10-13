import type {
  AnalysisAccepted,
  AnalysisList,
  AnalysisResults,
  AnalysisStatus,
  Overview,
  Publications,
  Regions,
  Report,
  Topics,
  Trends,
} from "./types";

const API_ROOT = "/api/v1";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as
      | { detail?: { message?: string } | string }
      | null;
    const detail = payload?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : detail?.message ?? `请求失败（HTTP ${response.status}）`;
    throw new ApiError(message, response.status);
  }

  if (response.status === 204) return undefined as T;

  return response.json() as Promise<T>;
}

export async function checkHealth(): Promise<boolean> {
  const response = await fetch("/health/ready");
  return response.ok;
}

export function listAnalyses(): Promise<AnalysisList> {
  return request(`${API_ROOT}/analyses?page=1&page_size=12`);
}

export function getAnalysis(id: string): Promise<AnalysisStatus> {
  return request(`${API_ROOT}/analyses/${id}`);
}

export function createAnalysis(payload: {
  query: string;
  start_year?: number;
  end_year?: number;
  languages: string[];
  publication_types: string[];
  sort: "relevance" | "pub_date";
  metadata_limit: number;
  abstract_limit: number;
  report_evidence_limit: number;
}): Promise<AnalysisAccepted> {
  return request(`${API_ROOT}/analyses`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function cancelAnalysis(id: string): Promise<{ analysis_id: string; status: string }> {
  return request(`${API_ROOT}/analyses/${id}/cancel`, { method: "POST" });
}

export function retryAnalysis(id: string): Promise<{ analysis_id: string; status: string }> {
  return request(`${API_ROOT}/analyses/${id}/retry`, { method: "POST" });
}

export function deleteAnalysis(id: string): Promise<void> {
  return request(`${API_ROOT}/analyses/${id}`, { method: "DELETE" });
}

export async function getResults(id: string): Promise<AnalysisResults> {
  const [overview, trends, regions, topics, publications, report] = await Promise.all([
    request<Overview>(`${API_ROOT}/analyses/${id}/overview`),
    request<Trends>(`${API_ROOT}/analyses/${id}/trends`),
    request<Regions>(`${API_ROOT}/analyses/${id}/regions`),
    request<Topics>(`${API_ROOT}/analyses/${id}/topics`),
    request<Publications>(`${API_ROOT}/analyses/${id}/publications?page=1&page_size=100`),
    request<Report>(`${API_ROOT}/analyses/${id}/report`),
  ]);
  return { overview, trends, regions, topics, publications, report };
}
