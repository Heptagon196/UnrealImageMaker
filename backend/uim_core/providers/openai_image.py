from __future__ import annotations

import base64
from contextlib import ExitStack, suppress
import json
import os
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Sequence

from ..network import configured_network_proxy, open_external_url
from .stream_events import emit_stream_event

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_IMAGE_RESPONSE_FORMAT = "b64_json"
DEFAULT_OPENAI_USER_AGENT = "codex_cli_rs/0.77.0 (Windows 10.0.26100; x86_64) WindowsTerminal"


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
        self.merge_edit_images = os.environ.get("OPENAI_MERGE_EDIT_IMAGES", "1").strip().lower() not in {"0", "false", "no", "off"}

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
        retries = _openai_image_retry_count()
        for attempt in range(retries + 1):
            request = urllib.request.Request(
                f"{self.base_url}/images/generations",
                data=json.dumps(payload).encode("utf-8"),
                headers=_api_headers(self.api_key),
                method="POST",
            )
            try:
                with open_external_url(request, timeout=180) as response:
                    response_body, stream_events = _read_openai_image_response(response, self.base_url)
                    request_id = response.headers.get("x-request-id")
                    break
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                with suppress(Exception):
                    exc.close()
                if attempt < retries and _is_retryable_openai_image_error(exc.code, body):
                    continue
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
            stream_events=stream_events,
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
        mask_path: Path | None = None,
    ) -> ImageGenerationResult:
        return self.edit_many(prompt, [image_path], output_path, model=model, size=size, quality=quality, mask_path=mask_path)

    def edit_many(
        self,
        prompt: str,
        image_paths: Sequence[Path],
        output_path: Path,
        *,
        model: str = "gpt-image-2",
        size: str = "1024x1024",
        quality: str = "auto",
        mask_path: Path | None = None,
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
        if mask_path is not None and (not mask_path.exists() or not mask_path.is_file()):
            raise ValueError(f"Edit mask image does not exist: {mask_path}")

        with ExitStack() as stack:
            upload_paths = list(image_paths)
            image_field = "image[]"
            if self.merge_edit_images:
                image_field = "image"
                if len(upload_paths) > 1:
                    merged_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="uim_openai_edit_refs_")))
                    merged_path = merged_dir / "merged_reference.png"
                    _merge_edit_reference_images(upload_paths, merged_path, mask_path=mask_path)
                    upload_paths = [merged_path]
            files = [
                (image_field, (image_path.name, stack.enter_context(image_path.open("rb")), _image_mime_type(image_path)))
                for image_path in upload_paths
            ]
            if mask_path is not None:
                files.append(("mask", (mask_path.name, stack.enter_context(mask_path.open("rb")), _image_mime_type(mask_path))))
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
        response_body, stream_events = _read_openai_image_requests_response(response, self.base_url)
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
            stream_events=stream_events,
            base_url=self.base_url,
        )


