import { forwardRef, type ReactNode, useEffect, useState } from "react";
import { track } from "@/customization/utils/analytics";
import useFlowStore from "@/stores/flowStore";
import type { FlowType } from "@/types/flow";
import IconComponent from "../../components/common/genericIconComponent";
import EditFlowSettings from "../../components/core/editFlowSettingsComponent";
import { Checkbox } from "../../components/ui/checkbox";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { API_WARNING_NOTICE_ALERT } from "../../constants/alerts_constants";
import {
  ALERT_SAVE_WITH_API,
  EXPORT_DIALOG_SUBTITLE,
  SAVE_WITH_API_CHECKBOX,
} from "../../constants/constants";
import useAlertStore from "../../stores/alertStore";
import { useDarkStore } from "../../stores/darkStore";
import { downloadFlow, removeApiKeys } from "../../utils/reactflowUtils";
import BaseModal from "../baseModal";

// 실제 호출 대상 URL은 .env 값을 기반으로 "고정"합니다.
const RAW_BASE =
  (import.meta as any)?.env?.VITE_COE_BACKEND_URL || "http://greatcoe.cafe24.com:8000";
const COE_FLOWS_URL = `${String(RAW_BASE).replace(/\/+$/, "")}/flows/`;

const ExportModal = forwardRef(
  (
    props: {
      children?: ReactNode;
      open?: boolean;
      setOpen?: (open: boolean) => void;
      flowData?: FlowType;
    },
    ref,
  ): JSX.Element => {
    const version = useDarkStore((state) => state.version);
    const setSuccessData = useAlertStore((state) => state.setSuccessData);
    const setNoticeData = useAlertStore((state) => state.setNoticeData);
    const setErrorData = useAlertStore((state) => state.setErrorData);
    const [checked, setChecked] = useState(false);

    const currentFlowOnPage = useFlowStore((state) => state.currentFlow);
    const currentFlow = props.flowData ?? currentFlowOnPage;
    const isBuilding = useFlowStore((state) => state.isBuilding);

    useEffect(() => {
      setName(currentFlow?.name ?? "");
      setDescription(currentFlow?.description ?? "");
    }, [currentFlow?.name, currentFlow?.description]);

    const [name, setName] = useState(currentFlow?.name ?? "");
    const [description, setDescription] = useState(currentFlow?.description ?? "");

    // 화면에서 입력받는 endpoint(= payload.endpoint 로만 사용). 필수값.
    const [endpoint, setEndpoint] = useState<string>("CoE-Backend");
    const [endpointError, setEndpointError] = useState<string>("");

    // 디버그 출력 상태
    const [outgoingJson, setOutgoingJson] = useState<string>("");
    const [responseDump, setResponseDump] = useState<string>("");

    const [customOpen, customSetOpen] = useState(false);
    const [open, setOpen] =
      props.open !== undefined && props.setOpen !== undefined
        ? [props.open, props.setOpen]
        : [customOpen, customSetOpen];

    async function buildFlowBody(includeSecrets: boolean) {
      if (!currentFlow) throw new Error("No flow data");
      const base = {
        id: currentFlow.id,
        data: currentFlow.data!,
        description,
        name,
        last_tested_version: version,
        endpoint_name: currentFlow.endpoint_name,
        is_component: false,
        tags: currentFlow.tags,
      };
      return includeSecrets ? base : removeApiKeys(base);
    }

    // 클립보드 복사 공통 함수
    async function copyToClipboard(text: string) {
      try {
        await navigator.clipboard.writeText(text);
        setSuccessData({ title: "Copied to clipboard" });
      } catch (e: any) {
        setErrorData({ title: "Copy failed", list: [String(e?.message ?? e)] });
      }
    }

    async function handleSend() {
      try {
        const ep = String(endpoint ?? "").trim();
        if (!ep) {
          const msg = "Endpoint is required.";
          setEndpointError(msg);
          setErrorData({ title: "Missing endpoint", list: [msg] });
          return;
        }
        setEndpointError("");

        const flow_body = await buildFlowBody(checked);
        const payload = {
          endpoint: ep, // 화면 입력값은 payload 안에만 사용
          description,
          flow_body,
          flow_id: currentFlow!.id,
          context: "Ax Studio",
        };

        // 전송 직전 JSON 출력
        const pretty = JSON.stringify(payload, null, 2);
        setOutgoingJson(pretty);
        setResponseDump("");
        console.debug("[ExportModal] POST", COE_FLOWS_URL, payload);

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

        const rawText = await res.text();
        let bodyPretty = rawText;
        try {
          bodyPretty = JSON.stringify(JSON.parse(rawText), null, 2);
        } catch {
          /* non-JSON OK */
        }

        const summary = `Status: ${res.status} ${res.statusText}\nURL: ${COE_FLOWS_URL}\n\n${bodyPretty}`;
        setResponseDump(summary);
        console.debug("[ExportModal] response:", summary);

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
          track("Flow Sent To CoE", { flowId: currentFlow!.id });
        }
      } catch (err: any) {
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
        size="smaller-h-full"
        open={open}
        setOpen={setOpen}
        onSubmit={async () => {
          try {
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
            if (checked) {
              await downloadFlow(base, name!, description);
              setNoticeData({ title: API_WARNING_NOTICE_ALERT });
            } else {
              await downloadFlow(removeApiKeys(base), name!, description);
              setSuccessData({ title: "Flow exported successfully" });
            }
            setOpen(false);
            track("Flow Exported", { flowId: currentFlow!.id });
          } catch (error) {
            console.error("Error exporting flow:", error);
          }
        }}
      >
        <BaseModal.Trigger asChild>{props.children ?? <></>}</BaseModal.Trigger>

        <BaseModal.Header description={EXPORT_DIALOG_SUBTITLE}>
          <span className="pr-2">Export</span>
          <IconComponent
            name="Download"
            className="h-6 w-6 pl-1 text-foreground"
            aria-hidden="true"
          />
        </BaseModal.Header>

        <BaseModal.Content>
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
              placeholder="CoE-Backend"
              value={endpoint}
              onChange={(e) => setEndpoint(e.target.value)}
            />
            {endpointError ? (
              <div className="mt-1 text-xs text-destructive">{endpointError}</div>
            ) : (
              <div className="mt-1 text-xs text-muted-foreground">
                호출 URL은 고정: <code>{COE_FLOWS_URL}</code> (payload.endpoint 에만 위 값이 전달됩니다)
              </div>
            )}
          </div>

          <div className="mt-3 flex items-center space-x-2">
            <Checkbox
              id="export-with-api"
              checked={checked}
              onCheckedChange={(event: boolean) => setChecked(event)}
            />
            <label htmlFor="export-with-api" className="export-modal-save-api text-sm">
              {SAVE_WITH_API_CHECKBOX}
            </label>
          </div>
          <span className="mt-1 text-xs text-destructive">{ALERT_SAVE_WITH_API}</span>

          {/* Outgoing JSON */}
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

          {/* Response */}
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

        {/* Footer: 기본 Export + 오른쪽 Send(위치 변경 없음) */}
        <BaseModal.Footer
          submit={{
            label: "Export",
            loading: isBuilding,
            dataTestId: "modal-export-button",
          }}
        >
          <Button
            data-testid="modal-send-button"
            className="ml-2"
            onClick={handleSend}
            title="Send current flow to CoE-Backend (shows request/response below)"
          >
            Send
          </Button>
        </BaseModal.Footer>
      </BaseModal>
    );
  },
);

export default ExportModal;