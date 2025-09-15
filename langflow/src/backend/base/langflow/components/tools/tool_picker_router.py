# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from typing import Any, Dict, Iterable

from langflow.custom.custom_component.component import Component
from langflow.inputs.inputs import MessageInput, DropdownInput, BoolInput
from langflow.io import Output

# Langflow Message (버전 호환)
try:
    from langflow.schema.message import Message  # Langflow >= 1.0
except Exception:  # pragma: no cover
    try:
        from langflow.schema import Message  # 일부 구버전
    except Exception:  # pragma: no cover
        Message = None  # type: ignore


class ToolPickerJsonRouterMessageOnlyV2(Component):
    """
    Message(JSON) → Message(JSON or string).

    - 입력: Tool Picker가 반환한 JSON을 담은 Message
            (message.text=stringified JSON 또는 message.data=dict)
    - 출력:
        1) original_message: 원본 JSON 전체를 Message(text=JSON string)로 패스스루
        2) prompt_value_message: 선택된 key의 값을 Message(text=...)로 출력
    - 드롭다운: 입력 JSON의 키들을 동적으로 로드하여 선택지로 표시
    """

    display_name = "Tool Picker Router"
    description = "JSON Message를 그대로 전달하거나, 특정 Key만 선택해서 전달할 수 있습니다."
    icon = "plug"
    category = "tools"

    # ─────────────────────────────────────────────────────────────────────────
    # Inputs (Message only)
    inputs = [
        MessageInput(
            name="tool_message",
            display_name="Tool JSON",
            info="Tool Picker가 반환한 JSON Message.",
        ),
        DropdownInput(
            name="key_for_prompt",
            display_name="Key",
            options=[],          # ⚠️ 동적으로 채움
            value="",            # ⚠️ 동적으로 기본값 지정
            info="Toll Picker가 반환한 JSON의 Key 목록 출력. Input이 변경되면 동적으로 변경됨.",
            real_time_refresh=True,
        ),
        BoolInput(
            name="minify_original",
            display_name="Minify original JSON",
            value=True,
            advanced=True,
            info="If true, original JSON is compact (no spaces). Otherwise pretty-printed.",
        ),
    ]

    # ─────────────────────────────────────────────────────────────────────────
    # Outputs (Message only, 2개)
    outputs = [
        Output(
            display_name="original_message",
            name="original_message",
            method="get_original_message",
            types=["Message"],
            selected="Message",
        ),
        Output(
            display_name="prompt_value_message",
            name="prompt_value_message",
            method="get_prompt_value_message",
            types=["Message"],
            selected="Message",
        ),
    ]

    # ─────────────────────────────────────────────────────────────────────────
    # Dynamic UI (입력 JSON의 키로 드롭다운 옵션 구성)
    def update_build_config(self, build_config, field_value: Any, field_name: str | None = None):
        """
        - tool_message 값이 바뀌거나 처음 로드될 때, JSON을 파싱해 키 목록을 드롭다운 옵션으로 세팅
        - 기본 선택값은 'name' 우선, 없으면 첫 번째 키
        """
        # 1) 후보 Message 값 얻기 (이번 변경 혹은 현재 보유 값)
        candidate = None
        if field_name == "tool_message":
            candidate = field_value
        if candidate is None:
            candidate = (build_config.get("tool_message") or {}).get("value")

        # 2) candidate에서 키 목록 추출
        keys = list(self._extract_json_keys_from_candidate(candidate))

        # 3) 폴백(키가 없으면 기존에 자주 쓰는 키를 보여줌)
        fallback_keys = ["name", "url_path", "description", "base_url"]
        if not keys:
            keys = fallback_keys

        # 4) 드롭다운 옵션/값 갱신
        try:
            build_config["key_for_prompt"]["options"] = keys
        except Exception:
            pass

        current_value = (build_config.get("key_for_prompt") or {}).get("value") or ""
        # 'name'이 있으면 기본으로, 없으면 첫 키
        default_value = "name" if "name" in keys else (keys[0] if keys else "")
        if not current_value or current_value not in keys:
            try:
                build_config["key_for_prompt"]["value"] = default_value
            except Exception:
                pass

        return build_config

    # ─────────────────────────────────────────────────────────────────────────
    # 내부 유틸: 입력 Message → dict, 키 추출
    def _coerce_to_dict(self) -> Dict[str, Any]:
        """
        입력 Message에서 JSON을 dict로 변환.
        - message.text를 JSON으로 파싱 시도
        - 실패 시 message.data(dict)이면 그대로 사용
        - 둘 다 아니면 빈 dict
        """
        msg = getattr(self, "tool_message", None)

        # 1) Message 타입: text 우선
        if Message is not None and isinstance(msg, Message):
            try:
                txt = getattr(msg, "text", "") or ""
                if isinstance(txt, str) and txt.strip():
                    try:
                        return json.loads(txt)
                    except Exception:
                        # 문자열이지만 JSON 아님 → text를 그대로 value로 감싼다
                        return {"value": txt}
                data = getattr(msg, "data", None)
                if isinstance(data, dict):
                    return data
            except Exception:
                pass

        # 2) 혹시 dict나 str이 직접 들어오는 환경일 경우(호환)
        if isinstance(msg, dict):
            return msg
        if isinstance(msg, str) and msg.strip():
            try:
                return json.loads(msg)
            except Exception:
                return {"value": msg}

        return {}

    def _extract_json_keys_from_candidate(self, candidate: Any) -> Iterable[str]:
        """
        update_build_config용: 아직 self.tool_message로 주입되기 전 값(field_value/build_config.value)에서
        안전하게 키 목록을 추출.
        """
        # Message-like(dict로 전달) 형태일 수 있음
        # 1) dict(payload) → 키
        if isinstance(candidate, dict):
            # Langflow가 Message를 dict로 serialize하여 value에 넣을 수도 있음
            # text 우선
            txt = candidate.get("text")
            data = candidate.get("data")
            if isinstance(txt, str) and txt.strip():
                try:
                    obj = json.loads(txt)
                    if isinstance(obj, dict):
                        return obj.keys()
                except Exception:
                    return ["value"]  # 문자열을 감싼 키
            if isinstance(data, dict):
                return data.keys()
            # dict 자체가 JSON일 수도 있음
            return candidate.keys()

        # 2) str → JSON 파싱
        if isinstance(candidate, str) and candidate.strip():
            try:
                obj = json.loads(candidate)
                if isinstance(obj, dict):
                    return obj.keys()
            except Exception:
                return ["value"]

        return []

    def _original_json_str(self, obj: Dict[str, Any]) -> str:
        if getattr(self, "minify_original", True):
            return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        return json.dumps(obj, ensure_ascii=False, indent=2)

    def _field_str(self, key: str) -> str:
        data = self._coerce_to_dict()
        val = data.get(key, "")
        if isinstance(val, (dict, list)):
            return json.dumps(val, ensure_ascii=False)
        return str(val) if val is not None else ""

    def _make_message(self, text: str) -> Any:
        """Message(text=...)로 감싸되, 실패 시 dict로 폴백."""
        if Message is not None:
            try:
                return Message(text=text)
            except Exception:
                pass
        return {"text": text, "sender": "AI"}

    # ─────────────────────────────────────────────────────────────────────────
    # Outputs 구현 (둘 다 Message)
    def get_original_message(self) -> Any:
        data = self._coerce_to_dict()
        return self._make_message(self._original_json_str(data))

    def get_prompt_value_message(self) -> Any:
        key = (getattr(self, "key_for_prompt", "") or "").strip()
        if not key:
            # 드롭다운이 비어있다면 안전 폴백
            # 입력 JSON에서 첫 키를 택하거나 'name' 시도
            keys = list(self._coerce_to_dict().keys())
            key = "name" if "name" in keys else (keys[0] if keys else "")
        return self._make_message(self._field_str(key))