def _merge_edit_reference_images(image_paths: Sequence[Path], output_path: Path, *, mask_path: Path | None = None) -> None:
    if not image_paths:
        raise ValueError("At least one reference image is required")
    Image = _require_pillow_image()
    with ExitStack() as stack:
        images = [stack.enter_context(path.open("rb")) for path in image_paths]
        opened = [Image.open(handle).convert("RGBA") for handle in images]
        first = opened[0]
        if mask_path is not None:
            merged = first.copy()
            if len(opened) > 1:
                from PIL import ImageDraw

                draw = ImageDraw.Draw(merged)
                padding = max(8, min(first.size) // 64)
                thumb_height = max(32, first.height // 5)
                thumb_width = max(32, first.width // 5)
                x = first.width - padding
                y = padding
                for index, reference in enumerate(opened[1:], start=2):
                    thumb = _contain_image(reference, (thumb_width, thumb_height))
                    x -= thumb.width
                    if x < padding:
                        x = first.width - padding - thumb.width
                        y += thumb_height + padding * 2
                    if y + thumb.height + padding >= first.height:
                        break
                    draw.rectangle((x - padding // 2, y - padding // 2, x + thumb.width + padding // 2, y + thumb.height + padding // 2), fill=(255, 255, 255, 220))
                    merged.alpha_composite(thumb, (x, y))
                    draw.text((x, y + thumb.height + 2), f"ref {index}", fill=(24, 27, 33, 255))
                    x -= padding
        else:
            cell_width, cell_height = first.size
            merged = Image.new("RGBA", (cell_width * len(opened), cell_height), (255, 255, 255, 255))
            for index, reference in enumerate(opened):
                merged.alpha_composite(_contain_image(reference, (cell_width, cell_height)), (index * cell_width, 0))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    merged.save(output_path)


def _contain_image(image: Any, size: tuple[int, int]) -> Any:
    Image = _require_pillow_image()
    target_width, target_height = size
    source = image.convert("RGBA")
    ratio = min(target_width / max(1, source.width), target_height / max(1, source.height))
    width = max(1, int(round(source.width * ratio)))
    height = max(1, int(round(source.height * ratio)))
    resized = source.resize((width, height), getattr(getattr(Image, "Resampling", Image), "LANCZOS"))
    output = Image.new("RGBA", (target_width, target_height), (255, 255, 255, 255))
    output.alpha_composite(resized, ((target_width - width) // 2, (target_height - height) // 2))
    return output


def _require_pillow_image():
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is required for merged image edit uploads") from exc
    return Image


def _api_headers(api_key: str, *, include_content_type: bool = True, accept: str = "application/json") -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": accept,
        "User-Agent": os.environ.get("OPENAI_USER_AGENT") or DEFAULT_OPENAI_USER_AGENT,
    }
    if include_content_type:
        headers["Content-Type"] = "application/json"
    return headers


def _openai_image_retry_count() -> int:
    raw = os.environ.get("UIM_OPENAI_IMAGE_RETRIES", "1").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 1


def _is_retryable_openai_image_error(status_code: int, body: str) -> bool:
    if status_code in {408, 409, 429, 500, 502, 503, 504, 524}:
        return True
    cleaned = (body or "").lower()
    return "retryable" in cleaned and "true" in cleaned


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


def _read_openai_image_response(response: Any, base_url: str) -> tuple[dict[str, Any], list[str]]:
    first_line = response.readline()
    if _looks_like_sse_line(first_line, response):
        return _read_openai_image_sse_response(response, base_url, first_line)
    text = first_line.decode("utf-8", errors="replace") + response.read().decode("utf-8", errors="replace")
    return _read_openai_image_text(text, base_url)


def _read_openai_image_requests_response(response: Any, base_url: str) -> tuple[dict[str, Any], list[str]]:
    iter_lines = getattr(response, "iter_lines", None)
    if not callable(iter_lines):
        return _read_openai_image_text(str(getattr(response, "text", "")), base_url)
    lines = iter_lines(decode_unicode=True)
    try:
        first_line = next(lines)
    except StopIteration:
        return _read_openai_image_text(str(getattr(response, "text", "")), base_url)
    first_text = first_line if isinstance(first_line, str) else first_line.decode("utf-8", errors="replace")
    if _looks_like_sse_text(first_text, response):
        return _read_openai_image_sse_lines(_chain_first_line(first_text, lines), base_url)
    remaining = [first_text]
    for line in lines:
        remaining.append(line if isinstance(line, str) else line.decode("utf-8", errors="replace"))
    return _read_openai_image_text("\n".join(remaining), base_url)


def _read_openai_image_text(text: str, base_url: str) -> tuple[dict[str, Any], list[str]]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        events = list(_iter_sse_json_events(text))
        stream_events = [_summarize_openai_image_event(event) for event in events]
        for event in events:
            image_data = _image_data_from_stream_event(event)
            if image_data:
                return {"data": [image_data]}, stream_events
        raise RuntimeError(
            "OpenAI-compatible streamed image response did not include supported image data. "
            f"base_url={base_url}"
        )
    if not isinstance(parsed, dict):
        raise RuntimeError(f"OpenAI-compatible image response was not an object; base_url={base_url}")
    return parsed, []


def _looks_like_sse_line(first_line: bytes, response: Any) -> bool:
    return _looks_like_sse_text(first_line.decode("utf-8", errors="replace"), response)


def _looks_like_sse_text(first_line: str, response: Any) -> bool:
    content_type = ""
    headers = getattr(response, "headers", None)
    if headers is not None:
        content_type = str(headers.get("content-type") or headers.get("Content-Type") or "")
    if "text/event-stream" in content_type.lower():
        return True
    line = first_line.lstrip()
    return line.startswith("data:") or line.startswith("event:") or line.startswith(":")


def _read_openai_image_sse_response(response: Any, base_url: str, first_line: bytes = b"") -> tuple[dict[str, Any], list[str]]:
    return _read_openai_image_sse_lines(_iter_response_lines(response, first_line), base_url)


def _read_openai_image_sse_lines(lines: Iterator[str], base_url: str) -> tuple[dict[str, Any], list[str]]:
    image_data: dict[str, Any] | None = None
    stream_events: list[str] = []
    for event in _iter_sse_json_events_from_lines(lines):
        summary = _summarize_openai_image_event(event)
        if summary:
            stream_events.append(summary)
            emit_stream_event(summary)
        event_image_data = _image_data_from_stream_event(event)
        if event_image_data:
            image_data = event_image_data
            if "image_generation_call.result" not in stream_events:
                stream_events.append("image_generation_call.result")
                emit_stream_event("image_generation_call.result")
    if image_data:
        return {"data": [image_data]}, stream_events[:80]
    raise RuntimeError(
        "OpenAI-compatible streamed image response did not include supported image data. "
        f"base_url={base_url}"
    )


def _chain_first_line(first_line: str, lines: Iterator[Any]) -> Iterator[str]:
    yield first_line.rstrip("\r\n")
    for line in lines:
        text = line if isinstance(line, str) else line.decode("utf-8", errors="replace")
        yield text.rstrip("\r\n")


def _iter_response_lines(response: Any, first_line: bytes = b"") -> Iterator[str]:
    if first_line:
        yield first_line.decode("utf-8", errors="replace").rstrip("\r\n")
    for raw_line in iter(response.readline, b""):
        yield raw_line.decode("utf-8", errors="replace").rstrip("\r\n")


def _iter_sse_json_events_from_lines(lines: Iterator[str]) -> Iterator[dict[str, Any]]:
    event_name = ""
    data_lines: list[str] = []

    def flush() -> dict[str, Any] | None:
        nonlocal event_name, data_lines
        payload = "\n".join(data_lines).strip()
        data_lines = []
        if not payload or payload == "[DONE]":
            event_name = ""
            return None
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            event_name = ""
            return None
        if isinstance(parsed, dict):
            if event_name and "type" not in parsed:
                parsed["_event"] = event_name
            event_name = ""
            return parsed
        event_name = ""
        return None

    for line in lines:
        if line == "":
            event = flush()
            if event is not None:
                yield event
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip()
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].strip())
    event = flush()
    if event is not None:
        yield event


def _iter_sse_json_events(text: str) -> Iterator[dict[str, Any]]:
    yield from _iter_sse_json_events_from_lines(iter(text.splitlines()))


def _summarize_openai_image_event(event: dict[str, Any]) -> str:
    event_type = str(event.get("type") or event.get("_event") or "message")
    if event_type == "response.output_item.done":
        item = event.get("item")
        if isinstance(item, dict):
            return f"response.output_item.done item={item.get('type') or '-'} status={item.get('status') or '-'}"
    if event_type == "response.completed":
        response = event.get("response")
        if isinstance(response, dict):
            return f"response.completed status={response.get('status') or '-'} model={response.get('model') or '-'}"
    return event_type


def _image_data_from_stream_event(event: dict[str, Any]) -> dict[str, Any] | None:
    candidates: list[Any] = [event]
    for key in ("response", "item", "result"):
        value = event.get(key)
        if isinstance(value, dict):
            candidates.append(value)
    for candidate in candidates:
        image_data = _image_data_from_candidate(candidate)
        if image_data:
            return image_data
    return None


def _image_data_from_candidate(candidate: dict[str, Any]) -> dict[str, Any] | None:
    data = candidate.get("data")
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                image_data = _image_data_from_candidate(item)
                if image_data:
                    return image_data

    b64_json = candidate.get("b64_json")
    if isinstance(b64_json, str) and b64_json:
        return {"b64_json": b64_json, "revised_prompt": candidate.get("revised_prompt")}

    url = candidate.get("url")
    if isinstance(url, str) and url:
        return {"url": url, "revised_prompt": candidate.get("revised_prompt")}

    result = candidate.get("result")
    if isinstance(result, str) and result:
        return {"b64_json": result}
    if isinstance(result, dict):
        image_data = _image_data_from_candidate(result)
        if image_data:
            return image_data

    for key in ("output", "content"):
        items = candidate.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict):
                image_data = _image_data_from_candidate(item)
                if image_data:
                    return image_data
    return None


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
