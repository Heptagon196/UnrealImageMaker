from __future__ import annotations

import os
import json
import re
from dataclasses import dataclass
from typing import Any

import requests

UMG_TOOLSET = "UMGToolSet.UMGToolSet"
ASSET_TOOLSET = "toolset_registry.toolsets.core.asset.AssetTools"
OBJECT_TOOLSET = "toolset_registry.toolsets.core.object.ObjectTools"
UMG_CREATE_WIDGET_BLUEPRINT = f"{UMG_TOOLSET}.CreateWidgetBlueprint"
UMG_ADD_WIDGET = f"{UMG_TOOLSET}.AddWidget"
UMG_GET_WIDGETS = f"{UMG_TOOLSET}.GetWidgets"
UMG_REMOVE_WIDGET = f"{UMG_TOOLSET}.RemoveWidget"
UMG_COMPILE_WIDGET_BLUEPRINT = f"{UMG_TOOLSET}.CompileWidgetBlueprint"
ASSET_CREATE_FOLDER = f"{ASSET_TOOLSET}.create_folder"
ASSET_EXISTS = f"{ASSET_TOOLSET}.exists"
ASSET_SAVE_ASSETS = f"{ASSET_TOOLSET}.save_assets"
OBJECT_SET_PROPERTIES = f"{OBJECT_TOOLSET}.set_properties"
PROGRAMMATIC_TOOLSET = "toolset_registry.toolsets.core.programmatic.ProgrammaticToolset"
PROGRAMMATIC_EXECUTE_TOOL_SCRIPT = f"{PROGRAMMATIC_TOOLSET}.execute_tool_script"


@dataclass(slots=True)
class UnrealMcpStatus:
    available: bool
    mode: str
    detail: str


