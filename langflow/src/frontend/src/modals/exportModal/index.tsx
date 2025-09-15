/*
 * ExportModal_with_detailed_comments.tsx
 * ----------------------------------------------------------------------------
 * 목적(Purpose)
 * - Langflow의 현재 플로우를 파일로 Export(다운로드)하거나, CoE-Backend(사내 백엔드)에
 *   POST로 전송하는 모달 컴포넌트입니다.
 * - 사용자는 모달에서 플로우 이름/설명 수정, 엔드포인트 입력(또는 자동 placeholder 사용),
 *   Context(여러 개)를 선택/추가한 뒤 "Export"(파일 저장) 또는 "Send"(서버 전송)를 수행합니다.
 *
 * 주요 포인트(Key Points)
 * - 호출 대상 URL은 .env의 VITE_COE_BACKEND_URL로 고정되며, 미설정 시 기본값 사용.
 * - Endpoint 입력값이 비어 있으면 모달 열릴 때 생성된 랜덤 10자리 placeholder가 사용됩니다.
 * - Context는 다중 선택 + 검색 + 동적 추가를 지원(shadcn/ui Popover + Command)
 * - "Export"는 파일 다운로드(+ 비밀키 포함 여부 선택), "Send"는 서버 POST 요청을 수행.
 * - 네트워크 요청/응답 JSON을 화면에 디버깅용으로 표시/복사할 수 있음.
 */

import { forwardRef, type ReactNode, useEffect, useMemo, useState } from "react";
import { track } from "@/customization/utils/analytics"; // 이벤트 분석/추적 유틸
import useFlowStore from "@/stores/flowStore"; // 전역 플로우 상태(Zustand)
import type { FlowType } from "@/types/flow"; // 플로우 데이터 타입 정의
import IconComponent from "../../components/common/genericIconComponent"; // 아이콘 컴포넌트
import EditFlowSettings from "../../components/core/editFlowSettingsComponent"; // 이름/설명 편집 UI
import { Checkbox } from "../../components/ui/checkbox"; // shadcn UI 체크박스
import { Button } from "../../components/ui/button"; // shadcn UI 버튼
import { Input } from "../../components/ui/input"; // shadcn UI 인풋
import { Popover, PopoverTrigger, PopoverContent } from "../../components/ui/popover"; // 드롭다운 컨테이너
import {
  Command,
  CommandInput,
  CommandList,
  CommandGroup,
  CommandItem,
  CommandEmpty,
} from "../../components/ui/command"; // 검색형 리스트 컴포넌트
import { Check, Plus, ChevronsUpDown, X } from "lucide-react"; // 아이콘
import { API_WARNING_NOTICE_ALERT } from "../../constants/alerts_constants"; // 경고 문구 상수
import {
  ALERT_SAVE_WITH_API,
  EXPORT_DIALOG_SUBTITLE,
  SAVE_WITH_API_CHECKBOX,
} from "../../constants/constants"; // 안내 문구 상수
import useAlertStore from "../../stores/alertStore"; // 전역 알림(성공/에러/노티스)
import { useDarkStore } from "../../stores/darkStore"; // 버전 등 다크스토어(전역)
import { downloadFlow, removeApiKeys } from "../../utils/reactflowUtils"; // Export 관련 유틸
import BaseModal from "../baseModal"; // 모달 베이스 컴포넌트

// ─────────────────────────────────────────────────────────────────────────────
// 고정 호출 URL 구성
//  - .env(COE_BACKEND_URL)가 있으면 사용하고, 없으면 기본 URL로 fallback
//  - 뒤에 슬래시 중복 방지 후 "/flows/" 엔드포인트를 붙입니다.
// ─────────────────────────────────────────────────────────────────────────────
const RAW_BASE =
  (import.meta as any)?.env?.COE_BACKEND_URL || "http://greatcoe.cafe24.com";
const COE_FLOWS_URL = `${String(RAW_BASE).replace(/\/+$/, "")}/flows/`;

// 기본 Context 후보(드롭다운 초기값)
const DEFAULT_CONTEXT_OPTIONS = ["aider", "openWebUi", "continue.dev"] as const;

// 입력 문자열 정규화(공백 제거 + 소문자) : 검색/중복 비교용
function normalize(s: string) {
  return s.trim().toLowerCase();
}

