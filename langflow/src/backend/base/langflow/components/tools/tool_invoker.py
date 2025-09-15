# tool_invoker_from_selection_min_msg.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import requests
from typing import Any, Dict, Tuple, Optional

from langflow.custom.custom_component.component import Component
from langflow.inputs.inputs import MultilineInput, BoolInput
from langflow.io import Output

try:
    from langflow.schema.message import Message  # Langflow >= 1.0
except Exception:  # pragma: no cover
    try:
        from langflow.schema import Message      # 일부 구버전
    except Exception:  # pragma: no cover
        Message = None  # type: ignore


class ToolInvokerFromSelectionMin(Component):
    display_name = "Tool Invoker"
    description = "Tool Picker로부터 전달받은 Tool을 Routing합니다."
    icon = "plug"
    category = "tools"

    # ──────────────────────────────────────────────────────────────────────
    # Inputs
    inputs = [
        # Chat/Text 모두 허용
        MultilineInput(
            name="user_input",
            display_name="User Input (Chat or Text)",
            info="Chat input/Text input 노드를 연결하거나 직접 입력하세요",
            input_types=["Message", "Text", "Any"],
        ),
        # ✅ Selection JSON: Message 타입도 허용
        MultilineInput(
            name="selection_json",
            display_name="Selection JSON (from Picker)",
            info='예: {"base_url":"http://host:8000","url_path":"/sub_graph","name":"sub_graph"} 또는 동일 내용을 담은 Message',
            value="",
            required=True,
            input_types=["Message", "Text", "Any"],
        ),
        # 고급: params/method는 기본 숨김
        MultilineInput(
            name="params_json",
            display_name="Params (JSON string)",
            info='예: {"top_k":3,"lang":"ko"}',
            value="",
            advanced=True,
            input_types=["Text", "Any"],
        ),
        MultilineInput(
            name="method_override",
            display_name="Method override (GET/POST/PUT/PATCH/DELETE)",
            value="POST",
            advanced=True,
            input_types=["Text", "Any"],
        ),
        BoolInput(
            name="force_get_query",
            display_name="Force GET query mode (optional)",
            value=False,
            advanced=True,
        ),
    ]

    # ──────────────────────────────────────────────────────────────────────
    # Outputs
    outputs = [
        Output(
            display_name="Chat Output",
            name="chat_output",
            method="run_message",
            types=["Message", "Text", "Any"],
            selected="Message",
        ),
    ]

    # ──────────────────────────────────────────────────────────────────────
    @staticmethod
    def _join_url(base: str, path: str, default_prefix: str = "/tools") -> str:
        b = (base or "").rstrip("/")
        p = (path or "/").strip()
        if not p.startswith("/"):
            p = "/" + p
        if p.startswith("/tools/") or p == "/tools":
            final_path = p
        else:
            final_path = (default_prefix.rstrip("/") + p) if not p.startswith(default_prefix.rstrip("/") + "/") else p
        return f"{b}{final_path}"

    @staticmethod
    def _extract_user_text(val: Any) -> str:
        if val is None:
            return ""
        # Message 우선
        try:
            if Message is not None and isinstance(val, Message):  # type: ignore
                txt = getattr(val, "text", "") or ""
                if txt:
                    return str(txt)
                data = getattr(val, "data", None)
                if isinstance(data, dict):
                    txt = data.get("text") or ""
                    if txt:
                        return str(txt)
        except Exception:
            pass
        if isinstance(val, str):
            return val
        if isinstance(val, (int, float)):
            return str(val)
        if isinstance(val, (dict, list)):
            return json.dumps(val, ensure_ascii=False)
        return ""

    @staticmethod
    def _parse_json_str(s: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        try:
            obj = json.loads(s or "{}")
            if isinstance(obj, dict):
                return obj, None
            return None, "selection_json must be a JSON object"
        except Exception as e:
            return None, f"invalid JSON: {e}"

    def _extract_selection(self, raw: Any) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        selection_json 입력을 Message/Text/Dict 등에서 안전 추출
        우선순위:
          - Message.text 가 유효 JSON이면 사용
          - Message.data 가 dict이면 그대로 사용 (또는 data['text'] 파싱)
          - str 이면 JSON 파싱
          - dict 이면 그대로 사용
        """
        if raw is None:
            return None, "selection_json is empty"

        # Message 타입
        try:
            if Message is not None and isinstance(raw, Message):  # type: ignore
                # 1) text 우선
                txt = getattr(raw, "text", "") or ""
                if isinstance(txt, str) and txt.strip():
                    obj, err = self._parse_json_str(txt)
                    if err is None:
                        return obj, None
                # 2) data 내부
                data = getattr(raw, "data", None)
                if isinstance(data, dict):
                    # data 가 곧 selection dict 인 경우
                    base_url = data.get("base_url")
                    url_path = data.get("url_path")
                    name = data.get("name")
                    if base_url or url_path or name:
                        return data, None
                    # 또는 data["text"] 에 JSON 문자열이 들어있는 경우
                    inner_txt = data.get("text")
                    if isinstance(inner_txt, str) and inner_txt.strip():
                        obj, err = self._parse_json_str(inner_txt)
                        if err is None:
                            return obj, None
                # 3) 더 이상 없으면 실패
                return None, "Message does not contain valid selection JSON"
        except Exception as e:
            return None, f"selection message parse error: {e}"

        # 문자열(JSON)
        if isinstance(raw, str):
            return self._parse_json_str(raw)

        # dict 그대로
        if isinstance(raw, dict):
            return raw, None

        # 기타(리스트 등) → 에러
        return None, "selection_json must be Message, JSON string, or object"

    def _call(self, method: str, url: str, payload: Dict[str, Any], timeout_s: int = 15):
        if method == "GET":
            params = dict(payload.get("params") or {})
            if "input" in payload and "input" not in params:
                params["input"] = payload["input"]
            return requests.get(url, params=params, timeout=timeout_s)
        else:
            return requests.request(method, url, json=payload, timeout=timeout_s)

    # 공통 코어: 실제 호출을 수행하고 텍스트(JSON 문자열)와 model_id(=tool_name)를 반환
    def _invoke_core(self) -> tuple[str, str]:
        # ✅ selection_json 추출(이제 Message/Text/Dict 모두 지원)
        sel_raw = getattr(self, "selection_json", None)
        sel, err = self._extract_selection(sel_raw)
        if err:
            return (json.dumps({"error": err, "raw_type": type(sel_raw).__name__}, ensure_ascii=False), "")

        base_url = (sel or {}).get("base_url", "").strip()
        url_path = (sel or {}).get("url_path", "").strip()
        tool_name = (sel or {}).get("name", "")  # model_id로도 사용
        if not base_url or not url_path:
            return (
                json.dumps({"error": "missing base_url or url_path in selection_json", "selection": sel}, ensure_ascii=False),
                tool_name or "",
            )

        # 입력 텍스트
        user_raw = getattr(self, "user_input", None)
        user_text = self._extract_user_text(user_raw)

        # payload
        payload: Dict[str, Any] = {}
        if user_text.strip():
            payload["input"] = user_text

        params_raw = (getattr(self, "params_json", "") or "").strip()
        if params_raw:
            try:
                payload["params"] = json.loads(params_raw)
            except Exception:
                return (json.dumps({"error": "params_json not valid JSON"}, ensure_ascii=False), tool_name or "")

        # 메서드/URL
        method = (getattr(self, "method_override", "POST") or "POST").strip().upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            method = "POST"
        method_eff = "GET" if bool(getattr(self, "force_get_query", False)) else method
        url = self._join_url(base_url, url_path, default_prefix="/tools")

        # 호출
        try:
            resp = self._call(method_eff, url, payload, timeout_s=15)
            resp.raise_for_status()
            try:
                body = resp.json()
                text = json.dumps(
                    {"request": {"method": method_eff, "url": url, "tool": tool_name}, "response": body},
                    ensure_ascii=False,
                    indent=2,
                )
            except Exception:
                text = json.dumps(
                    {"request": {"method": method_eff, "url": url, "tool": tool_name}, "response_text": resp.text},
                    ensure_ascii=False,
                    indent=2,
                )
            return (text, tool_name or "")
        except requests.HTTPError as e:
            status = getattr(e.response, "status_code", None)
            if status == 404 and not url.endswith("/"):
                url2 = url + "/"
                try:
                    resp2 = self._call(method_eff, url2, payload, timeout_s=15)
                    resp2.raise_for_status()
                    try:
                        text = json.dumps(
                            {
                                "request": {"method": method_eff, "url": url2, "tool": tool_name, "fallback": "trailing-slash"},
                                "response": resp2.json(),
                            },
                            ensure_ascii=False,
                            indent=2,
                        )
                    except Exception:
                        text = json.dumps(
                            {
                                "request": {"method": method_eff, "url": url2, "tool": tool_name, "fallback": "trailing-slash"},
                                "response_text": resp2.text,
                            },
                            ensure_ascii=False,
                            indent=2,
                        )
                    return (text, tool_name or "")
                except Exception as e2:
                    text = json.dumps(
                        {
                            "error": "HTTP 404 and trailing-slash fallback failed",
                            "first_try": {"method": method_eff, "url": url, "status": status},
                            "second_try": {"url": url2, "error": str(e2)},
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                    return (text, tool_name or "")
            # 기타 에러
            text = json.dumps(
                {
                    "error": "http_error",
                    "status": status,
                    "request": {"method": method_eff, "url": url, "tool": tool_name},
                    "detail": str(e),
                    "body_preview": getattr(e.response, "text", None),
                },
                ensure_ascii=False,
                indent=2,
            )
            return (text, tool_name or "")
        except Exception as e:
            text = json.dumps(
                {"error": "request_failed", "request": {"method": method_eff, "url": url, "tool": tool_name}, "detail": str(e)},
                ensure_ascii=False,
                indent=2,
            )
            return (text, tool_name or "")

    # ──────────────────────────────────────────────────────────────────────
    # Outputs 구현
    def run_text(self, **kwargs) -> str:
        text, _ = self._invoke_core()
        return text

    def run_message(self, **kwargs):
        text, _ = self._invoke_core()
        if Message is not None:
            try:
                return Message(text=text)
            except Exception:
                pass
        return {"text": text, "sender": "ToolInvoker"}

    def run_model_id(self, **kwargs) -> str:
        # selection_json.name 을 model_id로 반환 (Message 지원)
        sel_raw = getattr(self, "selection_json", None)
        sel, err = self._extract_selection(sel_raw)
        if err:
            return ""
        return str((sel or {}).get("name", "") or "")
