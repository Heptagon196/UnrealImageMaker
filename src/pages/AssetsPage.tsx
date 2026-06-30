// @ts-nocheck
import React from "react";
import { CheckCircle2, FileImage } from "lucide-react";
import { useAppContext } from "../AppContext";

export default function AssetsPage() {
  const {
    AssetPreview,
    currentManifest,
    disabled,
    issueCount,
    lastResult,
    selectedAsset,
    validateCurrentManifest,
    validationResult
  } = useAppContext();

  return (
    <div className="detail-grid">
      <section className="detail-card">
        <div className="section-header">
          <div>
            <div className="section-kicker">当前资产</div>
            <strong>{selectedAsset?.name || "未选择资产"}</strong>
          </div>
          <FileImage size={20} />
        </div>
        {AssetPreview()}
      </section>

      <section className="detail-card">
        <div className="section-header">
          <div>
            <div className="section-kicker">资产清单 / 质量</div>
            <strong>{issueCount} 个问题</strong>
          </div>
          <button className="icon-action" onClick={validateCurrentManifest} disabled={disabled || !currentManifest} aria-label="校验资产清单">
            <CheckCircle2 size={16} />
          </button>
        </div>
        {validationResult && (
          <div className="issue-list">
            {validationResult.errors.map((item) => (
              <span key={item}>
                <b>结构</b>
                {item}
              </span>
            ))}
            {validationResult.issues.map((item, index) => (
              <span key={`${item.code}-${index}`}>
                <b>{item.severity || "问题"}</b>
                {item.message || item.code}
              </span>
            ))}
            {issueCount === 0 && (
              <span>
                <b>通过</b>
                当前资产清单未发现问题。
              </span>
            )}
          </div>
        )}
        <textarea className="json-view" readOnly value={JSON.stringify(lastResult || currentManifest || {}, null, 2)} />
      </section>
    </div>
  );
}