// 10자리 랜덤 ID 생성 (모달 열릴 때 Endpoint placeholder로 사용)
function randomId(len = 10) {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz0123456789";
  // 브라우저 crypto API가 있으면 보안 랜덤 사용
  if (typeof crypto !== "undefined" && (crypto as any).getRandomValues) {
    const arr = new Uint32Array(len);
    (crypto as any).getRandomValues(arr);
    return Array.from(arr, (n) => chars[n % chars.length]).join("");
  }
  // 없으면 Math.random()으로 대체(충분)
  return Array.from({ length: len }, () => chars[Math.floor(Math.random() * chars.length)]).join("");
}

// ─────────────────────────────────────────────────────────────────────────────
// MultiSelect (Dropdown + Search + Add)
// - shadcn/ui Popover + Command를 조합하여 다중 선택, 검색, 신규 추가를 지원하는 컴포넌트
// - 외부에서 options/value/onChange/onCreate를 주입받아 상태는 상위에서 관리합니다.
// ─────────────────────────────────────────────────────────────────────────────

type MultiSelectProps = {
  options: string[]; // 선택 가능한 전체 옵션 목록
  value: string[]; // 현재 선택된 항목 배열
  onChange: (next: string[]) => void; // 선택 변경 콜백
  onCreate?: (label: string) => void; // 새 항목 추가 시 상위에 알림(옵션)
  placeholder?: string; // 버튼에 표시할 placeholder
  emptyText?: string; // 검색 결과 없음 표시 문구
  className?: string; // 버튼 className 확장
};

