from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Any, Dict
from urllib.parse import urlparse, parse_qsl
import json
import httpx
import time
import logging

logger = logging.getLogger(__name__)

class RepeaterError(Exception):
    """Base exception for Repeater network operations."""
    pass

class RequestTimeoutError(RepeaterError):
    """Raised when an HTTP request times out."""
    pass

class ConnectionFailedError(RepeaterError):
    """Raised when an HTTP connection fails to establish."""
    pass

# -------------------------
# Shared primitives
# -------------------------

@dataclass
class Header:
    name: str
    value: str


@dataclass
class ParsedBody:
    raw: bytes
    content_type: Optional[str]
    parsed: Any = None


# -------------------------
# Request
# -------------------------

@dataclass
class RawRequest:
    method: str
    target: str
    version: str
    headers: List[Header]
    body: ParsedBody
    notes: Dict[str, Any] = field(default_factory=dict)

    def get_header(self, name: str) -> Optional[str]:
        for h in self.headers:
            if h.name.lower() == name.lower():
                return h.value
        return None

    @property
    def host(self) -> str:
        host_header = self.get_header("Host")
        if not host_header:
            raise ValueError("Host header is strictly required but missing from the request.")
        return host_header


# -------------------------
# Response
# -------------------------

@dataclass
class RawResponse:
    version: str
    status_code: int
    reason: str
    headers: List[Header]
    body: ParsedBody
    elapsed: float

    def get_header(self, name: str):
        for h in self.headers:
            if h.name.lower() == name.lower():
                return h.value
        return None


# -------------------------
# Flow
# -------------------------

@dataclass
class Flow:
    request: RawRequest
    response: RawResponse


# -------------------------
# Response Parser
# -------------------------

class ResponseParser:

    @staticmethod
    def parse(resp: httpx.Response) -> RawResponse:

        ctype = resp.headers.get("content-type")
        parsed = None

        if ctype:

            if "application/json" in ctype:
                try:
                    parsed = resp.json()
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to decode JSON body: {e}")
                except Exception as e:
                    logger.error(f"Unexpected error parsing JSON: {e}", exc_info=True)

            elif "application/x-www-form-urlencoded" in ctype:
                try:
                    parsed = parse_qsl(
                        resp.text,
                        keep_blank_values=True,
                        strict_parsing=False
                    )
                except Exception as e:
                    logger.warning(f"Failed to parse form-urlencoded body: {e}")

        body = ParsedBody(
            raw=resp.content,
            content_type=ctype,
            parsed=parsed
        )

        headers = [
            Header(k, v)
            for k, v in resp.headers.multi_items()
        ]

        return RawResponse(
            version=f"HTTP/{resp.http_version}",
            status_code=resp.status_code,
            reason=resp.reason_phrase,
            headers=headers,
            body=body,
            elapsed=resp.elapsed.total_seconds()
        )


# -------------------------
# Repeater
# -------------------------

class Repeater:

    def __init__(
        self,
        timeout: float = 30.0,
        verify: bool = True,
        follow_redirects: bool = False,
        max_retries: int = 0,
        proxy: Optional[str] = None,
        version: str = "HTTP/1.1"
    ):
        is_http2 = False
        if version == "HTTP/2":
            is_http2 = True
        self.timeout = timeout
        transport = httpx.HTTPTransport(retries=max_retries)
        self.client = httpx.Client(
            timeout=timeout,
            verify=verify,
            follow_redirects=follow_redirects,
            http2=is_http2,
            transport=transport,
            proxy=proxy
        )

    def __enter__(self) -> "Repeater":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def send(self, req: RawRequest) -> Flow:

        scheme = req.notes.get("scheme", "https")
        
        try:
            host = req.host
        except ValueError as e:
            logger.error("Failed to construct URL: Missing Host header.")
            raise RepeaterError(str(e)) from e

        url = f"{scheme}://{host}{req.target}"

        headers = [
            (h.name, h.value)
            for h in req.headers
            if h.name.lower() != "host"
        ]

        logger.debug(f"Dispatching {req.method} request to {url}")

        try:
            response = self.client.request(
                method=req.method,
                url=url,
                headers=headers,
                content=req.body.raw
            )
        except httpx.TimeoutException as e:
            logger.error(f"Timeout connecting to {url}: {e}")
            raise RequestTimeoutError(f"Request timed out after {self.timeout}s") from e
        except httpx.RequestError as e:
            logger.error(f"Connection failed to {url}: {e}")
            raise ConnectionFailedError(f"Connection failed: {e}") from e
        except Exception as e:
            logger.critical(f"Unexpected execution error sending request to {url}: {e}", exc_info=True)
            raise RepeaterError(f"Unexpected error: {e}") from e

        parsed_response = ResponseParser.parse(response)
        
        logger.info(
            f"Received {parsed_response.status_code} from {url} "
            f"in {parsed_response.elapsed:.3f}s"
        )

        return Flow(
            request=req,
            response=parsed_response
        )

    def close(self) -> None:
        self.client.close()
