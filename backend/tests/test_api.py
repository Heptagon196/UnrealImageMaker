from __future__ import annotations

import sys
import asyncio
import json
import os
import io
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from uim_core import mcp_game_ui
from uim_core.api import (
    AssetSettingsRequest,
    AssetVersionOrderRequest,
    ProcessingQueueRequest,
    RuntimeSettingsRequest,
    WorkflowSlotsRequest,
    _apply_saved_runtime_settings,
    _shutdown_codex_oauth_callback_server,
    api_asset_preview,
    api_codex_oauth_start,
    api_delete_asset,
    api_delete_asset_version,
    api_game_ui_dsl_prompt,
    api_list_project_assets,
    api_list_models,
    api_project_workspace,
    api_reorder_asset_versions,
    api_runtime_settings,
    api_update_asset_settings,
    api_update_processing_queue,
    api_unreal_mcp_status,
    api_update_runtime_settings,
    api_update_workflow_slots,
    health,
    app,
)
from uim_core.constants import API_CONTRACT_VERSION, APP_VERSION
from uim_core.providers.codex_oauth_image import CodexOAuthImageProvider, codex_stream_events, parse_authorization_input, read_codex_sse_response, safe_token_status
from uim_core.providers.openai_image import DEFAULT_OPENAI_BASE_URL, OpenAIImageProvider
from uim_core.providers.seedance_provider import DEFAULT_SEEDANCE_ENDPOINT


class _FakeCodexResponse(io.BytesIO):
    def __init__(self, image_b64: str) -> None:
        stream = "\n".join(
            [
                "event: response.output_item.done",
                f'data: {{"type":"response.output_item.done","item":{{"type":"image_generation_call","status":"completed","result":"{image_b64}"}}}}',
                "",
            ]
        ).encode("utf-8")
        super().__init__(stream)
        self.headers = {"x-request-id": "req-test"}

    def __enter__(self) -> "_FakeCodexResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class _TrackingSseStream:
    def __init__(self, lines: list[bytes]) -> None:
        self.lines = lines
        self.index = 0

    def readline(self) -> bytes:
        if self.index >= len(self.lines):
            return b""
        line = self.lines[self.index]
        self.index += 1
        return line


