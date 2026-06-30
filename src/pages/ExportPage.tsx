// @ts-nocheck
import React from "react";
import { CheckCircle2, FileJson, RefreshCw } from "lucide-react";
import { useAppContext } from "../AppContext";

export default function ExportPage() {
  const {
    checkUnrealStatus,
    contentPath,
    currentManifest,
    disabled,
    exportUnrealScript,
    projectRoot,
    unrealStatus,
    validateCurrentManifest
  } = useAppContext();

  return (
    <div className="detail-grid">
      <section className="detail-card">
        <div className="section-header">
          <div>
            <div className="section-kicker">Unreal 连接</div>
            <strong>{unrealStatus?.mode || "未检测"}</strong>
          </div>
          <button className="icon-action" onClick={checkUnrealStatus} disabled={disabled} aria-label="检测 Unreal MCP">
            <RefreshCw size={16} />
          </button>
        </div>
        <div className="runtime-list">
          <span>
            <strong>MCP</strong>
            <small>{unrealStatus?.detail || "尚未检测"}</small>
          </span>
          <span>
            <strong>UE 内容路径</strong>
            <small>{contentPath}</small>
          </span>
          <span>
            <strong>兜底输出</strong>
            <small>{projectRoot}/exports/unreal</small>
          </span>
        </div>
        <div className="button-row">
          <button className="secondary-action tall" onClick={validateCurrentManifest} disabled={disabled || !currentManifest}>
            <CheckCircle2 size={15} />
            校验资产清单
          </button>
          <button className="primary-action" onClick={exportUnrealScript} disabled={disabled || !currentManifest}>
            <FileJson size={15} />
            生成 Python 脚本
          </button>
        </div>
      </section>

      <section className="detail-card">
        <div className="section-kicker">导出源数据</div>
        <textarea className="json-view" readOnly value={JSON.stringify(currentManifest || {}, null, 2)} />
      </section>
    </div>
  );
}
