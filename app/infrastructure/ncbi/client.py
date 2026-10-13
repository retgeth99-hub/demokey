from __future__ import annotations

import asyncio
import hashlib
import json
import random
import time
from dataclasses import dataclass
from typing import Any

import httpx


class UpstreamError(RuntimeError):
    def __init__(self, code: str, detail: str, *, retryable: bool, status_code: int | None = None):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.retryable = retryable
        self.status_code = status_code


class AsyncRateLimiter:
    def __init__(self, rate_per_second: float) -> None:
        self.interval = 1.0 / rate_per_second
        self._lock = asyncio.Lock()
        self._next_at = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            delay = max(0.0, self._next_at - now)
            if delay:
                await asyncio.sleep(delay)
            self._next_at = max(now, self._next_at) + self.interval


@dataclass(slots=True)
class SearchResult:
    total_count: int
    ids: list[int]
    query_translation: str
    webenv: str | None
    query_key: str | None
    raw: bytes
    duration_ms: int
    request_fingerprint: str


@dataclass(slots=True)
class BinaryResult:
    raw: bytes
    duration_ms: int
    request_fingerprint: str
    status_code: int


class NcbiClient:
    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        tool: str,
        email: str,
        rate_limit: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.tool = tool
        self.email = email
        effective_rate = min(rate_limit, 10.0 if api_key else 3.0)
        self.rate_limiter = AsyncRateLimiter(effective_rate)
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=10.0))
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    def _base_params(self) -> dict[str, str]:
        params = {"tool": self.tool, "email": self.email}
        if self.api_key:
            params["api_key"] = self.api_key
        return params

    @staticmethod
    def _fingerprint(endpoint: str, params: dict[str, Any]) -> str:
        safe = {key: value for key, value in params.items() if key != "api_key"}
        encoded = json.dumps([endpoint, safe], sort_keys=True, default=str).encode()
        return hashlib.sha256(encoded).hexdigest()

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        attempts: int = 3,
    ) -> BinaryResult:
        merged = self._base_params()
        merged.update(params or {})
        body = self._base_params()
        body.update(data or {})
        fingerprint = self._fingerprint(endpoint, merged if method == "GET" else body)
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            await self.rate_limiter.wait()
            started = time.perf_counter()
            try:
                response = await self.client.request(
                    method,
                    f"{self.base_url}/{endpoint}",
                    params=merged if method == "GET" else None,
                    data=body if method != "GET" else None,
                )
                duration_ms = int((time.perf_counter() - started) * 1000)
                if response.status_code < 400:
                    return BinaryResult(response.content, duration_ms, fingerprint, response.status_code)
                retryable = response.status_code == 429 or response.status_code >= 500
                if not retryable:
                    raise UpstreamError(
                        "PUBMED_REQUEST_REJECTED",
                        f"PubMed returned HTTP {response.status_code}",
                        retryable=False,
                        status_code=response.status_code,
                    )
                last_error = UpstreamError(
                    "PUBMED_TEMPORARY_FAILURE",
                    f"PubMed returned HTTP {response.status_code}",
                    retryable=True,
                    status_code=response.status_code,
                )
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 2 ** (attempt - 1)
            except UpstreamError:
                raise
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                delay = 2 ** (attempt - 1)
            if attempt < attempts:
                await asyncio.sleep(delay + random.uniform(0, 0.25))
        raise UpstreamError(
            "PUBMED_UNAVAILABLE",
            "PubMed request failed after retries",
            retryable=True,
        ) from last_error

    async def search(self, term: str, retmax: int, sort: str) -> SearchResult:
        result = await self._request(
            "GET",
            "esearch.fcgi",
            params={
                "db": "pubmed",
                "term": term,
                "retmode": "json",
                "retmax": str(retmax),
                "sort": sort,
                "usehistory": "y",
            },
        )
        try:
            payload = json.loads(result.raw)
            data = payload["esearchresult"]
            return SearchResult(
                total_count=int(data["count"]),
                ids=[int(value) for value in data.get("idlist", [])],
                query_translation=data.get("querytranslation", term),
                webenv=data.get("webenv"),
                query_key=data.get("querykey"),
                raw=result.raw,
                duration_ms=result.duration_ms,
                request_fingerprint=result.request_fingerprint,
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise UpstreamError(
                "PUBMED_INVALID_RESPONSE", "PubMed search response could not be parsed", retryable=True
            ) from exc

    async def fetch(self, ids: list[int]) -> BinaryResult:
        return await self._request(
            "POST",
            "efetch.fcgi",
            data={"db": "pubmed", "id": ",".join(map(str, ids)), "retmode": "xml"},
        )

    async def cited_by(self, ids: list[int]) -> BinaryResult:
        return await self._request(
            "POST",
            "elink.fcgi",
            data={
                "dbfrom": "pubmed",
                "db": "pubmed",
                "id": ids,
                "linkname": "pubmed_pubmed_citedin",
                "retmode": "xml",
            },
        )

