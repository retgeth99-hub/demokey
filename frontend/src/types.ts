export type AnalysisState = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export interface AnalysisStatus {
  id: string;
  query_text: string;
  normalized_query: string;
  status: AnalysisState;
  phase: string | null;
  progress_percent: number;
  total_hit_count: number | null;
  sampled_publication_count: number;
  abstract_sample_count: number;
  query_translation: string | null;
  ai_status: string;
  error_code: string | null;
  error_detail: string | null;
  retryable: boolean;
  created_at: string;
  completed_at: string | null;
}

export interface AnalysisList {
  items: AnalysisStatus[];
  page: number;
  page_size: number;
  total: number;
}

export interface AnalysisAccepted {
  analysis_id: string;
  status: AnalysisState;
  cache_hit: boolean;
  status_url: string;
}

export interface Overview {
  analysis_id: string;
  query: string;
  query_translation: string | null;
  total_hit_count: number;
  sampled_publication_count: number;
  abstract_sample_count: number;
  retrieved_at: string | null;
  limitations: string[];
}

export interface TrendItem {
  year: number | null;
  count: number;
  ratio: number;
}

export interface Trends {
  analysis_id: string;
  sample_size: number;
  items: TrendItem[];
}

export interface RegionItem {
  country_code: string | null;
  country_name: string;
  count: number;
  ratio: number;
  average_confidence: number | null;
  is_unknown: boolean;
}

export interface Regions {
  analysis_id: string;
  method: string;
  method_note: string;
  items: RegionItem[];
}

export interface TopicItem {
  id: string;
  index: number;
  name: string;
  summary: string;
  publication_count: number;
  share: number;
  method: string;
  confidence: number | null;
  terms: string[];
  representative_pmids: number[];
}

export interface Topics {
  analysis_id: string;
  terms: Array<{ term: string; document_count: number; weighted_score: number }>;
  topics: TopicItem[];
}

export interface Publication {
  pmid: number;
  title: string;
  abstract: string | null;
  journal: string | null;
  publication_date: string | null;
  doi: string | null;
  rank: number | null;
  score: number | null;
  score_components: {
    components?: Record<string, number>;
    effective_weights?: Record<string, number>;
    missing_signals?: string[];
  };
  scoring_version: string | null;
}

export interface Publications {
  analysis_id: string;
  items: Publication[];
  page: number;
  page_size: number;
  total: number;
  disclaimer: string;
}

export interface ReportSection {
  key: string;
  heading: string;
  content: string;
  evidence_pmids: number[];
  evidence_status: string;
}

export interface Report {
  analysis_id: string;
  title: string;
  body_markdown: string;
  generation_mode: string;
  ai_status: string;
  model: string | null;
  sections: ReportSection[];
  limitations: string[];
  disclaimer: string;
}

export interface AnalysisResults {
  overview: Overview;
  trends: Trends;
  regions: Regions;
  topics: Topics;
  publications: Publications;
  report: Report;
}
