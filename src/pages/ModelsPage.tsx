// @ts-nocheck
import React, { useEffect, useState } from "react";
import { Command } from "cmdk";
import { Download, RefreshCw, Trash2 } from "lucide-react";
import { useAppContext } from "../AppContext";

export default function ModelsPage() {
  const {
    deleteModel,
    disabled,
    downloadSam,
    installMarker,
    installedCount,
    modelCacheDir,
    modelDependencies,
    modelStatusLabel,
    models,
    refreshModels,
    runAction,
    runtimeSettings
  } = useAppContext();

  function ModelsPage() {  
    return (  
      <section className="full-page-card">  
        <div className="section-header">  
          <div>  
            <div className="section-kicker">本地模型</div>  
            <strong>{installedCount} / {models.length} 已安装</strong>  
          </div>  
          <button className="secondary-action tall" onClick={() => runAction("刷新模型", refreshModels, undefined, { notify: false })} disabled={disabled}>  
            <RefreshCw size={15} />  
            刷新  
          </button>  
        </div>  
        <small className="path-hint">{modelCacheDir || runtimeSettings?.modelCacheDir || "model-cache"}</small>  
        <div className="dependency-grid">  
          {(modelDependencies || []).map((dependency) => (  
            <span className={`dependency-pill ${dependency.available ? "ok" : "missing"}`} key={dependency.id}>  
              <strong>{dependency.label}</strong>  
              <small>{dependency.detail}</small>  
            </span>  
          ))}  
        </div>  
        <div className="model-grid">  
          {models.length === 0 ? (  
            <div className="empty-card">模型注册表为空。请先确认本地服务可用，然后刷新模型。</div>  
          ) : (  
            models.map((model) => (  
              <article className="model-card" key={model.id}>  
                <div className="section-header">  
                  <div>  
                    <strong>{model.display_name}</strong>  
                    <small>{model.provider} · {model.task} · {model.version} · {model.recommended_vram_gb}GB · {model.size_hint}</small>  
                  </div>  
                  <span className={`pill ${model.status}`}>{modelStatusLabel(model.status)}</span>  
                </div>  
                <div className="model-meta">  
                  <span>  
                    <b>许可</b>  
                    {model.license}  
                  </span>  
                  <span>  
                    <b>本地路径</b>  
                    {model.local_path || "-"}  
                  </span>  
                  <span>  
                    <b>校验值</b>  
                    {model.checksum || "未锁定"}  
                  </span>  
                  <span>  
                    <b>来源</b>  
                    {model.source}  
                  </span>  
                </div>  
                <div className="button-row">  
                  {model.id.startsWith("sam2.1") ? (  
                    <button className="secondary-action" onClick={() => downloadSam(model.id)} disabled={disabled}>  
                      <Download size={14} />  
                      下载  
                    </button>  
                  ) : (  
                    <button className="secondary-action" onClick={() => installMarker(model.id)} disabled={disabled}>  
                      <Download size={14} />  
                      登记  
                    </button>  
                  )}  
                  <button className="secondary-action danger-action" onClick={() => deleteModel(model.id)} disabled={disabled}>  
                    <Trash2 size={14} />  
                    删除  
                  </button>  
                </div>  
              </article>  
            ))  
          )}  
        </div>  
      </section>  
    );  
  }  
    
  
  return ModelsPage();
}
