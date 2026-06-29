from __future__ import annotations

import base64
from contextlib import ExitStack, suppress
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from ..network import configured_network_proxy, open_external_url

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_IMAGE_RESPONSE_FORMAT = "b64_json"
DEFAULT_OPENAI_USER_AGENT = "UnrealImageMaker/0.1 (+https://github.com/openai/codex)"


@dataclass(slots=True)
class ImageGenerationResult:
    output_path: Path
    model: str
    prompt: str
    size: str
    quality: str
    request_id: str | None = None
    revised_prompt: str | None = None
    stream_events: list[str] | None = None
    base_url: str | None = None


class OpenAIImageProvider:
    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL") or DEFAULT_OPENAI_BASE_URL).rstrip("/")
        self.response_format = os.environ.get("OPENAI_IMAGE_RESPONSE_FORMAT", DEFAULT_IMAGE_RESPONSE_FORMAT)

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def generate(
        self,
        prompt: str,
        output_path: Path,
        *,
        model: str = "gpt-image-2",
        size: str = "1024x1024",
        quality: str = "auto",
    ) -> ImageGenerationResult:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")

        payload = {
            "model": model,
            "prompt": prompt,
            "size": size,
            "quality": quality,
            "response_format": self.response_format,
        }
        request = urllib.request.Request(
            f"{self.base_url}/images/generations",
            data=json.dumps(payload).encode("utf-8"),
            headers=_api_headers(self.api_key),
            method="POST",
        )
        try:
            with open_external_url(request, timeout=180) as response:
                response_body = json.loads(response.read().decode("utf-8"))
                request_id = response.headers.get("x-request-id")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            with suppress(Exception):
                exc.close()
            raise RuntimeError(_format_openai_http_error("generation", exc.code, body, self.base_url)) from exc

        image_data = response_body.get("data", [{}])[0]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        _write_image_result(image_data, output_path, self.base_url)
        return ImageGenerationResult(
            output_path=output_path,
            model=model,
            prompt=prompt,
            size=size,
            quality=quality,
            request_id=request_id,
            revised_prompt=image_data.get("revised_prompt"),
            base_url=self.base_url,
        )

    def edit(
        self,
        prompt: str,
        image_path: Path,
        output_path: Path,
        *,
        model: str = "gpt-image-2",
        size: str = "1024x1024",
        quality: str = "auto",
    ) -> ImageGenerationResult:
        return self.edit_many(prompt, [image_path], output_path, model=model, size=size, quality=quality)

    def edit_many(
        self,
        prompt: str,
        image_paths: Sequence[Path],
        output_path: Path,
        *,
        model: str = "gpt-image-2",
        size: str = "1024x1024",
        quality: str = "auto",
    ) -> ImageGenerationResult:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        try:
            import requests
        except ImportError as exc:
            raise RuntimeError("requests is required for image editing uploads") from exc
        if not image_paths:
            raise ValueError("At least one reference image is required")
        for image_path in image_paths:
            if not image_path.exists() or not image_path.is_file():
                raise ValueError(f"Reference image does not exist: {image_path}")

        with ExitStack() as stack:
            files = [
                ("image", (image_path.name, stack.enter_context(image_path.open("rb")), _image_mime_type(image_path)))
                for image_path in image_paths
            ]
            response = requests.post(
                f"{self.base_url}/images/edits",
                headers=_api_headers(self.api_key, include_content_type=False),
                data={"model": model, "prompt": prompt, "size": size, "quality": quality, "response_format": self.response_format},
                files=files,
                proxies={"http": configured_network_proxy(), "https": configured_network_proxy()} if configured_network_proxy() else None,
                timeout=180,
            )
        if response.status_code >= 400:
            raise RuntimeError(_format_openai_http_error("edit", response.status_code, response.text, self.base_url))
        response_body = response.json()
        image_data = response_body.get("data", [{}])[0]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        _write_image_result(image_data, output_path, self.base_url)
        return ImageGenerationResult(
            output_path=output_path,
            model=model,
            prompt=prompt,
            size=size,
            quality=quality,
            request_id=response.headers.get("x-request-id"),
            revised_prompt=image_data.get("revised_prompt"),
            base_url=self.base_url,
        )


def _api_headers(api_key: str, *, include_content_type: bool = True) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "User-Agent": os.environ.get("OPENAI_USER_AGENT") or DEFAULT_OPENAI_USER_AGENT,
    }
    if include_content_type:
        headers["Content-Type"] = "application/json"
    return headers


def _format_openai_http_error(operation: str, status_code: int, body: str, base_url: str) -> str:
    cleaned = " ".join((body or "").split())
    hint = ""
    if status_code == 403 and ("1010" in cleaned or "error code: 1010" in cleaned.lower()):
        hint = (
            " Hint: the OpenAI-compatible image endpoint rejected this client before the API request completed "
            "(Cloudflare/WAF code 1010). Check OPENAI_BASE_URL/network proxy, or switch the image provider to codex_oauth."
        )
    elif status_code == 524:
        hint = (
            " Hint: the OpenAI-compatible image endpoint timed out behind Cloudflare, commonly after its 120-second proxy read limit. "
            "Wait and retry, use a less loaded OPENAI_BASE_URL, or switch the image provider to codex_oauth."
        )
    return f"OpenAI image {operation} failed: {status_code} {cleaned}; base_url={base_url}.{hint}"


def _write_image_result(image_data: object, output_path: Path, base_url: str) -> None:
    if not isinstance(image_data, dict):
        raise RuntimeError(f"OpenAI-compatible image response was not an object; base_url={base_url}")

    b64_json = image_data.get("b64_json")
    if isinstance(b64_json, str) and b64_json:
        output_path.write_bytes(base64.b64decode(b64_json))
        return

    url = image_data.get("url")
    if isinstance(url, str) and url:
        if url.startswith("data:"):
            _write_data_url(url, output_path)
            return
        _download_image_url(url, output_path)
        return

    keys = ", ".join(sorted(str(key) for key in image_data.keys())) or "<none>"
    raise RuntimeError(
        "OpenAI-compatible image response did not include supported image data. "
        f"Expected data[0].b64_json or data[0].url; got keys: {keys}; base_url={base_url}"
    )


def _image_mime_type(image_path: Path) -> str:
    extension = image_path.suffix.lower()
    if extension in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if extension == ".webp":
        return "image/webp"
    return "image/png"


def _write_data_url(url: str, output_path: Path) -> None:
    try:
        _header, payload = url.split(",", 1)
    except ValueError as exc:
        raise RuntimeError("OpenAI-compatible image response included an invalid data URL") from exc
    output_path.write_bytes(base64.b64decode(payload))


def _download_image_url(url: str, output_path: Path) -> None:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        },
        method="GET",
    )
    try:
        with open_external_url(request, timeout=180) as response:
            output_path.write_bytes(response.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        with suppress(Exception):
            exc.close()
        raise RuntimeError(f"OpenAI-compatible image URL download failed: {exc.code} {body}") from exc
