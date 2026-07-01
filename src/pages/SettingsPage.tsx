// @ts-nocheck
import React, { useEffect, useState } from "react";
import { Command } from "cmdk";
import { CheckCircle2, ClipboardCopy, ExternalLink, FolderOpen, RefreshCw, Settings, Trash2 } from "lucide-react";
import { useAppContext } from "../AppContext";

export default function SettingsPage() {
  const {
    CommandCombobox,
    DEFAULT_SEEDANCE_ENDPOINT,
    DEFAULT_SEEDANCE_MODEL,
    DEFAULT_SEEDANCE_RESOLUTION,
    SEEDANCE_MODEL_OPTIONS,
    absoluteMcpRoot,
    checkNetworkProxy,
    chooseUnrealEditorPath,
    codexCallbackInput,
    codexFlow,
    codexOAuth,
    completeCodexOAuthManually,
    copyPixelMcpConfig,
    disabled,
    disconnectCodexOAuth,
    huggingFaceTokenDraft,
    mcpRuntimePaths,
    networkCheck,
    networkProxyDraft,
    openAiBaseUrlDraft,
    openAiKeyDraft,
    openAiMergeEditImagesDraft,
    pixelMcpBackendPath,
    pixelMcpPythonPath,
    pushLog,
    refreshCodexOAuth,
    runtimeSettings,
    saveRuntimeSettings,
    saveUnrealEditorPath,
    seedanceEndpointDraft,
    seedanceKeyDraft,
    seedanceModelDraft,
    seedanceResolutionDraft,
    seedanceResolutionOptions,
    setCodexCallbackInput,
    setHuggingFaceTokenDraft,
    setNetworkProxyDraft,
    setOpenAiBaseUrlDraft,
    setOpenAiKeyDraft,
    setOpenAiMergeEditImagesDraft,
    setSeedanceEndpointDraft,
    setSeedanceKeyDraft,
    setSeedanceResolutionDraft,
    setUnrealMcpUrlDraft,
    setUnrealEditorPathDraft,
    startCodexOAuth,
    unrealEditorPathDraft,
    unrealMcpUrlDraft,
    updateSeedanceModelDraft
  } = useAppContext();

  function SettingsPage() {  
    return (  
      <div className="settings-grid">  
        <section className="detail-card">  
          <div className="section-kicker">运行设置</div>  
          <label className="field">
            <span>OpenAI 密钥</span>
            <input  
              type="password"  
              value={openAiKeyDraft}  
              onChange={(event) => setOpenAiKeyDraft(event.target.value)}  
              placeholder={runtimeSettings?.hasOpenAiApiKey ? "已配置，留空则不覆盖" : "未配置"}  
            />  
          </label>  
          <label className="field">  
            <span>OpenAI Base URL</span>  
            <input  
              value={openAiBaseUrlDraft}  
              onChange={(event) => setOpenAiBaseUrlDraft(event.target.value)}  
              placeholder="https://api.openai.com/v1"  
            />  
          </label>  
          <label className="field">  
            <input
  
              type="checkbox"
  
              checked={openAiMergeEditImagesDraft}
  
              onChange={(event) => setOpenAiMergeEditImagesDraft(event.target.checked)}
  
            />
  
            <span>合并 image 上传编辑</span>
  
            <small>默认开启：多参考图会先合成单张图片，并用单个 image 字段上传；关闭后使用 image[] 多文件上传。</small>
  
          </label>
  
          <label className="field">
  
            <span>Unreal MCP 地址</span>
            <input value={unrealMcpUrlDraft} onChange={(event) => setUnrealMcpUrlDraft(event.target.value)} placeholder="http://127.0.0.1:xxxx" />
            <small>旧版 UE 不需要 MCP；配置 Editor 后可在游戏 UI 导出页自动执行 Python。</small>
          </label>
          <label className="field">  
            <span>Unreal Editor</span>
            <div className="inline-input-action">
              <input
                value={unrealEditorPathDraft}
                onChange={(event) => setUnrealEditorPathDraft(event.target.value)}
                onBlur={() => saveUnrealEditorPath(unrealEditorPathDraft).catch((error) => pushLog(`保存 Unreal Editor 路径失败：${error instanceof Error ? error.message : String(error)}`))}
                placeholder="UnrealEditor-Cmd.exe 或 UnrealEditor.exe"
              />
              <button className="secondary-action icon-only" onClick={chooseUnrealEditorPath} disabled={disabled} type="button" aria-label="选择 Unreal Editor">
                <FolderOpen size={15} />
              </button>
            </div>
            <small>用于自动执行导出的 UE Python；推荐选择 UnrealEditor-Cmd.exe。</small>
          </label>

          <label className="field">
            <span>Hugging Face 令牌 / RMBG 2.0</span>
            <input  
              type="password"  
              value={huggingFaceTokenDraft}  
              onChange={(event) => setHuggingFaceTokenDraft(event.target.value)}  
              placeholder={runtimeSettings?.hasHuggingFaceToken ? "已配置，留空则不覆盖" : "可选"}  
            />  
          </label>  
          <label className="field">  
            <span>Seedance 密钥</span>  
            <input  
              type="password"  
              value={seedanceKeyDraft}  
              onChange={(event) => setSeedanceKeyDraft(event.target.value)}  
              placeholder={runtimeSettings?.hasSeedanceApiKey ? "已配置，留空则不覆盖" : "角色图生视频动作可选"}  
            />  
          </label>  
          <label className="field">  
            <span>Seedance 接口地址</span>  
            <input  
              value={seedanceEndpointDraft}  
              onChange={(event) => setSeedanceEndpointDraft(event.target.value)}  
              placeholder={DEFAULT_SEEDANCE_ENDPOINT}  
            />  
          </label>  
          <div className="field">  
            <span>默认 Seedance 模型</span>  
            <CommandCombobox  
              value={seedanceModelDraft}  
              onValueChange={updateSeedanceModelDraft}  
              options={SEEDANCE_MODEL_OPTIONS}  
              placeholder={DEFAULT_SEEDANCE_MODEL}  
              searchPlaceholder="搜索 Seedance 模型"  
            />  
          </div>  
          <div className="field">  
            <span>默认 Seedance 分辨率</span>  
            <CommandCombobox  
              value={seedanceResolutionDraft}  
              onValueChange={setSeedanceResolutionDraft}  
              options={seedanceResolutionOptions().map((resolution) => ({ value: resolution, label: resolution }))}  
              placeholder={seedanceResolutionOptions()[0] || DEFAULT_SEEDANCE_RESOLUTION}  
              searchPlaceholder="搜索或输入分辨率"  
            />  
          </div>  
          <label className="field">  
            <span>网络代理</span>  
            <input  
              value={networkProxyDraft}  
              onChange={(event) => setNetworkProxyDraft(event.target.value)}  
              placeholder="例如 http://127.0.0.1:7890，留空则不使用"  
            />  
          </label>  
          <p className="help-copy">  
            默认 Seedance 模型会作为新工作区生成参数的默认值；像素工作区仍可为本次生成单独覆盖模型和分辨率。代理只用于后端访问 OpenAI / Hugging Face 等外部服务；localhost 和 127.0.0.1 会直连。  
          </p>  
          {networkCheck && (  
            <div className={`network-check ${networkCheck.reachable ? "ok" : "bad"}`}>  
              <strong>{networkCheck.reachable ? "网络可达" : "网络不可达"}</strong>  
              <small>{networkCheck.detail}</small>  
              <small>代理：{networkCheck.proxy || "未配置"} · 状态：{networkCheck.status || "-"}</small>  
            </div>  
          )}  
          <div className="button-row wrap">  
            <button className="primary-action" onClick={saveRuntimeSettings} disabled={disabled}>  
              <Settings size={15} />  
              应用设置  
            </button>  
            <button className="secondary-action tall" onClick={checkNetworkProxy} disabled={disabled}>  
              <RefreshCw size={15} />  
              测试网络  
            </button>  
          </div>  
        </section>  
    
        <section className="detail-card">  
          <div className="section-header">  
            <div>  
              <div className="section-kicker">Pixel MCP</div>  
              <strong>外部 AI stdio 配置</strong>  
            </div>  
            <ClipboardCopy size={18} />  
          </div>  
          <p className="help-copy">  
            复制后粘贴到支持 MCP 的客户端配置中。配置使用当前运行环境的绝对路径：开发态指向项目目录，打包态指向安装目录 resources；不开放 HTTP 端口。  
          </p>  
          <label className="field">  
            <span>MCP Server</span>  
            <input readOnly value="unreal-image-maker-pixel" />  
          </label>  
          <label className="field">  
            <span>启动模块</span>  
            <input readOnly value={mcpRuntimePaths?.runtimeKind === "sidecar" ? "uim-backend --mcp" : "python -m uim_core.mcp_server"} />
          </label>  
          <div className="runtime-list compact-list">  
            <span>  
              <strong>Python</strong>  
              <small>{absoluteMcpRoot() ? pixelMcpPythonPath() : "等待运行路径加载"}</small>  
            </span>  
            <span>  
              <strong>Backend</strong>  
              <small>{absoluteMcpRoot() ? pixelMcpBackendPath() : "等待运行路径加载"}</small>  
            </span>  
            <span>  
              <strong>状态</strong>  
              <small>{mcpRuntimePaths ? (mcpRuntimePaths.available ? "可用" : "未检测到完整运行时") : "浏览器预览会使用开发目录回退"}</small>  
            </span>  
          </div>  
          <button className="secondary-action tall" onClick={copyPixelMcpConfig} disabled={disabled || !absoluteMcpRoot()} type="button">  
            <ClipboardCopy size={15} />  
            复制 MCP 配置  
          </button>  
        </section>  
    
        <section className="detail-card">  
          <div className="section-header">  
            <div>  
              <div className="section-kicker">ChatGPT 订阅绑定</div>  
              <strong>{codexOAuth?.configured ? "已绑定 ChatGPT 订阅" : "未绑定"}</strong>  
            </div>  
            <span className={`pill ${codexOAuth?.configured ? "installed" : "not_installed"}`}>{codexOAuth?.configured ? "已就绪" : "待绑定"}</span>  
          </div>  
          <p className="help-copy">  
            点击开始绑定后会打开浏览器授权。默认使用 localhost:1455 自动回调；如果该端口被占用，可以把浏览器最终跳转的完整网址粘贴到下面完成绑定。  
          </p>  
          {codexFlow && (  
            <div className="oauth-fallback">  
              <p className="oauth-pending">{codexFlow.message || "正在等待浏览器授权完成..."}</p>  
              <label className="field">  
                <span>回调网址兜底输入</span>  
                <textarea  
                  className="short-textarea"  
                  value={codexCallbackInput}  
                  onChange={(event) => setCodexCallbackInput(event.target.value)}  
                  placeholder="http://localhost:1455/auth/callback?code=...&state=..."  
                />  
              </label>  
              <button className="secondary-action tall" onClick={completeCodexOAuthManually} disabled={disabled || !codexCallbackInput.trim()}>  
                <CheckCircle2 size={15} />  
                使用回调网址完成绑定  
              </button>  
            </div>  
          )}  
          <div className="runtime-list compact-list">  
            <span>  
              <strong>账号</strong>  
              <small>{codexOAuth?.email || codexOAuth?.accountId || "-"}</small>  
            </span>  
            <span>  
              <strong>过期时间</strong>  
              <small>{codexOAuth?.expiresAt || "-"}</small>  
            </span>  
            <span>  
              <strong>凭据文件</strong>  
              <small>{codexOAuth?.storePath || "-"}</small>  
            </span>  
          </div>  
          <div className="button-row wrap">  
            <button className="secondary-action tall" onClick={startCodexOAuth} disabled={disabled || Boolean(codexFlow)}>  
              <ExternalLink size={15} />  
              {codexFlow ? "等待授权" : "开始绑定"}  
            </button>  
            <button className="secondary-action tall" onClick={refreshCodexOAuth} disabled={disabled || !codexOAuth?.hasRefreshToken}>  
              <RefreshCw size={15} />  
              刷新凭据  
            </button>  
            <button className="secondary-action tall danger-action" onClick={disconnectCodexOAuth} disabled={disabled || !codexOAuth?.configured}>  
              <Trash2 size={15} />  
              断开  
            </button>  
          </div>  
        </section>  
      </div>  
    );  
  }  
    
  
  return SettingsPage();
}
