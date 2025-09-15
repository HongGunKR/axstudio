# coe_model_picker.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import socket
from typing import Any, Dict, List, Tuple, Optional

# stdlib HTTP
import urllib.request as urlreq
from urllib.error import URLError

from langflow.custom.custom_component.component import Component, _get_component_toolkit
from langflow.inputs.inputs import BoolInput, MessageInput, MultilineInput
from langflow.io import DropdownInput, Output

# ✅ tools 입력 활성화를 위해 추가
from langflow.base.agents.agent import LCToolsAgentComponent
from langflow.field_typing import Tool  # noqa: F401  (입력 타입 선언용)

# Langflow Message (버전 호환)
try:
    from langflow.schema.message import Message  # Langflow >= 1.0
except Exception:  # pragma: no cover
    try:
        from langflow.schema import Message  # 일부 구버전
    except Exception:  # pragma: no cover
        Message = None  # type: ignore

ALLOWED_OWNERS = {"openai", "sktax"}
DEFAULT_BACKEND = os.getenv("COE_BACKEND_URL", "http://host.docker.internal:8000").strip().rstrip("/")


def _http_get_json(url: str, timeout: float = 8.0) -> Dict[str, Any]:
    req = urlreq.Request(url, headers={"User-Agent": "langflow"})
    with urlreq.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _http_post_json(url: str, payload: Dict[str, Any], timeout: float = 30.0) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urlreq.Request(url, data=data, headers={"Content-Type": "application/json", "User-Agent": "langflow"})
    with urlreq.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