function MultiSelect({
  options,
  value,
  onChange,
  onCreate,
  placeholder = "Select contexts...",
  emptyText = "No results.",
  className,
}: MultiSelectProps) {
  // Popover 열림 상태
  const [open, setOpen] = useState(false);
  // 검색 쿼리 상태
  const [query, setQuery] = useState("");

  // 검색어가 존재하면 필터링, 없으면 전체 옵션
  const filtered = useMemo(() => {
    const q = normalize(query);
    return q ? options.filter((o) => normalize(o).includes(q)) : options;
  }, [options, query]);

  // 현재 query가 새로 추가 가능한 값인지 판단
  const canCreate =
    !!onCreate &&
    query.trim().length > 0 &&
    !options.some((o) => normalize(o) === normalize(query));

  // 항목 토글(선택/해제)
  function toggle(opt: string) {
    onChange(value.includes(opt) ? value.filter((v) => v !== opt) : [...value, opt]);
  }

  // 새 옵션 생성 후 선택까지 수행
  function createAndSelect() {
    const raw = query.trim();
    if (!raw) return;
    onCreate?.(raw);
    onChange(value.includes(raw) ? value : [...value, raw]);
    setQuery("");
  }

  // 버튼 내부 요약 텍스트: 선택 0개/1~3개/4개 이상에 따라 가독성 처리
  const summary =
    value.length === 0 ? (
      <span className="text-muted-foreground">{placeholder}</span>
    ) : value.length <= 3 ? (
      <span className="truncate">{value.join(", ")}</span>
    ) : (
      <span>{value.length} selected</span>
    );

  return (
    <Popover open={open} onOpenChange={setOpen}>
      {/* 버튼을 Popover 트리거로 사용 */}
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          role="combobox"
          aria-expanded={open}
          className={`w-full justify-between ${className ?? ""}`}
        >
          {summary}
          <ChevronsUpDown className="ml-2 h-4 w-4 opacity-50" />
        </Button>
      </PopoverTrigger>

      {/* 드롭다운 컨텐츠 */}
      <PopoverContent className="w-[var(--radix-popover-trigger-width)] p-0">
        <Command shouldFilter={false}>{/* 외부에서 이미 필터링 처리 */}
          {/* 상단 검색 + Add 버튼 */}
          <div className="flex items-center gap-2 p-2">
            <CommandInput
              value={query}
              onValueChange={setQuery}
              placeholder="Search or type to add…"
            />
            {canCreate && (
              <Button size="sm" variant="secondary" onClick={createAndSelect} title="Add">
                <Plus className="h-4 w-4" />
              </Button>
            )}
          </div>

          {/* 결과 리스트 */}
          <CommandList>
            {filtered.length === 0 ? (
              // 검색 결과가 없을 때: 안내 + 즉시 추가 버튼 제공
              <CommandEmpty className="py-4 text-sm">
                {emptyText}
                {canCreate && (
                  <div className="mt-2">
                    <Button size="sm" onClick={createAndSelect}>
                      <Plus className="mr-1 h-4 w-4" />
                      Add “{query.trim()}”
                    </Button>
                  </div>
                )}
              </CommandEmpty>
            ) : (
              // 검색 결과가 있을 때: 항목 렌더링 + 하단에 "Add" 단축 항목 제공
              <CommandGroup>
                {filtered.map((opt) => {
                  const isChecked = value.includes(opt);
                  return (
                    <CommandItem key={opt} value={opt} onSelect={() => toggle(opt)}>
                      <Check className={`mr-2 h-4 w-4 ${isChecked ? "opacity-100" : "opacity-0"}`} />
                      {opt}
                    </CommandItem>
                  );
                })}
                {canCreate && (
                  <CommandItem
                    value={`__create__:${query}`}
                    onSelect={createAndSelect}
                    className="text-primary"
                  >
                    <Plus className="mr-2 h-4 w-4" />
                    Add “{query.trim()}”
                  </CommandItem>
                )}
              </CommandGroup>
            )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// ExportModal
// - 플로우 설정 편집, 파일 Export, 서버 전송(POST) 기능을 포함하는 모달 컴포넌트
// - forwardRef는 외부에서 ref로 모달 제어 시 사용 가능(본 구현은 내부 open 상태도 지원)
// ─────────────────────────────────────────────────────────────────────────────

const ExportModal = forwardRef(
  (
    props: {
      children?: ReactNode; // 모달 트리거로 사용할 커스텀 노드
      open?: boolean; // 외부 제어용 열림 상태(선택)
      setOpen?: (open: boolean) => void; // 외부 제어용 setter(선택)
      flowData?: FlowType; // 외부에서 특정 플로우 데이터를 직접 주입할 수 있음
    },
    ref,
  ): JSX.Element => {
    // 전역에서 가져오는 값들
    const version = useDarkStore((state) => state.version); // 앱/테마 버전(로그 기록용)
    const setSuccessData = useAlertStore((state) => state.setSuccessData); // 성공 알림
    const setNoticeData = useAlertStore((state) => state.setNoticeData); // 노티스 알림
    const setErrorData = useAlertStore((state) => state.setErrorData); // 에러 알림
    const [saveWithApiChecked, setSaveWithApiChecked] = useState(false); // Export 시 API 키 포함 여부

    // 현재 페이지의 플로우(전역) 또는 props로 주입된 플로우 사용
    const currentFlowOnPage = useFlowStore((state) => state.currentFlow);
    const currentFlow = props.flowData ?? currentFlowOnPage;

    // 빌드 중 여부(Export 버튼 로딩에 사용)
    const isBuilding = useFlowStore((state) => state.isBuilding);

    // currentFlow 변경 시 이름/설명 로컬 상태 동기화
    useEffect(() => {
      setName(currentFlow?.name ?? "");
      setDescription(currentFlow?.description ?? "");
    }, [currentFlow?.name, currentFlow?.description]);

    // 이름/설명 로컬 상태
    const [name, setName] = useState(currentFlow?.name ?? "");
    const [description, setDescription] = useState(currentFlow?.description ?? "");

    // ▶ Endpoint 입력값과 상태들
    // - endpoint: 사용자가 직접 입력(비우면 placeholder 사용)
    // - endpointPlaceholder: 모달 열릴 때마다 새로 생성되는 10자리 랜덤 문자열
    // - endpointError: 유효성 오류 메시지
    const [endpoint, setEndpoint] = useState<string>("");
    const [endpointPlaceholder, setEndpointPlaceholder] = useState<string>("");
    const [endpointError, setEndpointError] = useState<string>("");

    // ▶ Context 선택 상태
    // - contextOptions: 드롭다운에 노출할 전체 옵션(동적 추가 가능)
    // - selectedContexts: 사용자가 선택한 컨텍스트 배열
    // - contextError: 유효성 오류 메시지
    const [contextOptions, setContextOptions] = useState<string[]>(
      [...DEFAULT_CONTEXT_OPTIONS],
    );
    const [selectedContexts, setSelectedContexts] = useState<string[]>([]);
    const [contextError, setContextError] = useState<string>("");

    // 디버그 출력을 위한 상태: 요청 본문, 응답 전문
    const [outgoingJson, setOutgoingJson] = useState<string>("");
    const [responseDump, setResponseDump] = useState<string>("");

    // 모달 open 상태: 외부 제어 props가 있으면 그것을 우선, 없으면 내부 상태 사용
    const [customOpen, customSetOpen] = useState(false);
    const [open, setOpen] =
      props.open !== undefined && props.setOpen !== undefined
        ? [props.open, props.setOpen]
        : [customOpen, customSetOpen];

    // 모달이 열릴 때마다 Endpoint placeholder 초기화 및 입력값/에러 리셋
    useEffect(() => {
      if (open) {
        setEndpointPlaceholder(randomId(10));
        setEndpoint("");
        setEndpointError("");
      }
    }, [open]);

    // 서버 전송 시 사용할 플로우 body 생성
    // - includeSecrets=true 이면 API 키 등 민감정보 포함(내부 테스트/백업용)
    // - false면 removeApiKeys를 통해 민감정보 제거(안전한 공유용)
    async function buildFlowBody(includeSecrets: boolean) {
      if (!currentFlow) throw new Error("No flow data");
      const base = {
        id: currentFlow.id,
        data: currentFlow.data!, // 런타임 상 존재 보장 가정
        description,
        name,
        last_tested_version: version,
        endpoint_name: currentFlow.endpoint_name,
        is_component: false,
        tags: currentFlow.tags,
      };
      return includeSecrets ? base : removeApiKeys(base);
    }

    // 텍스트를 클립보드로 복사(성공/실패 알림 처리)
    async function copyToClipboard(text: string) {
      try {
        await navigator.clipboard.writeText(text);
        setSuccessData({ title: "Copied to clipboard" });
      } catch (e: any) {
        setErrorData({ title: "Copy failed", list: [String(e?.message ?? e)] });
      }
    }

    // Context 옵션 목록에 새 항목 추가(중복 방지)
    function addContextOption(label: string) {
      const raw = label.trim();
      if (!raw) return;
      const exists = contextOptions.some((c) => normalize(c) === normalize(raw));
      if (!exists) setContextOptions((prev) => [...prev, raw]);
    }

    // "Send" 버튼 핸들러: 서버로 POST 전송
    async function handleSend() {
      try {
        // Endpoint 값 준비: 입력이 비어 있으면 placeholder 사용
        const epRaw = String(endpoint ?? "").trim();
        const ep = epRaw || endpointPlaceholder;

        // 1) 엔드포인트 필수 검증
        if (!ep) {
          const msg = "Endpoint is required.";
          setEndpointError(msg);
          setErrorData({ title: "Missing endpoint", list: [msg] });
          return;
        }
        setEndpointError("");

        // 2) 컨텍스트 최소 1개 선택 검증
        if (selectedContexts.length === 0) {
          const msg = "At least one context is required.";
          setContextError(msg);
          setErrorData({ title: "Missing context", list: [msg] });
          return;
        }
        setContextError("");

        // 3) 플로우 본문 생성(민감정보 포함 여부는 체크박스에 따름)
        const flow_body = await buildFlowBody(saveWithApiChecked);

        // 4) 전송 Payload 구성
        const payload = {
          endpoint: ep, // 문자열(빈값이면 placeholder)
          description,
          flow_body,
          flow_id: currentFlow!.id,
          context: selectedContexts, // string[] (여러 개)
        };

        // 디버깅을 위해 요청 본문을 예쁘게 표시
        const pretty = JSON.stringify(payload, null, 2);
        setOutgoingJson(pretty);
        setResponseDump("");
        console.debug("[ExportModal] POST", COE_FLOWS_URL, payload);

        // 5) 서버 호출(fetch). 네트워크 오류와 HTTP 오류를 분리 처리
        let res: Response;
        try {
          res = await fetch(COE_FLOWS_URL, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              accept: "application/json",
            },
            body: JSON.stringify(payload),
          });
        } catch (networkErr: any) {
          const msg = `Network error: ${String(networkErr?.message ?? networkErr)}`;
          console.error("[ExportModal] fetch error:", networkErr);
          setResponseDump(msg);
          setErrorData({ title: "Failed to send to CoE-Backend", list: [msg] });
          return;
        }

        // 6) 응답 본문을 텍스트로 받아 JSON이면 prettify
        const rawText = await res.text();
        let bodyPretty = rawText;
        try {
          bodyPretty = JSON.stringify(JSON.parse(rawText), null, 2);
        } catch {
          /* JSON이 아니면 원문 그대로 표시 */
        }

        // 7) 상태/URL/본문을 합쳐 화면에 표시
        const summary = `Status: ${res.status} ${res.statusText}\nURL: ${COE_FLOWS_URL}\n\n${bodyPretty}`;
        setResponseDump(summary);
        console.debug("[ExportModal] response:", summary);

        // 8) 상태 코드에 따라 알림 처리
        if (!res.ok) {
          setErrorData({
            title: "CoE-Backend returned an error",
            list: [`${res.status} ${res.statusText}`],
          });
        } else {
          setSuccessData({
            title: "Flow sent to CoE-Backend",
            list: [`Flow ID: ${currentFlow!.id}`],
          });
          // 분석 이벤트 트래킹(선택된 컨텍스트 배열 포함)
          track("Flow Sent To CoE", {
            flowId: currentFlow!.id,
            context: selectedContexts,
          });
        }
      } catch (err: any) {
        // 예기치 못한 런타임 오류: 화면/알림에 표시
        console.error(err);
        setResponseDump(String(err?.message ?? err));
        setErrorData({
          title: "Unexpected error while sending",
          list: [String(err?.message ?? err)],
        });
      }
    }

    return (
      <BaseModal
        size="smaller-h-full" // 화면 높이를 좀 더 활용하는 작은 모달 변형
        open={open}
        setOpen={setOpen}
        // Export 버튼(모달 Footer의 submit)이 눌렸을 때의 동작
        onSubmit={async () => {
          try {
            // 파일로 Export할 때 사용할 공통 base 오브젝트
            const base = {
              id: currentFlow!.id,
              data: currentFlow!.data!,
              description,
              name,
              last_tested_version: version,
              endpoint_name: currentFlow!.endpoint_name,
              is_component: false,
              tags: currentFlow!.tags,
            };

            if (saveWithApiChecked) {
              // API 키/시크릿 포함 저장(내부 백업/검증 용도)
              await downloadFlow(base, name!, description);
              setNoticeData({ title: API_WARNING_NOTICE_ALERT });
            } else {
              // 시크릿 제거 후 안전하게 저장(공유 목적)
              await downloadFlow(removeApiKeys(base), name!, description);
              setSuccessData({ title: "Flow exported successfully" });
            }

            // 모달 닫기 + 트래킹
            setOpen(false);
            track("Flow Exported", { flowId: currentFlow!.id });
          } catch (error) {
            // 파일 저장 실패는 콘솔에만 남김(요구 시 에러 알림 추가 가능)
            console.error("Error exporting flow:", error);
          }
        }}
      >
        {/* 모달을 여는 트리거. children이 있으면 감싸서 사용 */}
        <BaseModal.Trigger asChild>{props.children ?? <></>}</BaseModal.Trigger>

        {/* 헤더: 타이틀/서브타이틀 + 다운로드 아이콘 */}
        <BaseModal.Header description={EXPORT_DIALOG_SUBTITLE}>
          <span className="pr-2">Export</span>
          <IconComponent
            name="Download"
            className="h-6 w-6 pl-1 text-foreground"
            aria-hidden="true"
          />
        </BaseModal.Header>

        {/* 본문 컨텐츠 */}
        <BaseModal.Content>
          {/* 이름/설명 편집 섹션 */}
          <EditFlowSettings
            name={name}
            description={description}
            setName={setName}
            setDescription={setDescription}
          />

          {/* Endpoint 입력(필수) - payload.endpoint 용 */}
          <div className="mt-4">
            <label className="mb-1 block text-sm font-medium text-foreground">
              Endpoint <span className="text-destructive">*</span>
            </label>
            <Input
              placeholder={endpointPlaceholder || "──────────"}
              value={endpoint}
              onChange={(e) => setEndpoint(e.target.value)}
            />
            {endpointError ? (
              // 유효성 오류 메시지
              <div className="mt-1 text-xs text-destructive">{endpointError}</div>
            ) : (
              // 도움말: 실제 호출 URL은 고정이고, 입력 비우면 placeholder 자동 사용됨
              <div className="mt-1 text-xs text-muted-foreground">
                호출 URL은 고정: <code>{COE_FLOWS_URL}</code>
                <br />
                입력을 비워두면 Placeholder 값(
                <code>{endpointPlaceholder || "생성 중…"}</code>)이 자동 사용됩니다.
              </div>
            )}
          </div>

          {/* Context 드롭다운(다중선택 + Add) */}
          <div className="mt-4">
            <label className="mb-1 block text-sm font-medium text-foreground">
              Contexts <span className="text-destructive">*</span>
            </label>

            <MultiSelect
              options={contextOptions}
              value={selectedContexts}
              onChange={(next) => {
                setSelectedContexts(next);
                setContextError(""); // 변경 시 에러 해제
              }}
              onCreate={(label) => {
                addContextOption(label); // 새 항목 옵션에 추가
              }}
              placeholder="Select or add contexts..."
            />

            {/* 선택된 항목 chip 렌더링(미리보기 + 개별 제거) */}
            {selectedContexts.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-2">
                {selectedContexts.map((ctx) => (
                  <div
                    key={ctx}
                    className="inline-flex items-center rounded-full border px-2 py-0.5 text-xs"
                  >
                    <span>{ctx}</span>
                    <Button
                      variant="ghost"
                      size="xs"
                      className="ml-1 h-5 px-1"
                      onClick={() =>
                        setSelectedContexts((prev) => prev.filter((v) => v !== ctx))
                      }
                      title="Remove"
                    >
                      <X className="h-3 w-3" />
                    </Button>
                  </div>
                ))}
              </div>
            )}

            {/* 컨텍스트 관련 에러 또는 도움말 */}
            {contextError ? (
              <div className="mt-1 text-xs text-destructive">{contextError}</div>
            ) : (
              <div className="mt-1 text-xs text-muted-foreground">
                기본값: {DEFAULT_CONTEXT_OPTIONS.join(", ")} — 드롭다운에서 여러 개 선택하거나
                새 컨텍스트를 입력해 추가할 수 있습니다.
              </div>
            )}
          </div>

          {/* Export 옵션: API 키 포함 여부 */}
{/*           <div className="mt-3 flex items-center space-x-2">
            <Checkbox
              id="export-with-api"
              checked={saveWithApiChecked}
              onCheckedChange={(event: boolean) => setSaveWithApiChecked(event)}
            />
            <label htmlFor="export-with-api" className="export-modal-save-api text-sm">
              {SAVE_WITH_API_CHECKBOX}
            </label>
          </div> */}
          {/* API 포함 경고/안내 문구 */}
          {/* <span className="mt-1 text-xs text-destructive">{ALERT_SAVE_WITH_API}</span> */}

          {/* Outgoing JSON: 서버로 전송 직전의 payload 미리보기 */}
          {outgoingJson && (
            <div className="mt-3">
              <div className="mb-1 flex items-center justify-between">
                <div className="text-xs font-semibold text-muted-foreground">
                  Outgoing JSON (POST {COE_FLOWS_URL})
                </div>
                <Button
                  size="xs"
                  variant="secondary"
                  onClick={() => copyToClipboard(outgoingJson)}
                >
                  Copy
                </Button>
              </div>
              <pre className="max-h-32 overflow-auto rounded-md border bg-muted p-2 text-xs">
                {outgoingJson}
              </pre>
            </div>
          )}

          {/* Response: 서버로부터 받은 응답 전문 표시 */}
          {responseDump && (
            <div className="mt-2">
              <div className="mb-1 flex items-center justify-between">
                <div className="text-xs font-semibold text-muted-foreground">Response</div>
                <Button
                  size="xs"
                  variant="secondary"
                  onClick={() => copyToClipboard(responseDump)}
                >
                  Copy
                </Button>
              </div>
              <pre className="max-h-32 overflow-auto whitespace-pre-wrap rounded-md border bg-muted p-2 text-xs">
                {responseDump}
              </pre>
            </div>
          )}
        </BaseModal.Content>

        {/* Footer: 왼쪽 기본 Export(Submit) + 오른쪽 Send(서버 POST) */}
        <BaseModal.Footer
          submit={{
            label: "Download", // 파일 저장 버튼 라벨
            loading: isBuilding, // 빌드 중이면 로딩 표시
            dataTestId: "modal-export-button",
          }}
        >
          <Button
            data-testid="modal-send-button"
            className="ml-2"
            onClick={handleSend}
            title="Send current flow to CoE-Backend (shows request/response below)"
          >
            신청
          </Button>
        </BaseModal.Footer>
      </BaseModal>
    );
  },
);

export default ExportModal;