class UnrealMcpBridge:
    """Optional HTTP bridge for Unreal MCP-compatible servers.

    Codex MCP tools are available to the agent, but the packaged desktop app
    still needs a product-facing bridge. MVP supports a configurable HTTP MCP
    endpoint via UIM_UNREAL_MCP_URL and falls back to Python script export.
    """

    def __init__(self, endpoint: str | None = None) -> None:
        self.endpoint = endpoint or os.environ.get("UIM_UNREAL_MCP_URL")
        self._next_id = 1

    def _mcp_url(self) -> str:
        endpoint = (self.endpoint or "").strip().rstrip("/")
        if endpoint.endswith("/mcp"):
            return endpoint
        return f"{endpoint}/mcp"

    def _headers(self, session_id: str | None = None) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        return headers

    def _initialize_payload(self) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": self._request_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "UnrealImageMaker", "version": "0.1.0"},
            },
        }

    def _request_id(self) -> int:
        request_id = self._next_id
        self._next_id += 1
        return request_id

    def _parse_json_or_sse(self, response: requests.Response) -> dict[str, Any]:
        try:
            payload = response.json()
            if isinstance(payload, dict):
                return payload
        except ValueError:
            pass
        for line in response.text.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data:
                continue
            try:
                payload = json.loads(data)
            except ValueError:
                continue
            if isinstance(payload, dict):
                return payload
        raise RuntimeError("MCP endpoint returned a response that is neither JSON nor MCP SSE data")

    def _rpc(self, mcp_url: str, session_id: str | None, method: str, params: dict[str, Any] | None = None, timeout: int = 30) -> dict[str, Any]:
        response = requests.post(
            mcp_url,
            json={"jsonrpc": "2.0", "id": self._request_id(), "method": method, "params": params or {}},
            headers=self._headers(session_id),
            timeout=timeout,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"MCP endpoint returned HTTP {response.status_code} for {method}: {response.text[:500]}")
        payload = self._parse_json_or_sse(response)
        if "error" in payload:
            error = payload.get("error")
            raise RuntimeError(f"MCP {method} failed: {error}")
        result = payload.get("result")
        return result if isinstance(result, dict) else {"value": result}

    def _start_session(self) -> tuple[str, str]:
        if not self.endpoint:
            raise RuntimeError("UIM_UNREAL_MCP_URL is not configured")
        mcp_url = self._mcp_url()
        response = requests.post(
            mcp_url,
            json=self._initialize_payload(),
            headers=self._headers(),
            timeout=10,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"MCP endpoint returned HTTP {response.status_code} at {mcp_url}: {response.text[:500]}")
        session_id = response.headers.get("Mcp-Session-Id")
        if not session_id:
            raise RuntimeError("MCP endpoint did not return Mcp-Session-Id")
        requests.post(
            mcp_url,
            json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            headers=self._headers(session_id),
            timeout=10,
        )
        return mcp_url, session_id

    def _tool_call(self, mcp_url: str, session_id: str, name: str, arguments: dict[str, Any] | None = None, timeout: int = 30) -> Any:
        result = self._rpc(
            mcp_url,
            session_id,
            "tools/call",
            {"name": name, "arguments": arguments or {}},
            timeout=timeout,
        )
        content = result.get("content")
        if isinstance(content, list) and content:
            text_parts = [item.get("text", "") for item in content if isinstance(item, dict) and item.get("type") == "text"]
            text = "\n".join(part for part in text_parts if part)
            if text:
                try:
                    return json.loads(text)
                except ValueError:
                    if "Function schema Json" in text or "is required by the function input schema" in text:
                        raise RuntimeError(text)
                    return text
        return result

    def _load_toolset(self, mcp_url: str, session_id: str, toolset: str) -> Any:
        return self._tool_call(mcp_url, session_id, "load_toolset", {"toolset_name": toolset}, timeout=60)

    def status(self) -> UnrealMcpStatus:
        if not self.endpoint:
            return UnrealMcpStatus(
                available=False,
                mode="python_fallback",
                detail="UIM_UNREAL_MCP_URL is not configured; use generated Unreal Python scripts.",
            )
        mcp_url = self._mcp_url()
        try:
            response = requests.post(
                mcp_url,
                json=self._initialize_payload(),
                headers=self._headers(),
                timeout=5,
            )
        except requests.RequestException as exc:
            return UnrealMcpStatus(False, "python_fallback", f"MCP endpoint is unreachable: {exc}")
        if response.status_code >= 400:
            return UnrealMcpStatus(False, "python_fallback", f"MCP endpoint returned HTTP {response.status_code} at {mcp_url}")
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if payload and payload.get("jsonrpc") == "2.0" and ("result" in payload or "error" in payload):
            return UnrealMcpStatus(True, "mcp", f"MCP endpoint is reachable at {mcp_url}")
        return UnrealMcpStatus(True, "mcp", f"MCP endpoint responded at {mcp_url}")

    def export_widget_blueprint(
        self,
        widget_path: str,
        structure: dict[str, Any],
        texture_kit: dict[str, Any] | None = None,
        default_style_tokens: dict[str, str] | None = None,
        box_style_tokens: set[str] | list[str] | tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        """Create/update a UMG widget blueprint through the Unreal MCP server."""
        mcp_url, session_id = self._start_session()
        for toolset in (UMG_TOOLSET, ASSET_TOOLSET, OBJECT_TOOLSET, PROGRAMMATIC_TOOLSET):
            self._load_toolset(mcp_url, session_id, toolset)
        script = _programmatic_umg_export_script(widget_path, structure, texture_kit or {}, default_style_tokens or {}, box_style_tokens or [])
        result = self._tool_call(mcp_url, session_id, PROGRAMMATIC_EXECUTE_TOOL_SCRIPT, {"script": script}, timeout=300)
        payload = _unwrap_return_value(result)
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except ValueError:
                pass
        if not isinstance(payload, dict):
            raise RuntimeError(f"Programmatic UMG export returned an unexpected result: {payload!r}")
        payload.setdefault("ok", True)
        payload.setdefault("mode", "mcp")
        payload.setdefault("endpoint", mcp_url)
        payload.setdefault("widgetPath", widget_path)
        return payload

    def _prepare_root_widget(self, mcp_url: str, session_id: str, blueprint_ref: dict[str, str], widgets: Any) -> tuple[dict[str, str], int]:
        widget_items = _widget_items(widgets)
        root_ref = _first_widget_ref(widget_items)
        if not root_ref:
            raise RuntimeError("MCP GetWidgets did not return a root widget")
        removed = 0
        for item in widget_items[1:]:
            widget_ref = _widget_ref(item)
            if not widget_ref:
                continue
            try:
                self._tool_call(mcp_url, session_id, UMG_REMOVE_WIDGET, {"widgetBlueprint": blueprint_ref, "widget": widget_ref})
                removed += 1
            except Exception:
                continue
        return root_ref, removed

    def _add_node(
        self,
        mcp_url: str,
        session_id: str,
        blueprint_ref: dict[str, str],
        parent_ref: dict[str, str],
        node: dict[str, Any],
        z_order: int,
        warnings: list[str],
    ) -> int:
        if not isinstance(node, dict):
            return 0
        node_type = str(node.get("type") or "panel")
        widget_class = _widget_class_for_node(node_type)
        widget_name = _safe_unreal_name(str(node.get("name") or node_type))
        result = self._tool_call(
            mcp_url,
            session_id,
            UMG_ADD_WIDGET,
            {
                "widgetBlueprint": blueprint_ref,
                "parentWidget": parent_ref,
                "widgetClass": {"refPath": widget_class},
                "widgetName": widget_name,
            },
            timeout=60,
        )
        widget_ref = _extract_ref(result, ("widget", "result", "value")) or {"refPath": _guess_child_ref(parent_ref, widget_name)}
        slot_ref = _extract_ref(result, ("slot", "slotRef"))
        if not slot_ref:
            slot_ref = {"refPath": f"{widget_ref.get('refPath', '').rstrip()}.CanvasPanelSlot_0"}
        self._set_slot_layout(mcp_url, session_id, slot_ref, node, z_order, warnings)
        self._set_basic_properties(mcp_url, session_id, widget_ref, node, node_type, warnings)
        added = 1
        child_parent = widget_ref if node_type in {"screen", "panel", "scroll"} else parent_ref
        for index, child in enumerate(node.get("children") or []):
            added += self._add_node(mcp_url, session_id, blueprint_ref, child_parent, child, z_order + index + 1, warnings)
        return added

    def _set_slot_layout(self, mcp_url: str, session_id: str, slot_ref: dict[str, str], node: dict[str, Any], z_order: int, warnings: list[str]) -> None:
        x = _float(node.get("x", 0))
        y = _float(node.get("y", 0))
        width = max(1.0, _float(node.get("width", node.get("w", 100))))
        height = max(1.0, _float(node.get("height", node.get("h", 40))))
        offsets = node.get("offsets")
        if isinstance(offsets, dict):
            x = _float(offsets.get("left", x))
            y = _float(offsets.get("top", y))
            width = max(1.0, _float(offsets.get("right", width)))
            height = max(1.0, _float(offsets.get("bottom", height)))
        anchors = _anchors_for_node(node)
        values = {
            "layoutData": {
                "offsets": {"left": x, "top": y, "right": width, "bottom": height},
                "anchors": anchors,
                "alignment": {"x": 0.0, "y": 0.0},
            },
            "bAutoSize": False,
            "zOrder": int(z_order),
        }
        try:
            self._tool_call(mcp_url, session_id, OBJECT_SET_PROPERTIES, {"instance": slot_ref, "values": json.dumps(values)})
        except Exception as exc:
            warnings.append(f"Failed to set slot layout for {node.get('name')}: {exc}")

    def _set_basic_properties(self, mcp_url: str, session_id: str, widget_ref: dict[str, str], node: dict[str, Any], node_type: str, warnings: list[str]) -> None:
        values: dict[str, Any] = {}
        if node_type in {"text", "input"}:
            values["text"] = str(node.get("text") or node.get("name") or "")
        if node_type == "checkbox":
            values["checkedState"] = "Checked" if node.get("checked") else "Unchecked"
        if node_type == "slider":
            values["value"] = _float(node.get("value", 0.5))
        if not values:
            return
        try:
            self._tool_call(mcp_url, session_id, OBJECT_SET_PROPERTIES, {"instance": widget_ref, "values": json.dumps(values)})
        except Exception as exc:
            warnings.append(f"Failed to set properties for {node.get('name')}: {exc}")


def _split_widget_path(widget_path: str) -> tuple[str, str]:
    clean = widget_path.strip().rstrip("/")
    if not clean.startswith("/Game/") or "/" not in clean[6:]:
        raise ValueError(f"Invalid Unreal widget path: {widget_path}")
    folder, name = clean.rsplit("/", 1)
    return folder, _safe_unreal_name(name)


def _programmatic_umg_export_script(
    widget_path: str,
    structure: dict[str, Any],
    texture_kit: dict[str, Any],
    default_style_tokens: dict[str, str],
    box_style_tokens: set[str] | list[str] | tuple[str, ...],
) -> str:
    folder_path, asset_name = _split_widget_path(widget_path)
    structure_json = json.dumps(structure, ensure_ascii=False)
    texture_kit_json = json.dumps(texture_kit, ensure_ascii=False)
    default_style_tokens_json = json.dumps(default_style_tokens, ensure_ascii=False)
    box_style_tokens_json = json.dumps(sorted(box_style_tokens), ensure_ascii=False)
    widget_path_json = json.dumps(widget_path)
    folder_path_json = json.dumps(folder_path)
    asset_name_json = json.dumps(asset_name)
    return f'''
import json
import re

STRUCTURE = json.loads({structure_json!r})
TEXTURE_KIT = json.loads({texture_kit_json!r})
DEFAULT_STYLE_TOKENS = json.loads({default_style_tokens_json!r})
BOX_STYLE_TOKENS = set(json.loads({box_style_tokens_json!r}))
WIDGET_PATH = {widget_path_json}
FOLDER_PATH = {folder_path_json}
ASSET_NAME = {asset_name_json}

UMG = "UMGToolSet.UMGToolSet"
ASSET = "toolset_registry.toolsets.core.asset.AssetTools"
OBJECT = "toolset_registry.toolsets.core.object.ObjectTools"

def call(toolset, tool_name, params):
    result, error = execute_tool(toolset, tool_name, json.dumps(params))
    if error:
        raise RuntimeError(error)
    data = json.loads(result)
    return data.get("returnValue", data)

def ref(value):
    while isinstance(value, dict) and set(value.keys()) == {{"returnValue"}}:
        value = value.get("returnValue")
    if isinstance(value, dict) and isinstance(value.get("refPath"), str):
        return {{"refPath": value["refPath"]}}
    if isinstance(value, dict):
        for key in ("widget", "slot", "parent", "result", "value"):
            found = ref(value.get(key))
            if found:
                return found
    return None

def widget_items(payload):
    payload = payload.get("returnValue", payload) if isinstance(payload, dict) else payload
    if isinstance(payload, dict) and isinstance(payload.get("widgets"), list):
        return payload["widgets"]
    if isinstance(payload, list):
        return payload
    return []

def widget_count(payload):
    payload = payload.get("returnValue", payload) if isinstance(payload, dict) else payload
    if isinstance(payload, dict):
        info = payload.get("info")
        if isinstance(info, dict) and isinstance(info.get("widgetCount"), int):
            return info["widgetCount"]
        if isinstance(payload.get("widgetCount"), int):
            return payload["widgetCount"]
    return len(widget_items(payload))

def safe_name(value):
    name = re.sub(r"[^A-Za-z0-9_]+", "_", str(value or "").strip()).strip("_") or "Widget"
    if name[0].isdigit():
        name = "W_" + name
    return name[:58]

def unique_name(base, used):
    name = safe_name(base)
    if name not in used:
        used[name] = 1
        return name
    used[name] += 1
    suffix = "_" + str(used[name])
    return (name[:64 - len(suffix)] + suffix)

def widget_class(node_type):
    return {{
        "screen": "/Script/UMG.CanvasPanel",
        "panel": "/Script/UMG.CanvasPanel",
        "image": "/Script/UMG.Image",
        "text": "/Script/UMG.TextBlock",
        "button": "/Script/UMG.Button",
        "input": "/Script/UMG.EditableTextBox",
        "scroll": "/Script/UMG.ScrollBox",
        "checkbox": "/Script/UMG.CheckBox",
        "slider": "/Script/UMG.Slider",
        "dropdown": "/Script/UMG.ComboBoxString",
    }}.get(node_type, "/Script/UMG.Image")

def to_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default

def basename_no_ext(path):
    raw = str(path or "").replace("\\\\", "/").rsplit("/", 1)[-1]
    return raw.rsplit(".", 1)[0] if "." in raw else raw

def texture_content_path():
    return str(TEXTURE_KIT.get("contentPath") or FOLDER_PATH).rstrip("/")

def find_texture_asset(asset_name):
    if not asset_name:
        return None
    content = texture_content_path()
    for candidate in (content + "/" + asset_name, content + "/Textures/" + asset_name):
        try:
            if call(ASSET, "exists", {{"path": candidate}}):
                return {{"refPath": candidate}}
        except Exception:
            pass
    try:
        found = call(ASSET, "find_assets", {{"folder_path": content, "name": asset_name, "recursive": True}})
        if isinstance(found, list) and found:
            first = found[0]
            if isinstance(first, dict) and isinstance(first.get("refPath"), str):
                return {{"refPath": first["refPath"]}}
            if isinstance(first, str):
                return {{"refPath": first}}
    except Exception:
        pass
    return None

def build_texture_refs(warnings):
    refs = {{}}
    for token, entry in (TEXTURE_KIT.get("textures") or {{}}).items():
        states = entry.get("states") if isinstance(entry, dict) else {{}}
        for state, state_data in (states or {{}}).items():
            if not isinstance(state_data, dict):
                continue
            unreal_path = str(state_data.get("unrealPath") or "").strip()
            texture = {{"refPath": unreal_path}} if unreal_path else None
            if texture:
                try:
                    if not call(ASSET, "exists", {{"path": unreal_path}}):
                        texture = None
                except Exception:
                    texture = None
            if not texture:
                texture = find_texture_asset(basename_no_ext(state_data.get("path")))
            if texture:
                refs[token + ":" + str(state)] = texture
            elif state_data.get("path"):
                warnings.append("Texture is not imported in UE for " + token + ":" + str(state) + " (" + str(state_data.get("path")) + ")")
    return refs

def style_token(node, fallback_type=None):
    node_type = fallback_type or str(node.get("type") or "")
    explicit = str(node.get("styleToken") or "")
    textures = TEXTURE_KIT.get("textures") or {{}}
    if explicit and explicit in textures:
        return explicit
    if node_type == "text" and not explicit:
        return ""
    if explicit and node_type in ("panel", "image"):
        width = to_float(node.get("width"), 0.0)
        height = to_float(node.get("height"), 0.0)
        if width <= 0 or height <= 0 or width > 520 or height > 220:
            return ""
    fallback = DEFAULT_STYLE_TOKENS.get(node_type, "")
    return fallback if fallback in textures else explicit

def texture_for(node, refs, state="normal", fallback_type=None, explicit_token=None):
    token = explicit_token or style_token(node, fallback_type)
    if not token:
        return None, ""
    return refs.get(token + ":" + state) or refs.get(token + ":normal"), token

def slate_color(r=1.0, g=1.0, b=1.0, a=1.0):
    return {{"specifiedColor": {{"r": r, "g": g, "b": b, "a": a}}, "colorUseRule": "UseColor_Specified"}}

def brush_from_texture(texture, width, height, token):
    draw_as = "Box" if token in BOX_STYLE_TOKENS else "Image"
    margin = {{"left": 0.25, "top": 0.25, "right": 0.25, "bottom": 0.25}} if draw_as == "Box" else {{"left": 0.0, "top": 0.0, "right": 0.0, "bottom": 0.0}}
    return {{
        "tintColor": slate_color(),
        "drawAs": draw_as,
        "tiling": "NoTile",
        "mirroring": "NoMirror",
        "imageType": "FullColor",
        "imageSize": {{"x": max(1.0, to_float(width, 64.0)), "y": max(1.0, to_float(height, 64.0))}},
        "margin": margin,
        "resourceObject": texture,
        "resourceName": "",
    }}

def apply_image_brush(widget, node, texture_refs, warnings, label, explicit_token=None):
    texture, token = texture_for(node, texture_refs, explicit_token=explicit_token)
    if not texture:
        return False
    return set_properties(widget, {{"brush": brush_from_texture(texture, node.get("width", 64), node.get("height", 64), token)}}, warnings, "brush " + label)

def apply_button_style(widget, node, texture_refs, warnings, label):
    token = style_token(node, "button")
    if not token:
        return False
    state_map = {{"normal": "normal", "hover": "hovered", "pressed": "pressed", "disabled": "disabled"}}
    style = {{}}
    for source_state, property_name in state_map.items():
        texture = texture_refs.get(token + ":" + source_state) or texture_refs.get(token + ":normal")
        if texture:
            style[property_name] = brush_from_texture(texture, node.get("width", 64), node.get("height", 64), token)
    if not style:
        return False
    return set_properties(widget, {{"widgetStyle": style}}, warnings, "button style " + label)

def anchors_for_node(node):
    anchors = node.get("anchors")
    if isinstance(anchors, dict):
        minimum = anchors.get("minimum") if isinstance(anchors.get("minimum"), dict) else {{}}
        maximum = anchors.get("maximum") if isinstance(anchors.get("maximum"), dict) else {{}}
        return {{
            "minimum": {{"x": to_float(minimum.get("x"), 0.0), "y": to_float(minimum.get("y"), 0.0)}},
            "maximum": {{"x": to_float(maximum.get("x"), 0.0), "y": to_float(maximum.get("y"), 0.0)}},
        }}
    preset = str(node.get("anchorPreset") or node.get("anchor") or "top-left")
    presets = {{
        "top-left": ((0.0, 0.0), (0.0, 0.0)),
        "top-right": ((1.0, 0.0), (1.0, 0.0)),
        "bottom-left": ((0.0, 1.0), (0.0, 1.0)),
        "bottom-right": ((1.0, 1.0), (1.0, 1.0)),
        "center": ((0.5, 0.5), (0.5, 0.5)),
        "full": ((0.0, 0.0), (1.0, 1.0)),
        "top-stretch": ((0.0, 0.0), (1.0, 0.0)),
        "bottom-stretch": ((0.0, 1.0), (1.0, 1.0)),
        "left-stretch": ((0.0, 0.0), (0.0, 1.0)),
        "right-stretch": ((1.0, 0.0), (1.0, 1.0)),
    }}
    minimum, maximum = presets.get(preset, presets["top-left"])
    return {{"minimum": {{"x": minimum[0], "y": minimum[1]}}, "maximum": {{"x": maximum[0], "y": maximum[1]}}}}

def slot_values(node, z_order):
    x = to_float(node.get("x"), 0.0)
    y = to_float(node.get("y"), 0.0)
    width = max(1.0, to_float(node.get("width", node.get("w", 100)), 100.0))
    height = max(1.0, to_float(node.get("height", node.get("h", 40)), 40.0))
    offsets = node.get("offsets")
    if isinstance(offsets, dict):
        x = to_float(offsets.get("left"), x)
        y = to_float(offsets.get("top"), y)
        width = max(1.0, to_float(offsets.get("right"), width))
        height = max(1.0, to_float(offsets.get("bottom"), height))
    alignment = node.get("alignment") if isinstance(node.get("alignment"), dict) else {{}}
    return {{
        "layoutData": {{
            "offsets": {{"left": x, "top": y, "right": width, "bottom": height}},
            "anchors": anchors_for_node(node),
            "alignment": {{"x": to_float(alignment.get("x"), 0.0), "y": to_float(alignment.get("y"), 0.0)}},
        }},
        "bAutoSize": False,
        "zOrder": int(z_order),
    }}

def set_properties(instance, values, warnings, label):
    if not instance:
        warnings.append("Missing instance for " + label)
        return False
    try:
        result = call(OBJECT, "set_properties", {{"instance": instance, "values": json.dumps(values)}})
    except Exception as exc:
        warnings.append("Failed to set " + label + ": " + str(exc))
        return False
    if result is not True:
        warnings.append("set_properties returned false for " + label)
    return bool(result)

def add_skin_image(blueprint, parent, node, z_order, used, warnings, texture_refs, name_suffix="Skin", explicit_token=None, parent_has_canvas_slot=True, fill_parent=False):
    texture, token = texture_for(node, texture_refs, explicit_token=explicit_token)
    if not texture:
        return 0
    name = unique_name(str(node.get("name") or "Widget") + name_suffix, used)
    add_result = call(UMG, "AddWidget", {{
        "widgetBlueprint": blueprint,
        "parentWidget": parent,
        "widgetClass": {{"refPath": "/Script/UMG.Image"}},
        "widgetName": name,
    }})
    widget = ref(add_result.get("widget") if isinstance(add_result, dict) else add_result)
    slot = ref(add_result.get("slot") if isinstance(add_result, dict) else None)
    skin_node = node
    if fill_parent:
        skin_node = dict(node)
        skin_node["offsets"] = {{"left": 0, "top": 0, "right": node.get("width", 64), "bottom": node.get("height", 64)}}
        skin_node["anchors"] = {{"minimum": {{"x": 0.0, "y": 0.0}}, "maximum": {{"x": 1.0, "y": 1.0}}}}
        skin_node["alignment"] = {{"x": 0.0, "y": 0.0}}
    if parent_has_canvas_slot:
        set_properties(slot, slot_values(skin_node, z_order), warnings, "slot " + name)
    elif slot:
        warnings.append("Skipped Canvas layout for non-Canvas skin slot " + name)
    set_properties(widget, {{"brush": brush_from_texture(texture, node.get("width", 64), node.get("height", 64), token)}}, warnings, "brush " + name)
    return 1

def add_node(blueprint, parent, node, z_order, used, warnings, texture_refs, parent_has_canvas_slot=True):
    if not isinstance(node, dict):
        return 0
    node_type = str(node.get("type") or "panel")
    name = unique_name(node.get("name") or node_type, used)
    widget_class_path = "/Script/UMG.CanvasPanel" if node_type == "panel" else widget_class(node_type)
    add_result = call(UMG, "AddWidget", {{
        "widgetBlueprint": blueprint,
        "parentWidget": parent,
        "widgetClass": {{"refPath": widget_class_path}},
        "widgetName": name,
    }})
    widget = ref(add_result.get("widget") if isinstance(add_result, dict) else add_result)
    slot = ref(add_result.get("slot") if isinstance(add_result, dict) else None)
    if parent_has_canvas_slot:
        set_properties(slot, slot_values(node, z_order), warnings, "slot " + name)
    elif slot:
        warnings.append("Skipped Canvas layout for non-Canvas slot " + name)
    added = 1
    if node_type == "panel":
        added += add_skin_image(blueprint, widget, node, 0, used, warnings, texture_refs, parent_has_canvas_slot=True, fill_parent=True)
    elif node_type == "image":
        apply_image_brush(widget, node, texture_refs, warnings, name)
    elif node_type == "button":
        apply_button_style(widget, node, texture_refs, warnings, name)
    elif node_type in ("text", "input", "scroll", "checkbox", "slider", "dropdown"):
        token = style_token(node, node_type)
        if token:
            added += add_skin_image(blueprint, parent, node, z_order - 1, used, warnings, texture_refs, explicit_token=token, parent_has_canvas_slot=parent_has_canvas_slot)
    if node_type in ("text", "input"):
        set_properties(widget, {{"text": str(node.get("text") or node.get("name") or "")}}, warnings, "widget " + name)
    elif node_type == "checkbox":
        set_properties(widget, {{"checkedState": "Checked" if node.get("checked") else "Unchecked"}}, warnings, "widget " + name)
    elif node_type == "slider":
        set_properties(widget, {{"value": to_float(node.get("value"), 0.5)}}, warnings, "widget " + name)
    child_parent = widget if node_type in ("screen", "panel", "scroll") and widget else parent
    child_parent_has_canvas_slot = node_type in ("screen", "panel")
    for index, child in enumerate(node.get("children") or []):
        added += add_node(blueprint, child_parent, child, z_order + index + 1, used, warnings, texture_refs, child_parent_has_canvas_slot)
    return added

def run():
    warnings = []
    texture_refs = build_texture_refs(warnings)
    call(ASSET, "create_folder", {{"path": FOLDER_PATH}})
    exists = call(ASSET, "exists", {{"path": WIDGET_PATH}})
    created = False
    if not exists:
        call(UMG, "CreateWidgetBlueprint", {{
            "folderPath": FOLDER_PATH,
            "assetName": ASSET_NAME,
            "parentClass": {{"refPath": "/Script/UMG.UserWidget"}},
            "rootWidgetClass": {{"refPath": "/Script/UMG.CanvasPanel"}},
        }})
        created = True

    blueprint = {{"refPath": WIDGET_PATH + "." + ASSET_NAME}}
    before = call(UMG, "GetWidgets", {{"widgetBlueprint": blueprint}})
    items = widget_items(before)
    root = ref(items[0].get("widget") if items else None)
    if not root:
        raise RuntimeError("GetWidgets did not return a root widget")
    removed = 0
    for item in items[1:]:
        widget = ref(item.get("widget") if isinstance(item, dict) else item)
        if widget:
            call(UMG, "RemoveWidget", {{"widgetBlueprint": blueprint, "widget": widget}})
            removed += 1

    root_node = STRUCTURE.get("root") if isinstance(STRUCTURE.get("root"), dict) else STRUCTURE
    used = {{"RootWidget": 1}}
    added = 0
    if isinstance(root_node, dict):
        for index, child in enumerate(root_node.get("children") or []):
            added += add_node(blueprint, root, child, index, used, warnings, texture_refs, True)

    call(UMG, "CompileWidgetBlueprint", {{"widgetBlueprint": blueprint}})
    call(ASSET, "save_assets", {{"asset_paths": [WIDGET_PATH]}})
    after = call(UMG, "GetWidgets", {{"widgetBlueprint": blueprint}})
    return {{
        "ok": True,
        "mode": "mcp",
        "widgetPath": WIDGET_PATH,
        "created": created,
        "removedWidgets": removed,
        "addedWidgets": added,
        "widgetCount": widget_count(after),
        "warnings": warnings,
        "textureRefs": len(texture_refs),
    }}
'''


def _safe_unreal_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip())
    name = name.strip("_") or "Widget"
    if name[0].isdigit():
        name = f"W_{name}"
    return name[:64]