class CoEModelPicker(Component):
    """
    /v1/models에서 모델 목록을 name으로 표시(owned_by ∈ {openai, sktax} 필터),
    선택한 모델로 /v1/chat/completions를 호출합니다.

    추가:
      - tools 입력을 받아 OpenAI Tool Calling 포맷으로 직렬화하여 페이로드에 포함합니다.

    출력:
      - chat_output (Message 타입): Chat Output 싱크에 연결
      - text_output (Text 타입): Text Output 싱크에 연결
      - model_id (Text): 선택 모델의 id
    """

    display_name = "CoE Agents"
    description = "Pick a model by name then call /v1/chat/completions. (Supports Tools)"
    icon = "server"
    category = "agents"
    priority = 0

    # name -> id 매핑(런타임에 채움)
    _name_to_id: Dict[str, str] = {}
    # 최근 호출 결과 캐시
    _last_text: Optional[str] = None

    # ★ 첫 렌더링(마운트) 시 자동 로드 제어 플래그
    _did_initial_fetch: bool = False

    # ─────────────────────────────────────────────────────────────────────────
    # Inputs
    inputs = [
        # ── 기본 대화 입력
        MessageInput(
            name="chat_input",
            display_name="Chat Input",
            info="User message to send to the selected model.",
        ),
        MultilineInput(
            name="prompt",
            display_name="Prompt (System)",
            info="Optional system prompt (system role).",
        ),

        # ── 모델 선택
        DropdownInput(
            name="model_name",
            display_name="Model",
            options=[],
            value="",
            info="Models filtered by owned_by (openai, sktax).",
            real_time_refresh=True,
        ),

        # ── 백엔드/네트워크 옵션
        MultilineInput(
            name="backend_url",
            display_name="CoE Backend URL",
            value=DEFAULT_BACKEND,
            info="mac/Windows: http://greatcoe.cafe24.com",
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
        BoolInput(
            name="refresh_now",
            display_name="Refresh models now",
            value=False,
            info="Toggle to refresh the model list.",
            advanced=True,
            real_time_refresh=True,
        ),

        # ─────────────────────────────────────────────────────────────────
        # ✅ Tools 관련 입력 (Langflow Agent 컴포넌트와 동일한 UX 제공)
        #     - LCToolsAgentComponent._base_inputs 내부에 'tools', 'agent_description' 등 포함
        #     - 이 리스트를 그대로 병합하여 tools 선택 UI를 활성화
        *LCToolsAgentComponent._base_inputs,

        # 툴 사용 on/off 스위치 (선택)
        BoolInput(
            name="enable_tools",
            display_name="Enable Tools (Tool Calling)",
            value=True,
            info="If enabled and tools are provided, they will be sent to /v1/chat/completions as OpenAI-style tools.",
            advanced=True,
            real_time_refresh=False,
        ),
        BoolInput(
            name="tool_choice_auto",
            display_name='tool_choice = "auto"',
            value=True,
            info='If true, sets {"tool_choice": "auto"} in the request payload.',
            advanced=True,
            real_time_refresh=False,
        ),
    ]

    # ─────────────────────────────────────────────────────────────────────────
    # Outputs
    outputs = [
        Output(
            display_name="Chat Output",
            name="chat_output",
            method="run_message",
            types=["Message", "Text", "Any"],
            selected="Message",
        ),
        Output(
            display_name="Text Output",
            name="text_output",
            method="run_text",
            types=["Text", "Any"],
            selected="Text",
        ),
        Output(
            display_name="Model ID",
            name="model_id",
            method="get_model_id",
            types=["Text"],
            selected="Text",
        ),
    ]

    # ─────────────────────────────────────────────────────────────────────────
    # 내부 유틸
    @staticmethod
    def _normalize(base: str, force_https: bool) -> str:
        base = (base or DEFAULT_BACKEND).strip()
        if force_https and base.startswith("http://"):
            base = "https://" + base[len("http://") :]
        return base.rstrip("/")

    @staticmethod
    def _linux_fallback(base: str) -> str:
        return base.replace("host.docker.internal", "172.17.0.1") if "host.docker.internal" in base else base

    @staticmethod
    def _fallback_pairs() -> List[Tuple[str, str]]:
        return [
            ("GPT-4o Mini", "gpt-4o-mini"),
            ("GPT-4o", "gpt-4o"),
            ("text-embedding-3-small", "text-embedding-3-small"),
            ("AX4 Model", "ax4"),
        ]

    def _fetch_models(self, base_url: str) -> List[Tuple[str, str]]:
        """서버에서 모델 목록을 받아 (name, id)로 반환(필터 적용)"""
        url = base_url + "/v1/models"

        def _try(u: str) -> Dict[str, Any]:
            return _http_get_json(u, timeout=8.0)

        try:
            payload = _try(url)
        except (URLError, OSError, socket.gaierror):
            fb = self._linux_fallback(base_url) + "/v1/models"
            self.log(f"[CoEModelPicker] retry: {fb}")
            payload = _try(fb)

        data = (payload.get("result") or {}).get("data") or payload.get("data") or []
        pairs: List[Tuple[str, str]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            owner = str(item.get("owned_by") or "").strip().lower()
            if owner not in ALLOWED_OWNERS:
                continue
            mid = str(item.get("id") or "").strip()
            name = str(item.get("name") or mid).strip()
            if mid and name:
                pairs.append((name, mid))
        pairs.sort(key=lambda x: x[0].lower())
        return pairs

    # ─────────────────────────────────────────────────────────────────────────
    # 동적 UI 반영
    def update_build_config(self, build_config, field_value: Any, field_name: str | None = None):
        current_base = build_config.get("backend_url", {}).get("value", DEFAULT_BACKEND)
        current_force_https = bool(build_config.get("force_https", {}).get("value", False))
        if field_name == "backend_url":
            current_base = field_value
        elif field_name == "force_https":
            current_force_https = bool(field_value)

        base = self._normalize(current_base, current_force_https)

        current_options = build_config.get("model_name", {}).get("options") or []
        current_value = (build_config.get("model_name", {}) or {}).get("value") or ""

        # ★ 최초 마운트 또는 옵션이 비어있을 때/수동 토글 시 새로고침
        should_refresh = (
            not self._did_initial_fetch
            or field_name in {"backend_url", "force_https", "refresh_now"}
            or not current_options
            or current_value == "(click Refresh models now)"
        )

        if should_refresh:
            try:
                pairs = self._fetch_models(base)
                if pairs:
                    self._name_to_id = {name: mid for name, mid in pairs}
                    names = list(self._name_to_id.keys())
                    build_config["model_name"]["options"] = names
                    if not current_value or current_value not in names:
                        build_config["model_name"]["value"] = names[0]
                    self._did_initial_fetch = True  # ★ 한 번 성공하면 플래그 켜기
                    self.log(f"[CoEModelPicker] models loaded: {len(names)} from {base}")
                else:
                    # 서버 응답이 비었을 때 폴백
                    pairs = self._fallback_pairs()
                    self._name_to_id = {n: i for n, i in pairs}
                    names = [n for n, _ in pairs]
                    build_config["model_name"]["options"] = names
                    if not current_value or current_value not in names:
                        build_config["model_name"]["value"] = names[0]
                    self._did_initial_fetch = True
                    self.log("[CoEModelPicker] server returned empty; using fallback")
            except Exception as e:
                # 실패 시 폴백 후에도 초기화 완료 처리 (UI가 비지 않도록)
                pairs = self._fallback_pairs()
                self._name_to_id = {n: i for n, i in pairs}
                names = [n for n, _ in pairs]
                build_config["model_name"]["options"] = names
                if not current_value or current_value not in names:
                    build_config["model_name"]["value"] = names[0]
                self._did_initial_fetch = True
                self.log(f"[CoEModelPicker] fetch failed: {e}; using fallback list")

            # ★ 수동 토글이 켜져 있으면 끄면서(체크 해제) UI 깜빡임 방지
            if "refresh_now" in build_config:
                build_config["refresh_now"]["value"] = False

        return build_config

    # ─────────────────────────────────────────────────────────────────────────
    # 입력 수집
    def _collect_inputs(self) -> Tuple[str, str, str, str, bool, bool, bool]:
        # chat_input → Message 객체(.text) 또는 dict(data.text) 또는 str
        chat_text = ""
        msg = getattr(self, "chat_input", None)
        try:
            if msg is not None:
                # Message 타입
                chat_text = getattr(msg, "text", "") or ""
                if not chat_text and hasattr(msg, "data") and isinstance(msg.data, dict):
                    chat_text = msg.data.get("text") or ""
                if not chat_text and isinstance(msg, str):
                    chat_text = msg
        except Exception:
            pass

        prompt = (getattr(self, "prompt", "") or "").strip()
        model_name = (getattr(self, "model_name", "") or "").strip()
        backend_url = (getattr(self, "backend_url", "") or DEFAULT_BACKEND).strip()
        force_https = bool(getattr(self, "force_https", False))
        enable_tools = bool(getattr(self, "enable_tools", True))
        tool_choice_auto = bool(getattr(self, "tool_choice_auto", True))
        return chat_text, prompt, model_name, backend_url, force_https, enable_tools, tool_choice_auto

    # ─────────────────────────────────────────────────────────────────────────
    # Tools 직렬화
    def _build_tools_payload(self) -> List[Dict[str, Any]]:
        """
        Langflow에서 선택된 self.tools를 StructuredTool로 빌드한 뒤
        OpenAI Tool Calling 포맷으로 직렬화하여 반환합니다.
        """
        try:
            # Langflow 표준 방식으로 toolkits 생성
            component_toolkit = _get_component_toolkit()
            # 참고 소스와 동일한 명칭 사용 (Call_Agent)
            tools = component_toolkit(component=self).get_tools(
                tool_name="Call_Agent",
                tool_description=self.get_tool_description() if hasattr(self, "get_tool_description") else "",
                callbacks=None,
            )
        except Exception as e:
            self.log(f"[CoEModelPicker] tool toolkit build failed: {e}")
            return []

        tools_payload: List[Dict[str, Any]] = []
        for t in tools or []:
            try:
                name = getattr(t, "name", None) or ""
                description = getattr(t, "description", "") or ""
                # args_schema -> JSON Schema
                schema = {}
                args_schema = getattr(t, "args_schema", None)
                if args_schema is not None:
                    try:
                        schema = args_schema.schema()
                    except Exception:
                        schema = {"type": "object", "properties": {}}
                else:
                    schema = {"type": "object", "properties": {}}

                if name:
                    tools_payload.append(
                        {
                            "type": "function",
                            "function": {
                                "name": name,
                                "description": description,
                                "parameters": schema,
                            },
                        }
                    )
            except Exception as e:
                self.log(f"[CoEModelPicker] tool serialize failed: {e}")
                continue

        return tools_payload

    # ─────────────────────────────────────────────────────────────────────────
    # 공통 호출(한 번만 호출해서 캐시)
    def _call_chat(
        self,
        chat_input: str,
        prompt: str,
        model_name: str,
        backend_url: str,
        force_https: bool,
        enable_tools: bool,
        tool_choice_auto: bool,
    ) -> str:
        if self._last_text is not None:
            return self._last_text

        model_id = self._name_to_id.get(model_name or "", "")
        if not model_id:
            fpairs = self._fallback_pairs()
            if fpairs:
                model_id = fpairs[0][1]

        base = self._normalize(backend_url or DEFAULT_BACKEND, bool(force_https))
        url = base + "/v1/chat/completions"
        fb = self._linux_fallback(base)

        messages: List[Dict[str, Any]] = []
        if prompt:
            messages.append({"role": "system", "content": str(prompt)})
        messages.append({"role": "user", "content": str(chat_input or "")})

        payload: Dict[str, Any] = {"model": model_id or (model_name or ""), "messages": messages}

        # ✅ Tools 포함
        if enable_tools:
            tools_payload = self._build_tools_payload()
            if tools_payload:
                payload["tools"] = tools_payload
                if tool_choice_auto:
                    payload["tool_choice"] = "auto"

        def _try(u: str) -> Dict[str, Any]:
            return _http_post_json(u, payload, timeout=30.0)

        try:
            resp = _try(url)
        except (URLError, OSError, socket.gaierror):
            if base != fb:
                resp = _try(fb + "/v1/chat/completions")
            else:
                raise

        try:
            choice0 = (resp.get("choices") or [])[0]
            msg = (choice0.get("message") or {})
            content = msg.get("content") or ""

            # 기본적으로 텍스트 응답을 우선. 필요 시 tool_calls를 요약해 함께 노출하도록 확장 가능.
            self._last_text = str(content)
            return self._last_text
        except Exception:
            self._last_text = json.dumps(resp, ensure_ascii=False)[:2000]
            return self._last_text

    # ─────────────────────────────────────────────────────────────────────────
    # Outputs 구현
    def run_message(self, **kwargs: Any):
        (
            chat_text,
            prompt,
            model_name,
            backend_url,
            force_https,
            enable_tools,
            tool_choice_auto,
        ) = self._collect_inputs()
        text = self._call_chat(chat_text, prompt, model_name, backend_url, force_https, enable_tools, tool_choice_auto)
        if Message is not None:
            try:
                return Message(text=text)
            except Exception:
                pass
        # 폴백: Langflow가 dict도 표시 가능
        return {"text": text, "sender": "AI"}

    def run_text(self, **kwargs: Any) -> str:
        (
            chat_text,
            prompt,
            model_name,
            backend_url,
            force_https,
            enable_tools,
            tool_choice_auto,
        ) = self._collect_inputs()
        return self._call_chat(chat_text, prompt, model_name, backend_url, force_https, enable_tools, tool_choice_auto)

    def get_model_id(self) -> str:
        name = (getattr(self, "model_name", "") or "").strip()
        return self._name_to_id.get(name, "")
