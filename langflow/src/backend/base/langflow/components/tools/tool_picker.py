# tool_picker_dropdown_message_v3.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import socket
from typing import Any, Dict, List, Optional, Tuple
import urllib.request as urlreq
from urllib.error import URLError

from langflow.custom.custom_component.component import Component
from langflow.inputs.inputs import MessageInput, MultilineInput, BoolInput
from langflow.io import DropdownInput, Output

# Langflow Message (버전 호환)
try:
    from langflow.schema.message import Message  # Langflow >= 1.0
except Exception:  # pragma: no cover
    try:
        from langflow.schema import Message  # 일부 구버전
    except Exception:  # pragma: no cover
        Message = None  # type: ignore


def _http_get_json(url: str, timeout: float = 8.0) -> Dict[str, Any] | List[Any]:
    req = urlreq.Request(url, headers={"User-Agent": "langflow"})
    with urlreq.urlopen(req, timeout=timeout) as r:
        body = r.read().decode("utf-8")
        return json.loads(body)


class ToolPickerDropdownSafeMessage(Component):
    """
    /tools를 GET하여 드롭다운 옵션을 구성하고,
    선택된 항목(name/url_path/description/base_url)을 JSON 문자열(Message)로 반환합니다.

    입력:
      - chat_input (Message): 상류 노드에서 넘어오는 메시지(선택 사항, 내용은 사용하지 않아도 됨)
      - backend_base_url (Text): ex) http://greatcoe.cafe24.com:8080
      - selected_tool (Dropdown): /tools 결과로 동적 채움
      - refresh_now (Bool): 토글 시 목록 새로고침
      - force_https (Bool): http→https 강제 전환(옵션)

    출력:
      - picked_tool (Message): {"name","url_path","description","base_url"} JSON 문자열
      - picked_tool_text (Text): 동일 JSON의 Text 버전(옵션)
    """

    display_name = "Tool Picker"
    description = "/tools를 GET해 드롭다운 옵션을 만들고, 선택 결과를 Message(JSON)로 반환합니다."
    icon = "plug"
    category = "tools"
    priority = 0

    # 내부 상태
    _did_initial_fetch: bool = False
    _last_tools: List[Dict[str, Any]] = []

    # ──────────────────────────────────────────────────────────────────────
    # Inputs
    inputs = [
        MessageInput(
            name="chat_input",
            display_name="Chat Input (optional)",
            advanced=True,
            info="상류 Message 노드와의 연결을 위한 입력(내용은 선택적으로 사용).",
        ),
        MultilineInput(
            name="backend_base_url",
            display_name="Base URL",
            value="http://greatcoe.cafe24.com:8080",
            info="예: http://greatcoe.cafe24.com:8080",
            real_time_refresh=True,
        ),
        DropdownInput(
            name="selected_tool",
            display_name="Select a Tool",
            options=[],
            value="",
            info="/tools 응답으로 동적 로드됩니다.",
            real_time_refresh=True,
        ),
        BoolInput(
            name="refresh_now",
            display_name="Refresh tools now",
            value=False,
            info="토글 시 /tools 목록을 즉시 새로고침합니다.",
            advanced=True,
            real_time_refresh=True,
        ),
        BoolInput(
            name="force_https",
            display_name="Force HTTPS",
            value=False,
            advanced=True,
            real_time_refresh=True,
        ),
    ]

    # ──────────────────────────────────────────────────────────────────────
    # Outputs
    outputs = [
        Output(
            display_name="Picked Tool (Message)",
            name="picked_tool",
            method="run_message",
            types=["Message", "Text", "Any"],
            selected="Message",
        ),
        Output(
            display_name="Picked Tool (Text)",
            name="picked_tool_text",
            method="run_text",
            types=["Text", "Any"],
            selected="Text",
        ),
    ]

    # ──────────────────────────────────────────────────────────────────────
    # 유틸
    @staticmethod
    def _normalize_base(base: str, force_https: bool) -> str:
        base = (base or "").strip()
        if not base:
            return ""
        if force_https and base.startswith("http://"):
            base = "https://" + base[len("http://") :]
        return base.rstrip("/")

    @staticmethod
    def _linux_fallback(base: str) -> str:
        return base.replace("host.docker.internal", "172.17.0.1") if "host.docker.internal" in base else base

    def _fetch_tools(self, base_url: str) -> List[Dict[str, Any]]:
        url = f"{base_url}/tools"

        def _try(u: str):
            return _http_get_json(u, timeout=8.0)

        try:
            payload = _try(url)
        except (URLError, OSError, socket.gaierror):
            fb = self._linux_fallback(base_url) + "/tools"
            self.log(f"[ToolPicker] retry: {fb}")
            payload = _try(fb)

        # payload: {tools:[...]} | [...] | {...}
        if isinstance(payload, dict) and "tools" in payload:
            tools = payload.get("tools") or []
        elif isinstance(payload, list):
            tools = payload
        else:
            tools = [payload]

        norm: List[Dict[str, Any]] = []
        for t in tools:
            if not isinstance(t, dict):
                continue
            name = str((t.get("name") or "")).strip()
            url_path = str((t.get("url_path") or "")).strip()
            desc = str((t.get("description") or "")).strip()
            if not name and not url_path:
                continue
            norm.append({"name": name, "url_path": url_path, "description": desc})
        # 이름 기준 정렬(있으면)
        norm.sort(key=lambda x: (x.get("name") or x.get("url_path") or "").lower())
        return norm

    # ──────────────────────────────────────────────────────────────────────
    # 동적 UI 반영(옵션/값 실시간 갱신)
    def update_build_config(self, build_config, field_value: Any, field_name: str | None = None):
        base = build_config.get("backend_base_url", {}).get("value") or ""
        force_https = bool(build_config.get("force_https", {}).get("value", False))
        if field_name == "backend_base_url":
            base = field_value or ""
        elif field_name == "force_https":
            force_https = bool(field_value)

        base = self._normalize_base(base, force_https)

        current_options = build_config.get("selected_tool", {}).get("options") or []
        current_value = (build_config.get("selected_tool", {}) or {}).get("value") or ""

        should_refresh = (
            not self._did_initial_fetch
            or field_name in {"backend_base_url", "force_https", "refresh_now"}
            or not current_options
            or current_value == "(click Refresh tools now)"
        )

        if should_refresh and base:
            try:
                tools = self._fetch_tools(base)
                self._last_tools = tools
                names = [t["name"] or t["url_path"] for t in tools]
                build_config["selected_tool"]["options"] = names
                if not current_value or current_value not in names:
                    build_config["selected_tool"]["value"] = names[0] if names else ""
                self._did_initial_fetch = True
                self.log(f"[ToolPicker] tools loaded: {len(names)} from {base}/tools")
            except Exception as e:
                # 실패 시 옵션 비우고, 초기화 완료 처리(에디터가 비지 않도록)
                build_config["selected_tool"]["options"] = []
                if "value" in build_config.get("selected_tool", {}):
                    build_config["selected_tool"]["value"] = ""
                self._did_initial_fetch = True
                self.log(f"[ToolPicker] fetch failed: {e}")

            # 토글은 자동으로 내리기
            if "refresh_now" in build_config:
                build_config["refresh_now"]["value"] = False

        return build_config

    # ──────────────────────────────────────────────────────────────────────
    # 선택 로직
    @staticmethod
    def _pick_match(tools: List[Dict[str, Any]], selected: str) -> Optional[Dict[str, Any]]:
        sel = (selected or "").strip()
        if not tools:
            return None
        if not sel:
            return tools[0]
        sel_lower = sel.lower()
        for t in tools:
            name = (t.get("name") or "").strip()
            url_path = (t.get("url_path") or "").strip()
            if sel == name or sel == url_path or sel_lower == name.lower() or sel_lower == url_path.lower():
                return t
        # fallback: 첫 번째
        return tools[0]

    # ──────────────────────────────────────────────────────────────────────
    # 공통 실행
    def _run(self) -> str:
        # 입력 값 모으기
        base = (getattr(self, "backend_base_url", "") or "").strip()
        force_https = bool(getattr(self, "force_https", False))
        selected = (getattr(self, "selected_tool", "") or "").strip()

        base = self._normalize_base(base, force_https)
        if not base:
            return json.dumps({"error": "base_url is empty"}, ensure_ascii=False)

        # 필요 시 즉시 갱신(런타임에서 캐시가 비어 있으면)
        if not self._last_tools:
            try:
                self._last_tools = self._fetch_tools(base)
            except Exception as e:
                return json.dumps({"error": "failed to fetch tools", "detail": str(e)}, ensure_ascii=False)

        match = self._pick_match(self._last_tools, selected)
        if not match:
            return json.dumps({"error": "tool not found", "selected": selected}, ensure_ascii=False)

        result = {
            "name": match.get("name", ""),
            "url_path": match.get("url_path", ""),
            "description": match.get("description", ""),
            # ✅ ToolInvoker 등 다음 노드에 전달할 실제 호출 base (호출 측에서 /tools 이어붙이지 않도록 원본 base만 전달)
            "base_url": f"{base}/tools",
        }
        return json.dumps(result, ensure_ascii=False)

    # ──────────────────────────────────────────────────────────────────────
    # Outputs 구현
    def run_message(self, **kwargs: Any):
        text = self._run()
        if Message is not None:
            try:
                return Message(text=text)
            except Exception:
                pass
        return {"text": text, "sender": "ToolPicker"}

    def run_text(self, **kwargs: Any) -> str:
        return self._run()
