import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowSquareOutIcon,
  CheckCircleIcon,
  ClockIcon,
  DatabaseIcon,
  MagnifyingGlassIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react";

import {
  cancelAnalysis,
  checkHealth,
  createAnalysis,
  deleteAnalysis,
  getAnalysis,
  getResults,
  listAnalyses,
  retryAnalysis,
} from "./api";
import type { AnalysisResults, AnalysisState, AnalysisStatus, RegionItem, TrendItem } from "./types";

const phaseLabels: Record<string, string> = {
  queued: "等待处理",
  searching: "检索 PubMed",
  fetching_metadata: "获取文献详情",
  enriching_citations: "补充引用信息",
  aggregating: "统计与主题分析",
  generating_report: "生成中文报告",
  finalizing: "整理结果",
  completed: "分析完成",
};

const flow = ["检索文献", "获取详情", "统计分析", "生成报告", "完成"];

const scoreLabels: Record<string, string> = {
  relevance: "检索相关度",
  citation: "可见引用",
  recency: "发表时间",
  publication_type: "文献类型",
  mesh_match: "MeSH 匹配",
};

function formatNumber(value: number | null | undefined): string {
  return new Intl.NumberFormat("zh-CN").format(value ?? 0);
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function currentStep(phase: string | null): number {
  if (!phase || phase === "queued") return 0;
  if (phase === "searching") return 0;
  if (phase === "fetching_metadata" || phase === "enriching_citations") return 1;
  if (phase === "aggregating") return 2;
  if (phase === "generating_report") return 3;
  return 4;
}

function TrendChart({ items }: { items: TrendItem[] }) {
  const max = Math.max(...items.map((item) => item.count), 1);
  return (
    <div className="trend-chart" aria-label="年度文献趋势">
      {items.map((item) => (
        <div className="trend-column" key={item.year ?? "unknown"}>
          <span className="trend-value">{item.count}</span>
          <div className="trend-track">
            <div className="trend-bar" style={{ height: `${Math.max((item.count / max) * 100, 4)}%` }} />
          </div>
          <span className="trend-year">{item.year ?? "未知"}</span>
        </div>
      ))}
    </div>
  );
}

function RegionBars({ items }: { items: RegionItem[] }) {
  const visible = items.slice(0, 6);
  const max = Math.max(...visible.map((item) => item.count), 1);
  return (
    <div className="region-list">
      {visible.map((item) => (
        <div className="region-row" key={item.country_code ?? item.country_name}>
          <span>{item.country_name}</span>
          <div className="region-track">
            <div className="region-fill" style={{ width: `${(item.count / max) * 100}%` }} />
          </div>
          <strong>{item.count}</strong>
        </div>
      ))}
    </div>
  );
}

function TopicChart({ data }: { data: AnalysisResults["topics"] }) {
  const maxCount = Math.max(...data.topics.map((topic) => topic.publication_count), 1);
  const maxWeight = Math.max(...data.terms.map((term) => term.weighted_score), 1);
  return (
    <>
      <div className="topic-chart" aria-label="研究方向文献数量">
        {data.topics.map((topic) => (
          <div className="topic-chart-row" key={topic.id}>
            <span>{String(topic.index).padStart(2, "0")}</span>
            <div>
              <div className="topic-chart-label"><strong>{topic.name}</strong><b>{topic.publication_count} 篇</b></div>
              <div className="topic-chart-track"><i style={{ width: `${Math.max((topic.publication_count / maxCount) * 100, 3)}%` }} /></div>
            </div>
          </div>
        ))}
      </div>
      <div className="term-cloud" aria-label="高频研究词">
        {data.terms.slice(0, 22).map((term) => {
          const weight = term.weighted_score / maxWeight;
          return <span style={{ fontSize: `${10 + weight * 9}px`, opacity: 0.55 + weight * 0.45 }} key={term.term}>{term.term}</span>;
        })}
      </div>
    </>
  );
}

function LoadingState({ status, onCancel, actionBusy }: { status: AnalysisStatus; onCancel: () => void; actionBusy: boolean }) {
  const active = currentStep(status.phase);
  return (
    <section className="progress-panel" aria-live="polite">
      <div className="progress-heading">
        <div>
          <span className="eyebrow">正在分析</span>
          <h2>{status.query_text}</h2>
        </div>
        <strong>{Math.round(status.progress_percent)}%</strong>
      </div>
      <div className="progress-line">
        <span style={{ width: `${status.progress_percent}%` }} />
      </div>
      <div className="steps">
        {flow.map((label, index) => (
          <div className={`step ${index < active ? "done" : ""} ${index === active ? "active" : ""}`} key={label}>
            <span className="step-index">{index < active ? <CheckCircleIcon weight="fill" /> : index + 1}</span>
            <span>{label}</span>
          </div>
        ))}
      </div>
      <div className="progress-footer">
        <p className="progress-note">{phaseLabels[status.phase ?? "queued"] ?? "正在处理"}。页面可以安全刷新，任务会在后台继续。</p>
        <button className="secondary-button danger" type="button" onClick={onCancel} disabled={actionBusy}>取消任务</button>
      </div>
    </section>
  );
}

function ResultsView({ data, status }: { data: AnalysisResults; status: AnalysisStatus }) {
  const { overview, trends, regions, topics, publications, report } = data;
  const [showAllPublications, setShowAllPublications] = useState(false);
  const [publicationQuery, setPublicationQuery] = useState("");
  const [publicationYear, setPublicationYear] = useState("all");
  const [publicationSort, setPublicationSort] = useState("rank");
  const [copied, setCopied] = useState(false);
  const availableYears = useMemo(
    () => [...new Set(publications.items.map((item) => item.publication_date?.slice(0, 4)).filter(Boolean))].sort().reverse() as string[],
    [publications.items],
  );
  const filteredPublications = useMemo(() => {
    const needle = publicationQuery.trim().toLocaleLowerCase();
    const filtered = publications.items.filter((item) => {
      const matchesText = !needle || `${item.title} ${item.journal ?? ""} ${item.pmid}`.toLocaleLowerCase().includes(needle);
      const matchesYear = publicationYear === "all" || item.publication_date?.startsWith(publicationYear);
      return matchesText && matchesYear;
    });
    return [...filtered].sort((a, b) => {
      if (publicationSort === "date") return (b.publication_date ?? "").localeCompare(a.publication_date ?? "");
      if (publicationSort === "score") return (b.score ?? 0) - (a.score ?? 0);
      return (a.rank ?? 999) - (b.rank ?? 999);
    });
  }, [publicationQuery, publicationSort, publicationYear, publications.items]);
  const visiblePublications = showAllPublications ? filteredPublications : filteredPublications.slice(0, 10);

  async function copyReport() {
    await navigator.clipboard.writeText(report.body_markdown);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  }

  function downloadReport() {
    const blob = new Blob([`# ${report.title}\n\n${report.body_markdown}\n\n---\n${report.disclaimer}\n`], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `PubMed科研情报分析-${overview.query.replace(/[\\/:*?\"<>|]/g, "-")}.md`;
    link.click();
    URL.revokeObjectURL(url);
  }

  function printReport() {
    document.body.classList.add("printing-report");
    window.print();
    document.body.classList.remove("printing-report");
  }
  return (
    <>
      <div className="result-title">
        <div>
          <span className="eyebrow">分析结果</span>
          <h2>{overview.query}</h2>
          <p>完成于 {formatDate(status.completed_at)} · 结果仅代表本次检索与抽样范围</p>
        </div>
        <span className="status-badge success"><CheckCircleIcon weight="fill" /> 已完成</span>
      </div>

      <section className="metrics" aria-label="核心统计">
        <article><span>PubMed 命中</span><strong>{formatNumber(overview.total_hit_count)}</strong><small>完整检索结果</small></article>
        <article><span>分析样本</span><strong>{formatNumber(overview.sampled_publication_count)}</strong><small>用于统计与排序</small></article>
        <article><span>摘要样本</span><strong>{formatNumber(overview.abstract_sample_count)}</strong><small>用于主题归纳</small></article>
        <article><span>AI 报告</span><strong>{report.sections.length}</strong><small>{report.model ?? "模板生成"} · {report.ai_status === "succeeded" ? "证据校验通过" : "已降级"}</small></article>
      </section>

      <div className="workspace-grid">
        <main className="analysis-column">
          <div className="chart-grid">
            <section className="panel">
              <header className="panel-header"><div><span className="section-number">01</span><h3>年度趋势</h3></div><small>样本 n={trends.sample_size}</small></header>
              <TrendChart items={trends.items} />
            </section>
            <section className="panel">
              <header className="panel-header"><div><span className="section-number">02</span><h3>地区分布</h3></div><small>第一作者单位</small></header>
              <RegionBars items={regions.items} />
              <p className="method-note">{regions.method_note}</p>
            </section>
          </div>

          <section className="panel topics-panel">
            <header className="panel-header"><div><span className="section-number">03</span><h3>研究方向</h3></div><small>{topics.topics.length} 个主题</small></header>
            <TopicChart data={topics} />
            <div className="topic-list">
              {topics.topics.map((topic) => (
                <article className="topic-item" key={topic.id}>
                  <span className="topic-index">{String(topic.index).padStart(2, "0")}</span>
                  <div><h4>{topic.name}</h4><p>{topic.summary}</p><div className="term-row">{topic.terms.slice(0, 6).map((term) => <span key={term}>{term}</span>)}</div></div>
                  <strong>{Math.round(topic.share * 100)}%</strong>
                </article>
              ))}
            </div>
          </section>

          <section className="panel publications-panel">
            <header className="panel-header"><div><span className="section-number">04</span><h3>代表文献</h3></div><small>影响力综合排序</small></header>
            <div className="publication-tools">
              <label><span>筛选文献</span><input value={publicationQuery} onChange={(event) => setPublicationQuery(event.target.value)} placeholder="标题、期刊或 PMID" /></label>
              <label><span>年份</span><select value={publicationYear} onChange={(event) => setPublicationYear(event.target.value)}><option value="all">全部</option>{availableYears.map((year) => <option value={year} key={year}>{year}</option>)}</select></label>
              <label><span>排序</span><select value={publicationSort} onChange={(event) => setPublicationSort(event.target.value)}><option value="rank">综合排名</option><option value="score">综合得分</option><option value="date">最新发表</option></select></label>
            </div>
            <div className="publication-table">
              {visiblePublications.map((publication) => (
                <article className="publication-row" key={publication.pmid}>
                  <span className="publication-rank">{String(publication.rank ?? 0).padStart(2, "0")}</span>
                  <div>
                    <a href={`https://pubmed.ncbi.nlm.nih.gov/${publication.pmid}/`} target="_blank" rel="noreferrer">
                      {publication.title}<ArrowSquareOutIcon />
                    </a>
                    <p>{publication.journal ?? "期刊信息缺失"} · {publication.publication_date ?? "日期未知"} · PMID {publication.pmid}</p>
                    <details className="score-details">
                      <summary>查看评分构成</summary>
                      <div>
                        {Object.entries(publication.score_components.components ?? {}).map(([name, value]) => (
                          <span key={name}><b>{scoreLabels[name] ?? name}</b><i>{Math.round(value * 100)}%</i></span>
                        ))}
                        {(publication.score_components.missing_signals?.length ?? 0) > 0 && <p>缺失信号：{publication.score_components.missing_signals?.join("、")}</p>}
                      </div>
                    </details>
                  </div>
                  <span className="score">{publication.score?.toFixed(2) ?? "—"}</span>
                </article>
              ))}
              {visiblePublications.length === 0 && <div className="list-empty">没有符合当前筛选条件的文献。</div>}
            </div>
            {filteredPublications.length > 10 && (
              <button className="text-button" type="button" onClick={() => setShowAllPublications((value) => !value)}>
                {showAllPublications ? "收起文献" : `查看全部 ${filteredPublications.length} 篇代表文献`}
              </button>
            )}
            <p className="method-note">{publications.disclaimer}</p>
          </section>
        </main>

        <aside className="report-panel">
          <header>
            <span className="eyebrow">DeepSeek 中文综述</span>
            <h3>{report.title}</h3>
            <div className="report-meta"><span>{report.model ?? "内部模板"}</span><span>{report.generation_mode === "deepseek" ? "AI 生成" : "模板降级"}</span></div>
            <div className="report-actions">
              <button type="button" onClick={() => void copyReport()}>{copied ? "已复制" : "复制报告"}</button>
              <button type="button" onClick={downloadReport}>下载 Markdown</button>
              <button type="button" onClick={printReport}>打印报告</button>
            </div>
          </header>
          <div className="report-sections">
            {report.sections.map((section) => (
              <section key={section.key}>
                <h4>{section.heading}</h4>
                <p>{section.content}</p>
                <div className="pmid-row">
                  {section.evidence_pmids.map((pmid) => (
                    <a href={`https://pubmed.ncbi.nlm.nih.gov/${pmid}/`} target="_blank" rel="noreferrer" key={pmid}>PMID {pmid}</a>
                  ))}
                </div>
              </section>
            ))}
          </div>
          <footer>{report.disclaimer}</footer>
        </aside>
      </div>
    </>
  );
}

export default function App() {
  const [query, setQuery] = useState("Parkinson disease biomarkers");
  const [startYear, setStartYear] = useState(2024);
  const [endYear, setEndYear] = useState(2026);
  const [metadataLimit, setMetadataLimit] = useState(100);
  const [abstractLimit, setAbstractLimit] = useState(50);
  const [reportEvidenceLimit, setReportEvidenceLimit] = useState(10);
  const [language, setLanguage] = useState("");
  const [publicationType, setPublicationType] = useState("");
  const [sort, setSort] = useState<"relevance" | "pub_date">("relevance");
  const [historyFilter, setHistoryFilter] = useState<"all" | AnalysisState>("all");
  const [healthy, setHealthy] = useState<boolean | null>(null);
  const [history, setHistory] = useState<AnalysisStatus[]>([]);
  const [status, setStatus] = useState<AnalysisStatus | null>(null);
  const [results, setResults] = useState<AnalysisResults | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshHistory = useCallback(async () => {
    const list = await listAnalyses();
    setHistory(list.items);
    return list.items;
  }, []);

  const openAnalysis = useCallback(async (id: string) => {
    setError(null);
    setResults(null);
    const next = await getAnalysis(id);
    setStatus(next);
    localStorage.setItem("pubmed:last-analysis", id);
  }, []);

  useEffect(() => {
    let cancelled = false;
    void Promise.all([checkHealth(), refreshHistory()])
      .then(([isHealthy, items]) => {
        if (cancelled) return;
        setHealthy(isHealthy);
        const saved = localStorage.getItem("pubmed:last-analysis");
        const preferred = items.find((item) => item.id === saved) ?? items.find((item) => item.status === "succeeded");
        if (preferred) void openAnalysis(preferred.id);
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setHealthy(false);
          setError(reason instanceof Error ? reason.message : "无法连接后端服务");
        }
      });
    return () => { cancelled = true; };
  }, [openAnalysis, refreshHistory]);

  useEffect(() => {
    if (!status || !["queued", "running"].includes(status.status)) return;
    const timer = window.setTimeout(() => {
      void getAnalysis(status.id).then(setStatus).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "任务状态更新失败"));
    }, 2000);
    return () => window.clearTimeout(timer);
  }, [status]);

  useEffect(() => {
    if (status?.status !== "succeeded" || results?.overview.analysis_id === status.id) return;
    setBusy(true);
    void getResults(status.id)
      .then((data) => {
        setResults(data);
        void refreshHistory();
      })
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "结果加载失败"))
      .finally(() => setBusy(false));
  }, [refreshHistory, results?.overview.analysis_id, status]);

  const activePhase = useMemo(() => phaseLabels[status?.phase ?? ""] ?? "暂无任务", [status?.phase]);
  const filteredHistory = useMemo(
    () => historyFilter === "all" ? history : history.filter((item) => item.status === historyFilter),
    [history, historyFilter],
  );

  async function handleCancel() {
    if (!status || !["queued", "running"].includes(status.status)) return;
    setActionBusy(true);
    setError(null);
    try {
      await cancelAnalysis(status.id);
      setStatus(await getAnalysis(status.id));
      await refreshHistory();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "取消任务失败");
    } finally {
      setActionBusy(false);
    }
  }

  async function handleRetry() {
    if (!status || !["failed", "cancelled"].includes(status.status)) return;
    setActionBusy(true);
    setError(null);
    setResults(null);
    try {
      await retryAnalysis(status.id);
      setStatus(await getAnalysis(status.id));
      await refreshHistory();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "重新运行失败");
    } finally {
      setActionBusy(false);
    }
  }

  async function handleDelete() {
    if (!status || !window.confirm(`确认删除“${status.query_text}”的历史分析吗？`)) return;
    setActionBusy(true);
    setError(null);
    try {
      const deletedId = status.id;
      await deleteAnalysis(deletedId);
      localStorage.removeItem("pubmed:last-analysis");
      setStatus(null);
      setResults(null);
      const items = await refreshHistory();
      const next = items.find((item) => item.id !== deletedId && item.status === "succeeded")
        ?? items.find((item) => item.id !== deletedId);
      if (next) await openAnalysis(next.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "删除历史分析失败");
    } finally {
      setActionBusy(false);
    }
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!query.trim()) return;
    if (!Number.isInteger(metadataLimit) || metadataLimit < 1 || metadataLimit > 2000) {
      setError("文献样本必须是 1 至 2000 之间的整数。");
      return;
    }
    if (!Number.isInteger(abstractLimit) || abstractLimit < 0 || abstractLimit > 500 || abstractLimit > metadataLimit) {
      setError("摘要样本必须是 0 至 500 之间且不大于文献样本的整数。");
      return;
    }
    if (!Number.isInteger(reportEvidenceLimit) || reportEvidenceLimit < 1 || reportEvidenceLimit > 50 || reportEvidenceLimit > metadataLimit) {
      setError("报告证据数必须是 1 至 50 之间且不大于文献样本的整数。");
      return;
    }
    if (startYear > endYear) {
      setError("起始年份不能晚于结束年份。");
      return;
    }
    setBusy(true);
    setError(null);
    setResults(null);
    try {
      const accepted = await createAnalysis({
        query: query.trim(),
        start_year: startYear,
        end_year: endYear,
        languages: language ? [language] : [],
        publication_types: publicationType ? [publicationType] : [],
        sort,
        metadata_limit: metadataLimit,
        abstract_limit: abstractLimit,
        report_evidence_limit: reportEvidenceLimit,
      });
      await openAnalysis(accepted.analysis_id);
      await refreshHistory();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建分析失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand"><DatabaseIcon weight="duotone" /><div><strong>PubMed 科研情报分析</strong><span>真实检索 · 证据约束 · 中文综述</span></div></div>
        <div className={`connection ${healthy ? "online" : ""}`}><span />{healthy ? "后端已连接" : healthy === false ? "后端未连接" : "检查连接"}</div>
      </header>

      <div className="page">
        <section className="search-section">
          <div className="search-copy"><span className="eyebrow">新建分析</span><h1>从一个关键词开始</h1><p>检索 PubMed，整理研究趋势、主题方向和代表文献，并生成带 PMID 证据的中文综述。</p></div>
          <form className="search-form" onSubmit={submit}>
            <label className="query-field"><span>检索关键词</span><div><MagnifyingGlassIcon /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="例如：Alzheimer disease biomarkers" /></div></label>
            <label><span>起始年份</span><input type="number" min="1800" max="3000" value={startYear} onChange={(event) => setStartYear(Number(event.target.value))} /></label>
            <label><span>结束年份</span><input type="number" min="1800" max="3000" value={endYear} onChange={(event) => setEndYear(Number(event.target.value))} /></label>
            <label><span>文献样本（1–2000）</span><input type="number" min="1" max="2000" step="1" value={metadataLimit} onChange={(event) => setMetadataLimit(Number(event.target.value))} /></label>
            <button type="submit" disabled={busy || !healthy}>{busy ? "处理中" : "开始分析"}</button>
            <div className="advanced-fields">
              <label><span>摘要样本（0–500）</span><input type="number" min="0" max="500" step="1" value={abstractLimit} onChange={(event) => setAbstractLimit(Number(event.target.value))} /></label>
              <label><span>报告证据（1–50）</span><input type="number" min="1" max="50" step="1" value={reportEvidenceLimit} onChange={(event) => setReportEvidenceLimit(Number(event.target.value))} /></label>
              <label><span>文献语言</span><select value={language} onChange={(event) => setLanguage(event.target.value)}><option value="">全部语言</option><option value="English">英语</option><option value="Chinese">中文</option></select></label>
              <label><span>文献类型</span><select value={publicationType} onChange={(event) => setPublicationType(event.target.value)}><option value="">全部类型</option><option value="Review">综述</option><option value="Clinical Trial">临床试验</option><option value="Meta-Analysis">Meta 分析</option><option value="Randomized Controlled Trial">随机对照试验</option><option value="Journal Article">期刊论文</option></select></label>
              <label><span>PubMed 排序</span><select value={sort} onChange={(event) => setSort(event.target.value as "relevance" | "pub_date")}><option value="relevance">最佳匹配</option><option value="pub_date">最新发表</option></select></label>
            </div>
          </form>
          <div className="search-foot">
            <span><ClockIcon /> 当前阶段：{activePhase}</span>
            {history.length > 0 && <div className="history-controls">
              <label><span>状态</span><select value={historyFilter} onChange={(event) => setHistoryFilter(event.target.value as "all" | AnalysisState)}><option value="all">全部</option><option value="succeeded">已完成</option><option value="running">运行中</option><option value="queued">等待中</option><option value="failed">失败</option><option value="cancelled">已取消</option></select></label>
              <label><span>历史分析</span><select value={filteredHistory.some((item) => item.id === status?.id) ? status?.id : ""} onChange={(event) => void openAnalysis(event.target.value)}><option value="" disabled>{filteredHistory.length ? "选择分析" : "无匹配记录"}</option>{filteredHistory.map((item) => <option value={item.id} key={item.id}>{item.query_text} · {item.status === "succeeded" ? "已完成" : item.status === "cancelled" ? "已取消" : phaseLabels[item.phase ?? "queued"]}</option>)}</select></label>
              <button className="secondary-button danger" type="button" onClick={() => void handleDelete()} disabled={!status || actionBusy}>删除记录</button>
            </div>}
          </div>
        </section>

        {error && <div className="error-banner" role="alert"><WarningCircleIcon weight="fill" /><div><strong>无法完成请求</strong><span>{error}</span></div></div>}
        {status && ["queued", "running"].includes(status.status) && <LoadingState status={status} onCancel={() => void handleCancel()} actionBusy={actionBusy} />}
        {status && ["failed", "cancelled"].includes(status.status) && <div className="empty-state"><WarningCircleIcon /><h2>{status.status === "failed" ? "分析失败" : "分析已取消"}</h2><p>{status.error_detail ?? "可以使用原检索条件重新运行。"}</p>{status.retryable && <button className="secondary-button" type="button" onClick={() => void handleRetry()} disabled={actionBusy}>{actionBusy ? "正在处理" : "重新运行"}</button>}</div>}
        {status?.status === "succeeded" && busy && !results && <div className="empty-state"><ClockIcon className="spin" /><h2>正在载入结果</h2></div>}
        {status?.status === "succeeded" && results && <ResultsView data={results} status={status} />}
        {!status && !error && <div className="empty-state"><MagnifyingGlassIcon /><h2>等待检索</h2><p>输入研究主题后，分析结果会显示在这里。</p></div>}
      </div>
    </div>
  );
}
