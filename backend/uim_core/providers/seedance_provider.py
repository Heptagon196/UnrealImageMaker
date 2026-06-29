from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..network import open_external_url

DEFAULT_SEEDANCE_MODEL = "doubao-seedance-2-0-260128"
DEFAULT_SEEDANCE_RESOLUTION = "720p"
DEFAULT_SEEDANCE_ENDPOINT = "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks"
SEEDANCE_MODEL_ALIASES = {
    "seedance2.0": "doubao-seedance-2-0-260128",
    "seedance-2.0": "doubao-seedance-2-0-260128",
    "doubao-seedance-2-0-pro-260128": "doubao-seedance-2-0-260128",
    "seedance2.0-fast": "doubao-seedance-2-0-fast-260128",
    "seedance-2.0-fast": "doubao-seedance-2-0-fast-260128",
    "seedance2.0-mini": "doubao-seedance-2-0-mini-260615",
    "seedance-2.0-mini": "doubao-seedance-2-0-mini-260615",
    "doubao-seedance-2-0-mini-260128": "doubao-seedance-2-0-mini-260615",
}


def normalize_seedance_model(model: str | None) -> str:
    value = (model or DEFAULT_SEEDANCE_MODEL).strip()
    if not value:
        return DEFAULT_SEEDANCE_MODEL
    return SEEDANCE_MODEL_ALIASES.get(value, value)


@dataclass(slots=True)
class SeedanceResult:
    output_path: Path
    model: str
    prompt: str
    request_id: str | None = None
    events: list[str] | None = None


class SeedanceProvider:
    def __init__(self, api_key: str | None = None, endpoint: str | None = None, model: str | None = None, resolution: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("UIM_SEEDANCE_API_KEY")
        self.endpoint = (endpoint or os.environ.get("UIM_SEEDANCE_ENDPOINT") or DEFAULT_SEEDANCE_ENDPOINT).rstrip("/")
        self.model = normalize_seedance_model(model or os.environ.get("UIM_SEEDANCE_MODEL"))
        self.resolution = (resolution or os.environ.get("UIM_SEEDANCE_RESOLUTION") or DEFAULT_SEEDANCE_RESOLUTION).strip() or DEFAULT_SEEDANCE_RESOLUTION

    def is_configured(self) -> bool:
        return bool(self.api_key and self.endpoint and self.model)

    def generate_walk_video(
        self,
        anchor_path: Path,
        prompt: str,
        output_path: Path,
        *,
        seconds: int = 5,
        progress: Callable[[str], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> SeedanceResult:
        if not self.is_configured():
            raise RuntimeError("Seedance is not configured. Set Seedance API Key and endpoint in Settings.")
        if self._uses_ark_task_api() and not self.model:
            raise RuntimeError("Seedance Ark task API requires a Doubao Seedance model ID, for example doubao-seedance-2-0-fast-260128.")
        if seconds < 4 or seconds > 15:
            raise ValueError("Seedance duration must be between 4 and 15 seconds")

        # Endpoint shape is intentionally minimal/configurable: different Seedance gateways expose
        # slightly different routes, so the app expects a JSON response with video_url or video_base64.
        payload = {
            "model": self.model,
            "prompt": prompt,
            "image_path": str(anchor_path),
            "duration": seconds,
            "resolution": self.resolution,
        }
        if self._uses_ark_task_api():
            payload = self._ark_task_payload(anchor_path, prompt, seconds)
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with open_external_url(request, timeout=300) as response:
                body = json.loads(response.read().decode("utf-8"))
                request_id = response.headers.get("x-request-id") or str(body.get("request_id") or "")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Seedance generation failed: {exc.code} {detail}") from exc

        output_path.parent.mkdir(parents=True, exist_ok=True)
        if self._uses_ark_task_api():
            body = self._poll_ark_task(body, progress=progress, is_cancelled=is_cancelled)
            request_id = request_id or str(body.get("id") or body.get("task_id") or "")
        if progress:
            progress("seedance.video.download start")
        self._write_video_response(body, output_path)
        if progress:
            progress(f"seedance.video.download done path={output_path}")
        return SeedanceResult(
            output_path=output_path,
            model=str(body.get("model") or self.model),
            prompt=prompt,
            request_id=request_id or None,
            events=[str(item) for item in body.get("events", [])] if isinstance(body.get("events"), list) else [],
        )

    def _uses_ark_task_api(self) -> bool:
        return "/contents/generations/tasks" in self.endpoint

    def _ark_task_payload(self, anchor_path: Path, prompt: str, seconds: int) -> dict[str, Any]:
        import base64

        suffix = anchor_path.suffix.lower()
        mime = "image/jpeg" if suffix in {".jpg", ".jpeg"} else "image/webp" if suffix == ".webp" else "image/png"
        data_url = f"data:{mime};base64,{base64.b64encode(anchor_path.read_bytes()).decode('ascii')}"
        return {
            "model": self.model,
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
            "duration": seconds,
            "resolution": self.resolution,
            "generate_audio": False,
        }

    def _poll_ark_task(
        self,
        body: dict[str, Any],
        *,
        progress: Callable[[str], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        task_id = str(body.get("id") or body.get("task_id") or body.get("request_id") or "")
        if not task_id:
            return body
        task_url = f"{self.endpoint}/{task_id}"
        last_body = body
        if progress:
            status = str(body.get("status") or body.get("task_status") or "submitted")
            progress(f"seedance.task.submitted id={task_id} status={status} model={body.get('model') or self.model}")
        poll_count = 0
        while True:
            if is_cancelled and is_cancelled():
                raise RuntimeError(f"Seedance Ark task cancelled by user: {task_id}")
            request = urllib.request.Request(
                task_url,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                method="GET",
            )
            with open_external_url(request, timeout=60) as response:
                last_body = json.loads(response.read().decode("utf-8"))
            status = str(last_body.get("status") or last_body.get("task_status") or "").lower()
            poll_count += 1
            if progress:
                updated_at = last_body.get("updated_at") or last_body.get("updatedAt") or ""
                progress(f"seedance.task.poll count={poll_count} id={task_id} status={status or 'unknown'} updated_at={updated_at}")
            if status in {"succeeded", "success", "completed", "done"}:
                if progress:
                    progress(f"seedance.task.done id={task_id} status={status}")
                return last_body
            if status in {"failed", "error", "cancelled", "canceled"}:
                raise RuntimeError(f"Seedance Ark task failed: {json.dumps(last_body, ensure_ascii=False)[:1000]}")
            time.sleep(3)

    def _write_video_response(self, body: dict[str, Any], output_path: Path) -> None:
        import base64

        if body.get("video_base64"):
            output_path.write_bytes(base64.b64decode(str(body["video_base64"])))
            return
        url = self._find_video_url(body)
        if not url:
            raise RuntimeError("Seedance response did not include video_url or video_base64")
        request = urllib.request.Request(str(url), method="GET")
        with open_external_url(request, timeout=300) as response:
            output_path.write_bytes(response.read())

    def _find_video_url(self, body: Any) -> str:
        if isinstance(body, dict):
            for key in ("video_url", "url", "videoUrl"):
                if body.get(key):
                    return str(body[key])
            for key in ("video_urls", "urls"):
                value = body.get(key)
                if isinstance(value, list) and value:
                    return str(value[0])
            for key in ("result", "data", "output", "content"):
                found = self._find_video_url(body.get(key))
                if found:
                    return found
        if isinstance(body, list):
            for item in body:
                found = self._find_video_url(item)
                if found:
                    return found
        return ""