def _widget_class_for_node(node_type: str) -> str:
    return {
        "screen": "/Script/UMG.CanvasPanel",
        "panel": "/Script/UMG.CanvasPanel",
        "image": "/Script/UMG.Image",
        "text": "/Script/UMG.TextBlock",
        "button": "/Script/UMG.Button",
        "input": "/Script/UMG.EditableTextBox",
        "scroll": "/Script/UMG.ScrollBox",
        "checkbox": "/Script/UMG.CheckBox",
        "slider": "/Script/UMG.Slider",
        "dropdown": "/Script/UMG.ComboBoxString",
    }.get(node_type, "/Script/UMG.Image")


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _anchors_for_node(node: dict[str, Any]) -> dict[str, Any]:
    preset = str(node.get("anchor") or node.get("anchors") or "top-left")
    presets = {
        "top-left": ((0.0, 0.0), (0.0, 0.0)),
        "top-right": ((1.0, 0.0), (1.0, 0.0)),
        "bottom-left": ((0.0, 1.0), (0.0, 1.0)),
        "bottom-right": ((1.0, 1.0), (1.0, 1.0)),
        "center": ((0.5, 0.5), (0.5, 0.5)),
        "full": ((0.0, 0.0), (1.0, 1.0)),
        "top-stretch": ((0.0, 0.0), (1.0, 0.0)),
        "bottom-stretch": ((0.0, 1.0), (1.0, 1.0)),
        "left-stretch": ((0.0, 0.0), (0.0, 1.0)),
        "right-stretch": ((1.0, 0.0), (1.0, 1.0)),
    }
    minimum, maximum = presets.get(preset, presets["top-left"])
    return {
        "minimum": {"x": minimum[0], "y": minimum[1]},
        "maximum": {"x": maximum[0], "y": maximum[1]},
    }


