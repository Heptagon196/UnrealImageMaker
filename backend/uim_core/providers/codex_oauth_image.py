from __future__ import annotations

import base64
from contextlib import contextmanager
from contextvars import ContextVar
import io
import hashlib
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

from ..json_io import read_json, write_json
from ..network import configured_network_proxy, open_external_url
from ..paths import user_data_dir
from .openai_image import ImageGenerationResult

OPENAI_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OPENAI_OAUTH_AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
OPENAI_OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
OPENAI_OAUTH_REDIRECT_URI = "http://localhost:1455/auth/callback"
OPENAI_OAUTH_SCOPE = "openid profile email offline_access"
OPENAI_OAUTH_ACCOUNT_CLAIM_PATH = "https://api.openai.com/auth"
CODEX_RESPONSES_URL = "https://chatgpt.com/backend-api/codex/responses"
CODEX_IMAGE_MODEL = "gpt-5.5"
_stream_event_callback: ContextVar[Callable[[str], None] | None] = ContextVar("codex_stream_event_callback", default=None)


def codex_oauth_store_path() -> Path:
    return user_data_dir() / "codex-oauth.json"


@contextmanager
def codex_stream_events(callback: Callable[[str], None] | None) -> Iterator[None]:
    token = _stream_event_callback.set(callback)
    try:
        yield
    finally:
        _stream_event_callback.reset(token)


def _emit_stream_event(summary: str) -> None:
    callback = _stream_event_callback.get()
    if callback and summary:
        callback(summary)


def create_pkce_flow(redirect_uri: str | None = None) -> dict[str, str]:
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    callback_uri = redirect_uri or OPENAI_OAUTH_REDIRECT_URI
    return {
        "state": state,
        "verifier": verifier,
        "challenge": challenge,
        "redirect_uri": callback_uri,
        "authorize_url": build_authorize_url(state, challenge, callback_uri),
    }


def build_authorize_url(state: str, challenge: str, redirect_uri: str | None = None) -> str:
    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": OPENAI_OAUTH_CLIENT_ID,
            "redirect_uri": redirect_uri or OPENAI_OAUTH_REDIRECT_URI,
            "scope": OPENAI_OAUTH_SCOPE,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
            "id_token_add_organizations": "true",
            "codex_cli_simplified_flow": "true",
            "originator": "codex_cli_rs",
        }
    )
    return f"{OPENAI_OAUTH_AUTHORIZE_URL}?{query}"


def parse_authorization_input(raw: str) -> tuple[str, str]:
    value = (raw or "").strip()
    if not value:
        raise ValueError("OAuth callback is empty")
    if "code=" in value:
        parsed = urllib.parse.urlparse(value)
        query_string = parsed.query or parsed.path
        query = urllib.parse.parse_qs(query_string)
        return query.get("code", [""])[0].strip(), query.get("state", [""])[0].strip()
    if "#" in value:
        code, state = value.split("#", 1)
        return code.strip(), state.strip()
    return value, ""


def load_codex_oauth_tokens() -> dict[str, Any]:
    path = codex_oauth_store_path()
    if not path.exists():
        return {}
    data = read_json(path)
    return data if isinstance(data, dict) else {}