class _FakeOpenAIResponse(io.BytesIO):
    def __init__(self, body: bytes = b'{"data":[{"b64_json":"aW1hZ2U="}]}') -> None:
        super().__init__(body)
        self.headers = {"x-request-id": "req-compatible"}

    def __enter__(self) -> "_FakeOpenAIResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class ApiTests(unittest.TestCase):
    def test_health_accepts_cors_preflight(self) -> None:
        messages: list[dict[str, object]] = []

        async def receive() -> dict[str, object]:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: dict[str, object]) -> None:
            messages.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "OPTIONS",
            "scheme": "http",
            "path": "/health",
            "raw_path": b"/health",
            "query_string": b"",
            "headers": [
                (b"origin", b"http://localhost:5173"),
                (b"access-control-request-method", b"GET"),
            ],
            "client": ("127.0.0.1", 5173),
            "server": ("127.0.0.1", 8765),
        }
        asyncio.run(app(scope, receive, send))
        start = next(message for message in messages if message["type"] == "http.response.start")
        headers = dict(start["headers"])  # type: ignore[arg-type]
        self.assertEqual(start["status"], 200)
        self.assertEqual(headers[b"access-control-allow-origin"], b"http://localhost:5173")

    def test_health_reports_api_contract_version(self) -> None:
        result = health()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["appVersion"], APP_VERSION)
        self.assertEqual(result["apiContractVersion"], API_CONTRACT_VERSION)

    def test_runtime_settings_reports_safe_state(self) -> None:
        previous = os.environ.pop("OPENAI_API_KEY", None)
        previous_base = os.environ.pop("OPENAI_BASE_URL", None)
        try:
            with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}, clear=False):
                settings = api_runtime_settings()
                self.assertIn("modelCacheDir", settings)
                self.assertIn("codexOAuth", settings)
                self.assertFalse(settings["hasOpenAiApiKey"])
                self.assertEqual(settings["openAiBaseUrl"], DEFAULT_OPENAI_BASE_URL)
                self.assertEqual(settings["seedanceEndpoint"], DEFAULT_SEEDANCE_ENDPOINT)
                updated = api_update_runtime_settings(RuntimeSettingsRequest(openai_api_key="test-key", openai_base_url="https://compatible.example/v1/"))
                self.assertTrue(updated["hasOpenAiApiKey"])
                self.assertEqual(updated["openAiBaseUrl"], "https://compatible.example/v1")
                self.assertEqual(OpenAIImageProvider().base_url, "https://compatible.example/v1")
        finally:
            if previous is not None:
                os.environ["OPENAI_API_KEY"] = previous
            else:
                os.environ.pop("OPENAI_API_KEY", None)
            if previous_base is not None:
                os.environ["OPENAI_BASE_URL"] = previous_base
            else:
                os.environ.pop("OPENAI_BASE_URL", None)

    def test_runtime_settings_persists_openai_base_url(self) -> None:
        previous = os.environ.pop("OPENAI_BASE_URL", None)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}, clear=False):
            try:
                updated = api_update_runtime_settings(RuntimeSettingsRequest(openai_base_url="https://compatible.example/v1"))
                self.assertEqual(updated["openAiBaseUrl"], "https://compatible.example/v1")
                os.environ.pop("OPENAI_BASE_URL", None)
                _apply_saved_runtime_settings()
                self.assertEqual(os.environ.get("OPENAI_BASE_URL"), "https://compatible.example/v1")
            finally:
                if previous is not None:
                    os.environ["OPENAI_BASE_URL"] = previous
                else:
                    os.environ.pop("OPENAI_BASE_URL", None)

    def test_runtime_settings_persists_openai_api_key(self) -> None:
        previous = os.environ.pop("OPENAI_API_KEY", None)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}, clear=False):
            try:
                updated = api_update_runtime_settings(RuntimeSettingsRequest(openai_api_key="test-key"))
                self.assertTrue(updated["hasOpenAiApiKey"])
                os.environ.pop("OPENAI_API_KEY", None)
                _apply_saved_runtime_settings()
                self.assertEqual(os.environ.get("OPENAI_API_KEY"), "test-key")
                self.assertTrue(api_runtime_settings()["hasOpenAiApiKey"])
            finally:
                if previous is not None:
                    os.environ["OPENAI_API_KEY"] = previous
                else:
                    os.environ.pop("OPENAI_API_KEY", None)

    def test_runtime_settings_persists_seedance_api_key(self) -> None:
        previous = os.environ.pop("UIM_SEEDANCE_API_KEY", None)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}, clear=False):
            try:
                updated = api_update_runtime_settings(RuntimeSettingsRequest(seedance_api_key="seedance-test-key"))
                self.assertTrue(updated["hasSeedanceApiKey"])
                os.environ.pop("UIM_SEEDANCE_API_KEY", None)
                _apply_saved_runtime_settings()
                self.assertEqual(os.environ.get("UIM_SEEDANCE_API_KEY"), "seedance-test-key")
                self.assertTrue(api_runtime_settings()["hasSeedanceApiKey"])
            finally:
                if previous is not None:
                    os.environ["UIM_SEEDANCE_API_KEY"] = previous
                else:
                    os.environ.pop("UIM_SEEDANCE_API_KEY", None)

    def test_runtime_settings_persists_seedance_model(self) -> None:
        previous = os.environ.pop("UIM_SEEDANCE_MODEL", None)
        previous_resolution = os.environ.pop("UIM_SEEDANCE_RESOLUTION", None)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}, clear=False):
            try:
                updated = api_update_runtime_settings(RuntimeSettingsRequest(seedance_model="seedance-2.0-fast", seedance_resolution="480p"))
                self.assertEqual(updated["seedanceModel"], "doubao-seedance-2-0-fast-260128")
                self.assertEqual(updated["seedanceResolution"], "480p")
                os.environ.pop("UIM_SEEDANCE_MODEL", None)
                os.environ.pop("UIM_SEEDANCE_RESOLUTION", None)
                _apply_saved_runtime_settings()
                self.assertEqual(os.environ.get("UIM_SEEDANCE_MODEL"), "doubao-seedance-2-0-fast-260128")
                self.assertEqual(os.environ.get("UIM_SEEDANCE_RESOLUTION"), "480p")
                self.assertEqual(api_runtime_settings()["seedanceModel"], "doubao-seedance-2-0-fast-260128")
                self.assertEqual(api_runtime_settings()["seedanceResolution"], "480p")
            finally:
                if previous is not None:
                    os.environ["UIM_SEEDANCE_MODEL"] = previous
                else:
                    os.environ.pop("UIM_SEEDANCE_MODEL", None)
                if previous_resolution is not None:
                    os.environ["UIM_SEEDANCE_RESOLUTION"] = previous_resolution
                else:
                    os.environ.pop("UIM_SEEDANCE_RESOLUTION", None)

    def test_openai_provider_uses_configured_base_url_for_generation(self) -> None:
        captured: dict[str, object] = {}

        def fake_open_external_url(request, timeout: int):
            captured["url"] = request.full_url
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            captured["headers"] = dict(request.header_items())
            captured["timeout"] = timeout
            return _FakeOpenAIResponse()

        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"OPENAI_API_KEY": "test-key", "OPENAI_BASE_URL": "https://compatible.example/v1"}, clear=False), patch(
            "uim_core.providers.openai_image.open_external_url", fake_open_external_url
        ):
            output = Path(tmp) / "image.png"
            result = OpenAIImageProvider().generate("test", output)
            self.assertEqual(output.read_bytes(), b"image")

        self.assertEqual(captured["url"], "https://compatible.example/v1/images/generations")
        self.assertEqual(captured["payload"]["response_format"], "b64_json")  # type: ignore[index]
        self.assertIn("UnrealImageMaker/", str(captured["headers"].get("User-agent", "")))  # type: ignore[union-attr]
        self.assertEqual(result.base_url, "https://compatible.example/v1")

    def test_openai_provider_reports_cloudflare_1010_hint(self) -> None:
        def fake_open_external_url(_request, timeout: int):
            raise urllib.error.HTTPError("https://compatible.example/v1/images/generations", 403, "Forbidden", {}, io.BytesIO(b"error code: 1010"))

        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"OPENAI_API_KEY": "test-key", "OPENAI_BASE_URL": "https://compatible.example/v1"}, clear=False), patch(
            "uim_core.providers.openai_image.open_external_url", fake_open_external_url
        ):
            output = Path(tmp) / "image.png"
            with self.assertRaisesRegex(RuntimeError, r"Cloudflare/WAF code 1010.*codex_oauth"):
                OpenAIImageProvider().generate("test", output)

    def test_openai_provider_reports_cloudflare_524_hint(self) -> None:
        def fake_open_external_url(_request, timeout: int):
            raise urllib.error.HTTPError("https://compatible.example/v1/images/generations", 524, "Timeout", {}, io.BytesIO(b'{"error_code":524,"retryable":true,"retry_after":120}'))

        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"OPENAI_API_KEY": "test-key", "OPENAI_BASE_URL": "https://compatible.example/v1"}, clear=False), patch(
            "uim_core.providers.openai_image.open_external_url", fake_open_external_url
        ):
            output = Path(tmp) / "image.png"
            with self.assertRaisesRegex(RuntimeError, r"timed out behind Cloudflare.*codex_oauth"):
                OpenAIImageProvider().generate("test", output)

    def test_openai_provider_accepts_data_url_image_result(self) -> None:
        def fake_open_external_url(_request, timeout: int):
            return _FakeOpenAIResponse(b'{"data":[{"url":"data:image/png;base64,aW1hZ2U="}]}')

        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"OPENAI_API_KEY": "test-key", "OPENAI_BASE_URL": "https://compatible.example/v1"}, clear=False), patch(
            "uim_core.providers.openai_image.open_external_url", fake_open_external_url
        ):
            output = Path(tmp) / "image.png"
            OpenAIImageProvider().generate("test", output)
            self.assertEqual(output.read_bytes(), b"image")

    def test_openai_provider_reports_unsupported_response_keys(self) -> None:
        def fake_open_external_url(_request, timeout: int):
            return _FakeOpenAIResponse(b'{"data":[{"created":123,"id":"img-test"}]}')

        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"OPENAI_API_KEY": "test-key", "OPENAI_BASE_URL": "https://compatible.example/v1"}, clear=False), patch(
            "uim_core.providers.openai_image.open_external_url", fake_open_external_url
        ):
            output = Path(tmp) / "image.png"
            with self.assertRaisesRegex(RuntimeError, r"got keys: created, id; base_url=https://compatible.example/v1"):
                OpenAIImageProvider().generate("test", output)

    def test_runtime_settings_persists_network_proxy(self) -> None:
        proxy_keys = ("UIM_NETWORK_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")
        previous = {key: os.environ.get(key) for key in proxy_keys}
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}, clear=False):
            try:
                for key in proxy_keys:
                    os.environ.pop(key, None)
                updated = api_update_runtime_settings(RuntimeSettingsRequest(network_proxy="http://127.0.0.1:7890"))
                self.assertEqual(updated["networkProxy"], "http://127.0.0.1:7890")
                for key in proxy_keys:
                    os.environ.pop(key, None)
                _apply_saved_runtime_settings()
                self.assertEqual(os.environ.get("UIM_NETWORK_PROXY"), "http://127.0.0.1:7890")
            finally:
                for key in proxy_keys:
                    if previous[key] is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = previous[key] or ""

    def test_model_list_exposes_registry(self) -> None:
        result = api_list_models()
        self.assertGreaterEqual(len(result["models"]), 1)
        first = result["models"][0]
        self.assertIn("local_path", first)
        self.assertIn("license", first)
        self.assertIn("recommended_vram_gb", first)

    def test_asset_preview_rejects_path_outside_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            root.mkdir()
            with self.assertRaises(Exception):
                api_asset_preview(str(root), "../outside.png")

    def test_list_project_assets_reads_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            manifest_dir = root / "assets" / "fire_spell" / "manifests"
            manifest_dir.mkdir(parents=True)
            (manifest_dir / "manifest.json").write_text(
                '{"id":"fire_spell","displayName":"Fire Spell","assetType":"texture","files":[{"path":"assets/fire_spell/generated/final.png"}]}',
                encoding="utf-8",
            )
            result = api_list_project_assets(str(root))
            self.assertEqual(len(result["assets"]), 1)
            self.assertEqual(result["assets"][0]["name"], "Fire Spell")
            self.assertEqual(result["assets"][0]["path"], "assets/fire_spell/generated/final.png")
            self.assertEqual(result["assets"][0]["versions"][0]["path"], "assets/fire_spell/generated/final.png")

    def test_asset_version_order_and_delete_syncs_primary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            generated = root / "assets" / "fire_spell" / "generated"
            manifest_dir = root / "assets" / "fire_spell" / "manifests"
            generated.mkdir(parents=True)
            manifest_dir.mkdir(parents=True)
            (generated / "a.png").write_bytes(b"a")
            (generated / "b.png").write_bytes(b"b")
            (manifest_dir / "manifest.json").write_text(
                '{"id":"fire_spell","displayName":"Fire Spell","assetType":"texture","styleProfile":"pixel_art","files":[{"path":"assets/fire_spell/generated/a.png"}]}',
                encoding="utf-8",
            )
            first = api_list_project_assets(str(root))["assets"][0]
            version_a = first["versions"][0]["id"]
            from uim_core.api import AssetImageRegisterRequest, api_register_asset_image

            second = api_register_asset_image(
                AssetImageRegisterRequest(
                    project_root=str(root),
                    asset_name="Fire Spell",
                    image_path="assets/fire_spell/generated/b.png",
                    role="final",
                    label="final",
                )
            )
            version_b = second["versions"][0]["id"]
            reordered = api_reorder_asset_versions("fire_spell", AssetVersionOrderRequest(project_root=str(root), version_ids=[version_a, version_b]))
            self.assertEqual(reordered["path"], "assets/fire_spell/generated/a.png")
            deleted = api_delete_asset_version("fire_spell", version_a, str(root))
            self.assertEqual(deleted["path"], "assets/fire_spell/generated/b.png")
            self.assertFalse((generated / "a.png").exists())

    def test_asset_settings_persist_in_asset_index_and_asset_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            from uim_core.project import create_project

            create_project(root, "Demo")
            record = api_update_asset_settings(
                "hero",
                AssetSettingsRequest(
                    project_root=str(root),
                    display_name="Hero",
                    settings={"pixel": {"cellSize": 192, "anchorOutputSize": "1536x1536"}},
                ),
            )

            self.assertEqual(record["settings"]["pixel"]["cellSize"], 192)
            index = json.loads((root / "assets" / "hero" / "asset.index.json").read_text(encoding="utf-8"))
            self.assertEqual(index["settings"]["pixel"]["anchorOutputSize"], "1536x1536")
            listed = api_list_project_assets(str(root))["assets"][0]
            self.assertEqual(listed["settings"]["pixel"]["cellSize"], 192)

    def test_delete_asset_removes_project_asset_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            asset_dir = root / "assets" / "fire_spell"
            asset_dir.mkdir(parents=True)
            (asset_dir / "asset.index.json").write_text("{}", encoding="utf-8")
            result = api_delete_asset("fire_spell", str(root))
            self.assertEqual(result["deleted"], "fire_spell")
            self.assertFalse(asset_dir.exists())

    def test_project_workspace_refresh_updates_current_project_pointer_for_mcp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            pointer = Path(tmp) / "current-project.json"
            from uim_core.project import create_project

            create_project(root, "Demo")
            with (
                patch("uim_core.project.current_project_pointer_path", return_value=pointer),
                patch("uim_core.project.workspace_root", return_value=Path(tmp)),
                patch.dict(os.environ, {"UIM_CURRENT_PROJECT": "", "UIM_CURRENT_PROJECT_POINTER": ""}, clear=False),
            ):
                api_project_workspace(str(root))
                result = mcp_game_ui.game_ui_get_current_dsl_prompt()

            self.assertTrue(result["ok"])
            self.assertEqual(result["writeWorkflow"]["projectRoot"], str(root.resolve()))

    def test_game_ui_dsl_prompt_refresh_updates_current_project_pointer_for_mcp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            pointer = Path(tmp) / "current-project.json"
            from uim_core.project import create_project

            create_project(root, "Demo")
            with (
                patch("uim_core.project.current_project_pointer_path", return_value=pointer),
                patch("uim_core.project.workspace_root", return_value=Path(tmp)),
                patch.dict(os.environ, {"UIM_CURRENT_PROJECT": "", "UIM_CURRENT_PROJECT_POINTER": ""}, clear=False),
            ):
                api_game_ui_dsl_prompt(project_root=str(root))
                result = mcp_game_ui.game_ui_get_current_dsl_prompt()

            self.assertTrue(result["ok"])
            self.assertEqual(result["writeWorkflow"]["projectRoot"], str(root.resolve()))

    def test_processing_queue_persists_in_project_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            from uim_core.project import create_project

            create_project(root, "Demo")
            queue = [{"id": "item-1", "assetId": "fire", "assetName": "Fire", "role": "final", "label": "Fire", "path": "assets/fire/generated/final.png"}]
            api_update_processing_queue(ProcessingQueueRequest(project_root=str(root), queue=queue))
            workspace = api_project_workspace(str(root))
            self.assertEqual(workspace["processingQueue"], queue)

    def test_workflow_slots_persist_in_project_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Demo.uim"
            from uim_core.project import create_project

            create_project(root, "Demo")
            slots = {
                "pixel": {
                    "southAnchor": {"mode": "fixed", "assetId": "hero", "versionId": "v1"},
                    "directionAnchor": {"mode": "auto"},
                },
                "gameUi": {"concept": {"mode": "fixed", "assetId": "hud", "versionId": "concept"}},
            }
            api_update_workflow_slots(WorkflowSlotsRequest(project_root=str(root), workflow_slots=slots))
            workspace = api_project_workspace(str(root))
            self.assertEqual(workspace["workflowSlots"], slots)

    def test_unreal_mcp_status_is_serializable(self) -> None:
        result = api_unreal_mcp_status()
        self.assertIn("available", result)
        self.assertIn("mode", result)
        self.assertIn("detail", result)

    def test_codex_oauth_start_uses_pkce(self) -> None:
        result = api_codex_oauth_start()
        try:
            self.assertIn("https://auth.openai.com/oauth/authorize", result["authorize_url"])
            self.assertIn("code_challenge=", result["authorize_url"])
            self.assertIn("state=", result["authorize_url"])
            self.assertIn("redirect_uri=", result["authorize_url"])
            self.assertEqual(result["redirect_uri"], "http://localhost:1455/auth/callback")
            self.assertIn("auto_callback", result)
            self.assertIn("message", result)
            self.assertNotIn("verifier", result)
        finally:
            _shutdown_codex_oauth_callback_server(result["state"])

    def test_codex_oauth_callback_parser_accepts_url(self) -> None:
        code, state = parse_authorization_input("http://localhost:1455/auth/callback?code=abc&state=xyz")
        self.assertEqual(code, "abc")
        self.assertEqual(state, "xyz")

    def test_codex_oauth_start_falls_back_to_manual_callback(self) -> None:
        with patch("uim_core.api._create_codex_oauth_callback_server", side_effect=RuntimeError("port busy")):
            result = api_codex_oauth_start()
        self.assertFalse(result["auto_callback"])
        self.assertEqual(result["redirect_uri"], "http://localhost:1455/auth/callback")
        self.assertIn("完整网址", result["message"])
        self.assertNotIn("verifier", result)

    def test_codex_oauth_status_does_not_expose_tokens(self) -> None:
        status = safe_token_status(
            {
                "access_token": "secret",
                "refresh_token": "refresh",
                "account_id": "acct",
                "email": "user@example.com",
                "expires_at": "2030-01-01T00:00:00+00:00",
            }
        )
        self.assertTrue(status["configured"])
        self.assertNotIn("access_token", status)
        self.assertNotIn("refresh_token", status)

    def test_codex_sse_response_reads_stream_events(self) -> None:
        image = "aW1hZ2U="
        stream = "\n".join(
            [
                "event: response.created",
                'data: {"type":"response.created"}',
                "",
                "event: response.output_item.done",
                f'data: {{"type":"response.output_item.done","item":{{"type":"image_generation_call","status":"completed","result":"{image}"}}}}',
                "",
                "event: response.completed",
                'data: {"type":"response.completed","response":{"status":"completed","model":"gpt-5.5"}}',
                "",
            ]
        ).encode("utf-8")
        result, events = read_codex_sse_response(io.BytesIO(stream))
        self.assertEqual(result, image)
        self.assertIn("image_generation_call.result", events)
        self.assertIn("response.completed status=completed model=gpt-5.5", events)

    def test_codex_sse_response_emits_stream_events_while_reading(self) -> None:
        image = "aW1hZ2U="
        stream_text = "\n".join(
            [
                "event: response.image_generation_call.generating",
                'data: {"type":"response.image_generation_call.generating"}',
                "",
                "event: response.output_item.done",
                f'data: {{"type":"response.output_item.done","item":{{"type":"image_generation_call","status":"completed","result":"{image}"}}}}',
                "",
            ]
        )
        stream = _TrackingSseStream([f"{line}\n".encode("utf-8") for line in stream_text.splitlines()])
        emitted: list[str] = []
        positions: list[int] = []

        def capture(event: str) -> None:
            emitted.append(event)
            positions.append(stream.index)

        with codex_stream_events(capture):
            result, events = read_codex_sse_response(stream)

        self.assertEqual(result, image)
        self.assertIn("response.image_generation_call.generating", emitted)
        self.assertIn("image_generation_call.result", emitted)
        self.assertEqual(events, emitted)
        self.assertLess(positions[0], len(stream.lines))

    def test_codex_oauth_edit_sends_reference_image(self) -> None:
        captured: dict[str, object] = {}

        def fake_open_external_url(request, timeout: int):
            captured["timeout"] = timeout
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return _FakeCodexResponse("aW1hZ2U=")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = root / "reference.png"
            output = root / "output.png"
            reference.write_bytes(b"png")
            provider = CodexOAuthImageProvider(token_path=root / "tokens.json")

            with patch.object(provider, "_load_fresh_tokens", return_value={"access_token": "token", "account_id": "account"}), patch(
                "uim_core.providers.codex_oauth_image.open_external_url", fake_open_external_url
            ):
                result = provider.edit("keep the same silhouette", reference, output, size="1024x1024")
            self.assertEqual(output.read_bytes(), b"image")

        content = captured["payload"]["input"][0]["content"]  # type: ignore[index]
        self.assertEqual(content[0]["type"], "input_text")
        self.assertEqual(content[1]["type"], "input_image")
        self.assertTrue(content[1]["image_url"].startswith("data:image/png;base64,"))
        self.assertEqual(result.request_id, "req-test")


if __name__ == "__main__":
    unittest.main()