def _widget_items(widgets: Any) -> list[Any]:
    widgets = _unwrap_return_value(widgets)
    if isinstance(widgets, dict):
        for key in ("widgets", "items", "value"):
            value = widgets.get(key)
            if isinstance(value, list):
                return value
    return widgets if isinstance(widgets, list) else []


def _widget_count(widgets: Any) -> int:
    widgets = _unwrap_return_value(widgets)
    if isinstance(widgets, dict):
        count = widgets.get("widgetCount")
        if isinstance(count, int):
            return count
        info = widgets.get("info")
        if isinstance(info, dict) and isinstance(info.get("widgetCount"), int):
            return int(info["widgetCount"])
    return len(_widget_items(widgets))


def _extract_ref(value: Any, keys: tuple[str, ...]) -> dict[str, str] | None:
    value = _unwrap_return_value(value)
    if isinstance(value, dict) and isinstance(value.get("refPath"), str):
        return {"refPath": str(value["refPath"])}
    if isinstance(value, dict):
        for key in keys:
            child = value.get(key)
            ref = _extract_ref(child, ())
            if ref:
                return ref
    return None


def _widget_ref(item: Any) -> dict[str, str] | None:
    return _extract_ref(item, ("widget", "ref", "object"))


def _first_widget_ref(items: list[Any]) -> dict[str, str] | None:
    for item in items:
        ref = _widget_ref(item)
        if ref:
            return ref
    return None


def _guess_child_ref(parent_ref: dict[str, str], widget_name: str) -> str:
    parent = parent_ref.get("refPath", "")
    prefix = parent.rsplit(".", 1)[0] if "." in parent else parent
    return f"{prefix}:WidgetTree.{widget_name}"


def _bool_tool_result(value: Any) -> bool:
    value = _unwrap_return_value(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, dict):
        for key in ("exists", "result", "value", "success", "ok"):
            current = value.get(key)
            if isinstance(current, bool):
                return current
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1", "exists"}
    return False


def _unwrap_return_value(value: Any) -> Any:
    while isinstance(value, dict) and set(value.keys()) == {"returnValue"}:
        value = value.get("returnValue")
    return value
