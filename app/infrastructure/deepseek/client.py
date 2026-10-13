from __future__ import annotations

import asyncio
import json
import random
from dataclasses import dataclass
from typing import Any

import httpx

from app.domain.reports import ReportPayload, validate_evidence
from app.infrastructure.ncbi.client import UpstreamError


@dataclass(slots=True)
class GeneratedReport:
    payload: ReportPayload
    model: str
    usage: dict[str, object]
    validation_status: str


class DeepSeekClient:
    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        model: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=10.0))
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def generate_report(self, evidence: dict[str, Any], allowed_pmids: set[int]) -> GeneratedReport:
        if not self.api_key:
            raise UpstreamError(
                "DEEPSEEK_NOT_CONFIGURED", "DeepSeek API key is not configured", retryable=False
            )
        system = (
            "你是医学文献综述助手。只能根据输入 JSON 中的统计和文献证据生成中文报告。"
            "禁止补充输入之外的数字、疗效或因果结论。输出必须是 JSON object，不得使用 Markdown 代码块。"
            "sections 必须依次使用 overview、year_trend、research_directions、"
            "representative_findings、limitations_and_outlook 五个 key。每个结论引用的 PMID 必须来自输入。"
        )
        user = {
            "instruction": "生成约500至800个中文字符的结构化综述。JSON schema见 expected_shape。",
            "expected_shape": {
                "title": "string",
                "sections": [
                    {"key": key, "heading": "string", "content": "string", "evidence_pmids": [0]}
                    for key in (
                        "overview",
                        "year_trend",
                        "research_directions",
                        "representative_findings",
                        "limitations_and_outlook",
                    )
                ],
                "topic_labels": [
                    {"index": 1, "name_zh": "string", "summary_zh": "string"}
                ],
                "limitations": ["string"],
            },
            "evidence": evidence,
        }
        request_payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "max_tokens": 3000,
        }
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                response = await self.client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=request_payload,
                )
                if response.status_code >= 400:
                    retryable = response.status_code in {429, 500, 503}
                    error = UpstreamError(
                        "DEEPSEEK_TEMPORARY_FAILURE" if retryable else "DEEPSEEK_REQUEST_REJECTED",
                        f"DeepSeek returned HTTP {response.status_code}",
                        retryable=retryable,
                        status_code=response.status_code,
                    )
                    if not retryable:
                        raise error
                    last_error = error
                else:
                    data = response.json()
                    content = data["choices"][0]["message"]["content"]
                    if not content:
                        raise ValueError("empty model content")
                    report = ReportPayload.model_validate_json(content)
                    validate_evidence(report, allowed_pmids)
                    return GeneratedReport(
                        payload=report,
                        model=data.get("model", self.model),
                        usage=data.get("usage", {}),
                        validation_status="valid",
                    )
            except UpstreamError:
                raise
            except (httpx.TimeoutException, httpx.NetworkError, KeyError, ValueError, json.JSONDecodeError) as exc:
                last_error = exc
            if attempt < 3:
                await asyncio.sleep(2 ** (attempt - 1) + random.uniform(0, 0.25))
        raise UpstreamError(
            "DEEPSEEK_INVALID_RESPONSE",
            "DeepSeek did not return a valid evidence-constrained report",
            retryable=False,
        ) from last_error