def save_codex_oauth_tokens(tokens: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_token_payload(tokens)
    if not normalized.get("access_token"):
        raise ValueError("OAuth credentials must include access_token")
    write_json(codex_oauth_store_path(), normalized)
    return normalized


def delete_codex_oauth_tokens() -> None:
    path = codex_oauth_store_path()
    if path.exists():
        path.unlink()


def codex_oauth_status() -> dict[str, Any]:
    tokens = load_codex_oauth_tokens()
    return safe_token_status(tokens)


def safe_token_status(tokens: dict[str, Any]) -> dict[str, Any]:
    return {
        "configured": bool(tokens.get("access_token") and tokens.get("account_id")),
        "email": tokens.get("email", ""),
        "accountId": tokens.get("account_id", ""),
        "expiresAt": tokens.get("expires_at", ""),
        "hasRefreshToken": bool(tokens.get("refresh_token")),
        "storePath": str(codex_oauth_store_path()),
    }


def complete_codex_oauth(
    callback_input: str,
    verifier: str,
    expected_state: str = "",
    redirect_uri: str | None = None,
) -> dict[str, Any]:
    imported = parse_oauth_credential_json(callback_input)
    if imported:
        return save_codex_oauth_tokens(imported)
    code, state = parse_authorization_input(callback_input)
    if not code:
        raise ValueError("OAuth callback does not contain code")
    if expected_state and state and state != expected_state:
        raise ValueError("OAuth state mismatch")
    return exchange_authorization_code(code, verifier, redirect_uri)


def parse_oauth_credential_json(raw: str) -> dict[str, Any] | None:
    value = (raw or "").strip()
    if not value.startswith("{"):
        return None
    data = json.loads(value)
    if not isinstance(data, dict):
        raise ValueError("OAuth credential JSON must be an object")
    return normalize_token_payload(data)


def exchange_authorization_code(code: str, verifier: str, redirect_uri: str | None = None) -> dict[str, Any]:
    payload = {
        "grant_type": "authorization_code",
        "client_id": OPENAI_OAUTH_CLIENT_ID,
        "code": code.strip(),
        "code_verifier": verifier.strip(),
        "redirect_uri": redirect_uri or OPENAI_OAUTH_REDIRECT_URI,
    }
    tokens = request_oauth_tokens(payload)
    return save_codex_oauth_tokens(tokens)


def refresh_codex_oauth_tokens() -> dict[str, Any]:
    current = load_codex_oauth_tokens()
    refresh_token = str(current.get("refresh_token") or "")
    if not refresh_token:
        raise ValueError("Codex OAuth refresh_token is not configured")
    tokens = request_oauth_tokens(
        {
            "grant_type": "refresh_token",
            "client_id": OPENAI_OAUTH_CLIENT_ID,
            "refresh_token": refresh_token,
        }
    )
    if not tokens.get("refresh_token"):
        tokens["refresh_token"] = refresh_token
    return save_codex_oauth_tokens(tokens)


def request_oauth_tokens(payload: dict[str, str]) -> dict[str, Any]:
    encoded = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(
        OPENAI_OAUTH_TOKEN_URL,
        data=encoded,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with open_external_url(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if exc.code == 403 and "unsupported_country_region_territory" in body:
            raise RuntimeError(
                "OpenAI 拒绝了当前网络出口的 OAuth token 请求：当前国家、地区或网络出口不受支持。"
                f"如果浏览器授权页能正常打开，但软件换取 token 失败，请在设置里配置后端网络代理后重新绑定。当前代理：{configured_network_proxy() or '未配置'}"
            ) from exc
        raise RuntimeError(f"Codex OAuth token request failed: {exc.code} {body}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("Codex OAuth token response is not an object")
    return normalize_token_payload(data)


def normalize_token_payload(data: dict[str, Any]) -> dict[str, Any]:
    access_token = str(data.get("access_token") or data.get("oauth_access_token") or "").strip()
    refresh_token = str(data.get("refresh_token") or data.get("oauth_refresh_token") or "").strip()
    expires_at = normalize_expires_at(data)
    account_id = str(data.get("account_id") or data.get("oauth_account_id") or "").strip()
    email = str(data.get("email") or data.get("oauth_account_email") or "").strip()
    if access_token:
        account_id = account_id or extract_account_id_from_jwt(access_token)
        email = email or extract_email_from_jwt(access_token)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
        "email": email,
        "account_id": account_id,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }


def normalize_expires_at(data: dict[str, Any]) -> str:
    expires_at = data.get("expires_at") or data.get("oauth_expires_at")
    if isinstance(expires_at, str) and expires_at.strip():
        return expires_at.strip()
    expires_at = data.get("expired") or data.get("expires")
    if isinstance(expires_at, (int, float)):
        return datetime.fromtimestamp(float(expires_at), timezone.utc).isoformat()
    expires_in = data.get("expires_in")
    if isinstance(expires_in, (int, float)) or (isinstance(expires_in, str) and expires_in.isdigit()):
        return datetime.fromtimestamp(time.time() + float(expires_in), timezone.utc).isoformat()
    return ""


def token_needs_refresh(tokens: dict[str, Any]) -> bool:
    expires_at = str(tokens.get("expires_at") or "")
    if not expires_at:
        return False
    try:
        normalized = expires_at.replace("Z", "+00:00")
        expires = datetime.fromisoformat(normalized)
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return expires.timestamp() - time.time() < 120
    except ValueError:
        return False


def decode_jwt_claims(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1] + ("=" * (-len(parts[1]) % 4))
    try:
        decoded = base64.urlsafe_b64decode(payload.encode("ascii"))
        data = json.loads(decoded.decode("utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def extract_email_from_jwt(token: str) -> str:
    email = decode_jwt_claims(token).get("email")
    return email.strip() if isinstance(email, str) else ""


def extract_account_id_from_jwt(token: str) -> str:
    claims = decode_jwt_claims(token)
    auth = claims.get(OPENAI_OAUTH_ACCOUNT_CLAIM_PATH)
    if isinstance(auth, dict):
        account_id = auth.get("chatgpt_account_id")
        if isinstance(account_id, str):
            return account_id.strip()
    account_id = claims.get("chatgpt_account_id")
    return account_id.strip() if isinstance(account_id, str) else ""


class CodexOAuthImageProvider:
    def __init__(self, token_path: Path | None = None) -> None:
        self.token_path = token_path or codex_oauth_store_path()

    def is_configured(self) -> bool:
        tokens = self._load_tokens()
        return bool(tokens.get("access_token") and tokens.get("account_id"))

    def status(self) -> dict[str, Any]:
        return safe_token_status(self._load_tokens())

    def generate(
        self,
        prompt: str,
        output_path: Path,
        *,
        model: str = CODEX_IMAGE_MODEL,
        size: str = "1024x1024",
        quality: str = "auto",
    ) -> ImageGenerationResult:
        tokens = self._load_fresh_tokens()
        access_token = str(tokens.get("access_token") or "")
        account_id = str(tokens.get("account_id") or "")
        if not access_token or not account_id:
            raise RuntimeError("Codex OAuth is not configured")

        payload = {
            "model": model,
            "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            "tools": [
                {
                    "type": "image_generation",
                    "size": size,
                    "quality": quality,
                    "output_format": "png",
                }
            ],
            "tool_choice": {"type": "image_generation"},
            "store": False,
            "stream": True,
        }
        request = urllib.request.Request(
            CODEX_RESPONSES_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {access_token}",
                "ChatGPT-Account-Id": account_id,
                "OpenAI-Beta": "responses=experimental",
                "originator": "codex_cli_rs",
                "Accept": "text/event-stream",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with open_external_url(request, timeout=240) as response:
                image_b64, stream_events = read_codex_sse_response(response)
                request_id = response.headers.get("x-request-id")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Codex image generation failed: {exc.code} {body}") from exc

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(base64.b64decode(image_b64))
        return ImageGenerationResult(
            output_path=output_path,
            model=f"codex-oauth:{model}",
            prompt=prompt,
            size=size,
            quality=quality,
            request_id=request_id,
            stream_events=stream_events,
        )

    def edit(
        self,
        prompt: str,
        image_path: Path,
        output_path: Path,
        *,
        model: str = CODEX_IMAGE_MODEL,
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
        model: str = CODEX_IMAGE_MODEL,
        size: str = "1024x1024",
        quality: str = "auto",
    ) -> ImageGenerationResult:
        tokens = self._load_fresh_tokens()
        access_token = str(tokens.get("access_token") or "")
        account_id = str(tokens.get("account_id") or "")
        if not access_token or not account_id:
            raise RuntimeError("Codex OAuth is not configured")
        if not image_paths:
            raise ValueError("At least one reference image is required")

        content: list[dict[str, str]] = [{"type": "input_text", "text": prompt}]
        for image_path in image_paths:
            if not image_path.exists() or not image_path.is_file():
                raise ValueError(f"Reference image does not exist: {image_path}")
            image_b64_input = base64.b64encode(image_path.read_bytes()).decode("ascii")
            image_url = f"data:{_image_mime_type(image_path)};base64,{image_b64_input}"
            content.append({"type": "input_image", "image_url": image_url})
        payload = {
            "model": model,
            "input": [
                {
                    "role": "user",
                    "content": content,
                }
            ],
            "tools": [
                {
                    "type": "image_generation",
                    "size": size,
                    "quality": quality,
                    "output_format": "png",
                }
            ],
            "tool_choice": {"type": "image_generation"},
            "store": False,
            "stream": True,
        }
        request = urllib.request.Request(
            CODEX_RESPONSES_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {access_token}",
                "ChatGPT-Account-Id": account_id,
                "OpenAI-Beta": "responses=experimental",
                "originator": "codex_cli_rs",
                "Accept": "text/event-stream",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with open_external_url(request, timeout=240) as response:
                image_b64, stream_events = read_codex_sse_response(response)
                request_id = response.headers.get("x-request-id")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Codex image edit failed: {exc.code} {body}") from exc

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(base64.b64decode(image_b64))
        return ImageGenerationResult(
            output_path=output_path,
            model=f"codex-oauth:{model}",
            prompt=prompt,
            size=size,
            quality=quality,
            request_id=request_id,
            stream_events=stream_events,
        )

    def _load_tokens(self) -> dict[str, Any]:
        if not self.token_path.exists():
            return {}
        data = read_json(self.token_path)
        return data if isinstance(data, dict) else {}

    def _load_fresh_tokens(self) -> dict[str, Any]:
        tokens = self._load_tokens()
        if token_needs_refresh(tokens) and tokens.get("refresh_token"):
            return refresh_codex_oauth_tokens()
        return tokens


def _image_mime_type(image_path: Path) -> str:
    extension = image_path.suffix.lower()
    if extension in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if extension == ".webp":
        return "image/webp"
    return "image/png"


def parse_image_result_from_sse(text: str) -> str:
    for event in parse_sse_json_events(text):
        image = extract_image_result(event)
        if image:
            return image
    image = extract_image_result_from_json(text)
    if image:
        return image
    raise RuntimeError("Codex response did not include image_generation result")


def read_codex_sse_response(response: Any) -> tuple[str, list[str]]:
    image_b64 = ""
    summaries: list[str] = []
    for event in iter_sse_json_events(response):
        summary = summarize_sse_event(event)
        if summary:
            summaries.append(summary)
            _emit_stream_event(summary)
        image = extract_image_result(event)
        if image:
            image_b64 = image
            if "image_generation_call.result" not in summaries:
                summaries.append("image_generation_call.result")
                _emit_stream_event("image_generation_call.result")
    if not image_b64:
        raise RuntimeError(f"Codex response did not include image_generation result. Events: {summaries[:24]}")
    return image_b64, summaries[:80]


def iter_sse_json_events(response: Any) -> Iterator[dict[str, Any]]:
    event_name = ""
    data_lines: list[str] = []

    def flush() -> dict[str, Any] | None:
        nonlocal event_name, data_lines
        if not data_lines:
            event_name = ""
            return None
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

    for raw_line in iter(response.readline, b""):
        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
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


def summarize_sse_event(event: dict[str, Any]) -> str:
    event_type = str(event.get("type") or event.get("_event") or "message")
    if event_type == "response.completed":
        response = event.get("response")
        if isinstance(response, dict):
            status = response.get("status")
            model = response.get("model")
            return f"response.completed status={status or '-'} model={model or '-'}"
    if event_type == "response.output_item.done":
        item = event.get("item")
        if isinstance(item, dict):
            return f"response.output_item.done item={item.get('type') or '-'} status={item.get('status') or '-'}"
    if event_type == "response.output_text.done":
        text = str(event.get("text") or "")
        return f"response.output_text.done chars={len(text)}"
    if event_type == "image_generation_call":
        return "image_generation_call"
    if "image_generation" in event_type:
        return event_type
    return event_type


def parse_sse_json_events(text: str) -> list[dict[str, Any]]:
    return list(iter_sse_json_events(io.BytesIO(text.encode("utf-8"))))




def extract_image_result_from_json(text: str) -> str:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return ""
    return extract_image_result(parsed) if isinstance(parsed, dict) else ""


def extract_image_result(event: dict[str, Any]) -> str:
    candidates: list[Any] = [event]
    response = event.get("response")
    if isinstance(response, dict):
        candidates.append(response)
    item = event.get("item")
    if isinstance(item, dict):
        candidates.append(item)
    for candidate in candidates:
        image = image_result_from_candidate(candidate)
        if image:
            return image
    return ""


def image_result_from_candidate(candidate: dict[str, Any]) -> str:
    if candidate.get("type") == "image_generation_call":
        result = candidate.get("result")
        if isinstance(result, str) and result:
            return result
    output = candidate.get("output")
    if isinstance(output, list):
        for item in output:
            if isinstance(item, dict):
                image = image_result_from_candidate(item)
                if image:
                    return image
    content = candidate.get("content")
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            image = image_result_from_candidate(item)
            if image:
                return image
    result = candidate.get("result")
    return result if isinstance(result, str) and result else ""
