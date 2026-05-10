from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Any, Dict
from urllib.parse import urlparse, parse_qsl
import json
import re


@dataclass
class Header:
    name: str
    value: str


@dataclass
class ParsedBody:
    raw: bytes
    content_type: Optional[str]
    parsed: Any = None
    error: Optional[str] = None

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
            raise ValueError("Host header is strictly required but missing.")
        return host_header

    @property
    def query_params(self):
        parsed = urlparse(self.target)
        return parse_qsl(parsed.query, keep_blank_values=True)


class RawRequestParser:

    @staticmethod
    def parse(raw: str | bytes) -> RawRequest:
        if isinstance(raw, str):
            raw = raw.encode(errors="replace")

        # Safely split head and body FIRST to avoid corrupting binary payloads in the body
        if b"\r\n\r\n" in raw:
            head_bytes, body = raw.split(b"\r\n\r\n", 1)
        elif b"\n\n" in raw:
            head_bytes, body = raw.split(b"\n\n", 1)
        else:
            head_bytes = raw
            body = b""

        # Normalize newlines only in the headers
        head_text = head_bytes.decode(errors="replace").replace("\r\n", "\n")
        lines = head_text.split("\n")

        if not lines or not lines[0].strip():
            raise ValueError("Empty request")

        first = lines[0].strip()

        if first.startswith(":method"):
            return RawRequestParser._parse_http2(lines, body)

        # Handle extra spaces and missing HTTP version gracefully
        parts = [p for p in first.split(" ") if p]

        if len(parts) >= 3:
            method, target, version = parts[0], parts[1], " ".join(parts[2:])
        elif len(parts) == 2:
            method, target, version = parts[0], parts[1], "HTTP/1.1"
        elif len(parts) == 1:
            method, target, version = parts[0], "/", "HTTP/1.1"
        else:
            method, target, version = "UNKNOWN", "/", "HTTP/1.1"

        headers = RawRequestParser._parse_headers(lines[1:])
        parsed_body = RawRequestParser._parse_body(headers, body)

        return RawRequest(
            method=method,
            target=target,
            version=version,
            headers=headers,
            body=parsed_body
        )

    @staticmethod
    def _parse_http2(lines, body):
        pseudo = {}
        headers = []

        for line in lines:
            if not line.strip():
                continue

            if line.startswith(":"):
                name, value = line.split(":", 2)[1:]
                pseudo[f":{name.strip()}"] = value.strip()
            else:
                name, value = line.split(":", 1)
                headers.append(Header(name.strip(), value.strip()))

        parsed_body = RawRequestParser._parse_body(headers, body)

        return RawRequest(
            method=pseudo.get(":method", ""),
            target=pseudo.get(":path", ""),
            version="HTTP/2",
            headers=headers,
            body=parsed_body
        )

    @staticmethod
    def _parse_headers(lines):
        headers = []

        for line in lines:
            line = line.strip()

            if not line:
                continue

            if ":" not in line:
                continue

            name, value = line.split(":", 1)
            headers.append(Header(name.strip(), value.strip()))

        return headers

    @staticmethod
    def _parse_body(headers, body):
        ctype = None

        for h in headers:
            if h.name.lower() == "content-type":
                ctype = h.value.lower()
                break

        parsed = None
        error = None

        if ctype and body:

            if "application/json" in ctype:
                try:
                    parsed = json.loads(body.decode(errors="replace"))
                except Exception as e:
                    error = f"JSON parse error: {str(e)}"

            elif "application/x-www-form-urlencoded" in ctype:
                try:
                    parsed = parse_qsl(
                        body.decode(errors="replace"),
                        keep_blank_values=True,
                        strict_parsing=True
                    )
                except Exception as e:
                    error = f"Form parse error: {str(e)}"

            elif "multipart/form-data" in ctype:
                boundary_match = re.search(r'boundary=([^;]+)', ctype, re.IGNORECASE)
                if boundary_match:
                    boundary = boundary_match.group(1).strip('"\'')
                    parsed = {
                        "boundary": boundary,
                        "raw": body
                    }
                else:
                    error = "Multipart boundary not found in Content-Type"

        return ParsedBody(
            raw=body,
            content_type=ctype,
            parsed=parsed,
            error=error
        )
