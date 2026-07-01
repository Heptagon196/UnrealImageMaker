// @ts-nocheck
import React, { useEffect, useState } from "react";
import { Command } from "cmdk";
import { Box, ClipboardCopy, Download, Eye, FileImage, FileJson, FolderOpen, RefreshCw, Sparkles, Trash2, Wand2 } from "lucide-react";
import { useAppContext } from "../AppContext";

export default function GameUiPage() {
  const {
    AssetPreview,
    CommandCombobox,
    DEFAULT_GAME_UI_TEXTURE_BATCH_COUNT,
    DEFAULT_GAME_UI_TEXTURE_STATE_COUNT,
    DEFAULT_GAME_UI_TEXTURE_TOKEN_COUNT,
    EditableCommandCombobox,
    GAME_UI_CHROMA_PRESETS,
    WorkerAlert,
    bakeGameUiHtml,
    browserVersionDate,
    contentPath,
    copyGameUiDslPrompt,
    deleteCurrentUiConcept,
    deleteGameUiHtml,
    deleteGameUiStructure,
    disabled,
    exportGameUiUmg,
    chooseUnrealProjectPath,
    gameUiAdvancedTokensOpen,
    gameUiChromaPreset,
    gameUiConceptVersionChoices,
    gameUiCustomChromaHex,
    gameUiHtmlDraft,
    gameUiHtmlPath,
    gameUiHtmlPrototypes,
    gameUiKitFilesJson,
    gameUiKitName,
    gameUiKitSelectionValue,
    gameUiScreenName,
    gameUiSelectedChromaHex,
    gameUiSelectedChromaRgb,
    gameUiSelectedKitPath,
    gameUiStructurePath,
    gameUiStructures,
    gameUiTab,
    gameUiTextureDebugArtifacts,
    gameUiTextureKits,
    gameUiTextureMaxConcurrency,
    gameUiWidgetTokensJson,
    generateGameUiTextureKit,
    generateUiConcept,
    imageProvider,
    importUiConcept,
    openGameUiSkinPreview,
    pushLog,
    refreshGameUiWorkspace,
    registerGameUiTextureKit,
    requestClearGameUiTextureKit,
    saveGameUiUnrealProjectPath,
    saveGameUiHtml,
    selectGameUiConceptVersion,
    selectGameUiHtmlPrototype,
    selectGameUiKitName,
    selectedGameUiTextureKit,
    setContentPath,
    setGameUiAdvancedTokensOpen,
    setGameUiChromaPreset,
    setGameUiCustomChromaHex,
    setGameUiHtmlDraft,
    setGameUiHtmlPath,
    setGameUiKitFilesJson,
    setGameUiSelectedKitPath,
    setGameUiStructurePath,
    setGameUiTab,
    setGameUiTextureDebugArtifacts,
    setGameUiTextureMaxConcurrency,
    setGameUiWidgetTokensJson,
    setImageProvider,
    setUiAssetName,
    setUiGameDescription,
    setUiLayout,
    uiAssetName,
    uiConceptSlot,
    uiGameDescription,
    uiLayout,
    unrealProjectPathDraft,
    setUnrealProjectPathDraft,
    versionRoleLabel
  } = useAppContext();

  function GameUiPage() {
  
    const selectedStructure = gameUiStructures.find((item) => item.path === gameUiStructurePath);
  
    const selectedKit = selectedGameUiTextureKit();
  
    const htmlPrototypeOptions = gameUiHtmlPrototypes.map((item) => ({
  
      value: item.screenName,
  
      label: item.screenName,
  
      description: item.path
  
    }));
  
    const structureOptions = gameUiStructures.map((item) => ({
  
      value: item.path,
  
      label: item.screenName,
  
      description: item.referenceResolution?.width ? `${item.referenceResolution.width}x${item.referenceResolution.height || 1080} · ${item.path}` : item.path
  
    }));
  
    const kitOptions = gameUiTextureKits.map((kit) => ({
  
      value: gameUiKitSelectionValue(kit),
  
      label: kit.kitName,
  
      description: kit.inProgress
  
        ? `进行中 · ${kit.stateSheetCount || 0} 状态图 · ${kit.generatedStateCount || 0} 状态 PNG`
  
        : `${(kit.validation?.warnings?.length || 0) > 0 ? `${kit.validation?.warnings?.length} 个警告` : kit.validation?.ok === false ? "缺项" : "可用"} · ${kit.tokens.length} tokens`
  
    }));
  
    const kitNameOptions = gameUiTextureKits.map((kit) => ({
  
      value: kit.kitName,
  
      label: kit.kitName,
  
      description: kit.inProgress
  
        ? `进行中 · ${kit.stateSheetCount || 0} 状态图 · ${kit.generatedStateCount || 0} 状态 PNG`
  
        : kit.path
  
    }));
  
    const conceptChoices = gameUiConceptVersionChoices();
  
    const selectedConcept = uiConceptSlot();
  
    const conceptOptions = conceptChoices.map(({ asset, version }) => ({
  
      value: version.id,
  
      label: `${asset.name} · ${browserVersionDate(version) || versionRoleLabel(version.role)}`,
  
      description: version.path
  
    }));
  
    const selectedChromaHex = gameUiSelectedChromaHex();
  
    const selectedChromaRgb = gameUiSelectedChromaRgb();
  
    return (
  
      <div className="module-page">
  
        {AssetPreview()}
  
        <section className="form-panel">
  
          {WorkerAlert()}
  
          <div className="panel-heading">
  
            <Box size={18} />
  
            <div>
  
              <h3>游戏 UI 结构 / 贴图流水线</h3>
  
              <p>外部 AI 通过 MCP 生成 HTML；这里负责烘焙结构、管理贴图组，并导出 UE Python 脚本。</p>
            </div>
  
          </div>
  
          <div className="module-switcher" role="tablist" aria-label="游戏 UI 工作流">
  
            <button className={gameUiTab === "structure" ? "active" : ""} onClick={() => setGameUiTab("structure")} type="button">
  
              UI 结构
  
            </button>
  
            <button className={gameUiTab === "texture_kit" ? "active" : ""} onClick={() => setGameUiTab("texture_kit")} type="button">
  
              UI 贴图组
  
            </button>
  
          </div>
  
          {gameUiTab === "structure" && (
  
            <>
  
              <section className="subpanel">
  
                <div className="section-header">
  
                  <div>
  
                    <div className="section-kicker">MCP / HTML</div>
  
                    <strong>HTML 原型</strong>
  
                  </div>
  
                  <ClipboardCopy size={18} />
  
                </div>
  
                <p className="help-copy">
  
                  把 DSL 提示词交给外部 AI；AI 应通过 MCP 写入项目目录。这里也允许粘贴 HTML 保存，便于人工修正。
  
                </p>
  
                <div className="two-col">
  
                  <label className="field">
  
                    <span>HTML 原型</span>
  
                    <EditableCommandCombobox
  
                      value={gameUiScreenName}
  
                      onValueChange={(value) => {
  
                        selectGameUiHtmlPrototype(value).catch((error) => pushLog(error.message));
  
                      }}
  
                      options={htmlPrototypeOptions}
  
                      placeholder="选择或输入新屏幕名"
  
                      emptyLabel="没有 HTML 原型"
  
                    />
  
                  </label>
  
                  <label className="field">
  
                    <span>HTML 路径</span>
  
                    <input value={gameUiHtmlPath} onChange={(event) => setGameUiHtmlPath(event.target.value)} placeholder="保存后自动写入 ui/html/*.html" />
  
                  </label>
  
                  <label className="field span-2">
  
                    <span>HTML 内容</span>
  
                    <textarea
  
                      className="short-textarea"
  
                      value={gameUiHtmlDraft}
  
                      onChange={(event) => setGameUiHtmlDraft(event.target.value)}
  
                      placeholder="可选：粘贴外部 AI 生成的 HTML，然后点击保存。MCP 写入时可以留空。"
  
                    />
  
                  </label>
  
                </div>
  
                <div className="button-row wrap">
  
                  <button className="secondary-action tall" onClick={copyGameUiDslPrompt} disabled={disabled} type="button">
  
                    <ClipboardCopy size={15} />
  
                    复制 UI DSL 提示词
  
                  </button>
  
                  <button className="secondary-action tall" onClick={saveGameUiHtml} disabled={disabled || !gameUiHtmlDraft.trim()} type="button">
  
                    <FileJson size={15} />
  
                    保存 HTML
  
                  </button>
  
                  <button className="secondary-action tall danger-action" onClick={deleteGameUiHtml} disabled={disabled || !gameUiHtmlPath} type="button">
  
                    <Trash2 size={15} />
  
                    删除 HTML
  
                  </button>
  
                  <button className="primary-action" onClick={bakeGameUiHtml} disabled={disabled || !gameUiScreenName.trim()} type="button">
  
                    <Wand2 size={15} />
  
                    烘焙结构 JSON
  
                  </button>
  
                </div>
  
              </section>
  
  
  
              <section className="subpanel">
  
                <div className="section-header">
  
                  <div>
  
                    <div className="section-kicker">结构 / UMG</div>
  
                    <strong>结构化 UI 描述</strong>
  
                  </div>
  
                  <FileJson size={18} />
  
                </div>
  
                <div className="two-col">
  
                  <label className="field">
  
                    <span>结构 JSON</span>
  
                    <CommandCombobox
  
                      value={gameUiStructurePath}
  
                      onValueChange={setGameUiStructurePath}
  
                      options={structureOptions}
  
                      placeholder="选择结构 JSON"
  
                      searchPlaceholder="搜索结构 JSON"
  
                      emptyLabel="没有结构 JSON"
  
                      allowCustom={false}
  
                    />
  
                  </label>
  
                  <label className="field">
  
                    <span>贴图组</span>
  
                    <CommandCombobox
  
                      value={gameUiSelectedKitPath}
  
                      onValueChange={setGameUiSelectedKitPath}
  
                      options={kitOptions}
  
                      placeholder="选择 UI 贴图组"
  
                      searchPlaceholder="搜索 UI 贴图组"
  
                      emptyLabel="没有 UI 贴图组"
  
                      allowCustom={false}
  
                    />
  
                  </label>
  

                  <label className="field span-2">

                    <span>Unreal 项目 (.uproject)</span>

                    <div className="inline-input-action">

                      <input
                        value={unrealProjectPathDraft}
                        onChange={(event) => setUnrealProjectPathDraft(event.target.value)}
                        onBlur={() => saveGameUiUnrealProjectPath(unrealProjectPathDraft).catch((error) => pushLog(error.message))}
                        placeholder="选择当前项目的 .uproject 文件"
                      />

                      <button className="secondary-action icon-only" onClick={chooseUnrealProjectPath} disabled={disabled} type="button" aria-label="选择 Unreal 项目">

                        <FolderOpen size={15} />

                      </button>

                    </div>

                    <small className="field-hint">随当前 .uim 项目保存；导出时用于自动执行 UE Python。</small>

                  </label>
                </div>
  
                <div className="runtime-list compact-list">
  
                  <span>
  
                    <strong>当前结构</strong>
  
                    <small>{selectedStructure ? `${selectedStructure.screenName} · ${selectedStructure.referenceResolution?.width || 1920}x${selectedStructure.referenceResolution?.height || 1080}` : "未选择"}</small>
  
                  </span>
  
                  <span>
  
                    <strong>当前贴图组</strong>
  
                    <small>{selectedKit ? `${selectedKit.kitName} · ${selectedKit.tokens.length} tokens` : "未选择"}</small>
  
                  </span>
  
                  <span>
  
                    <strong>UE 内容路径</strong>
  
                    <small>{contentPath}/UI</small>
  
                  </span>
  
                </div>
  
                <div className="button-row wrap">
  
                  <button className="secondary-action tall" onClick={refreshGameUiWorkspace} disabled={disabled} type="button">
  
                    <RefreshCw size={15} />
  
                    刷新列表
  
                  </button>
  
                  <button className="secondary-action tall" onClick={openGameUiSkinPreview} disabled={disabled || !gameUiStructurePath || !selectedKit?.path} type="button">
  
                    <Eye size={15} />
  
                    预览应用效果
  
                  </button>
  
                  <button className="secondary-action tall danger-action" onClick={deleteGameUiStructure} disabled={disabled || !gameUiStructurePath} type="button">
  
                    <Trash2 size={15} />
  
                    删除结构 JSON
  
                  </button>
  
                  <button className="primary-action" onClick={exportGameUiUmg} disabled={disabled || !gameUiStructurePath || !selectedKit?.path} type="button">
  
                    <Download size={15} />
  
                    导出 UE Python
                  </button>
  
                </div>
  
              </section>
  
            </>
  
          )}
  
          {gameUiTab === "texture_kit" && (
  
            <>
  
              <section className="subpanel">
  
                <div className="section-header">
  
                  <div>
  
                    <div className="section-kicker">概念参考</div>
  
                    <strong>UI 概念图</strong>
  
                  </div>
  
                  <Sparkles size={18} />
  
                </div>
  
                <div className="two-col">
  
                  <label className="field">
  
                    <span>UI 资产名</span>
  
                    <input value={uiAssetName} onChange={(event) => setUiAssetName(event.target.value)} />
  
                  </label>
  
                  <label className="field">
  
                    <span>生成方式</span>
  
                    <select value={imageProvider} onChange={(event) => setImageProvider(event.target.value as ImageProvider)}>
  
                      <option value="openai_api">OpenAI 密钥（gpt-image-2）</option>
  
                      <option value="codex_oauth">ChatGPT 订阅账号</option>
  
                    </select>
  
                  </label>
  
                  <label className="field span-2">
  
                    <span>UI 概念图</span>
  
                    <CommandCombobox
  
                      value={selectedConcept?.version.id || ""}
  
                      onValueChange={(value) => {
  
                        selectGameUiConceptVersion(value).catch((error) => pushLog(error.message));
  
                      }}
  
                      options={conceptOptions}
  
                      placeholder="选择 UI 概念图"
  
                      searchPlaceholder="搜索 UI 概念图"
  
                      emptyLabel="当前 UI 资产没有概念图"
  
                      allowCustom={false}
  
                    />
  
                    <small className="field-hint">{selectedConcept?.version.path || "生成或导入概念图后可在这里切换版本。"}</small>
  
                  </label>
  
                  <label className="field span-2">
  
                    <span>游戏类型与风格</span>
  
                    <textarea className="short-textarea" value={uiGameDescription} onChange={(event) => setUiGameDescription(event.target.value)} />
  
                  </label>
  
                  <label className="field span-2">
  
                    <span>界面布局</span>
  
                    <textarea className="short-textarea" value={uiLayout} onChange={(event) => setUiLayout(event.target.value)} />
  
                  </label>
  
                </div>
  
                <div className="button-row wrap">
  
                  <button className="run-button" onClick={generateUiConcept} disabled={disabled}>
  
                    <Wand2 size={17} />
  
                    生成 UI 概念图
  
                  </button>
  
                  <button className="secondary-action tall" onClick={importUiConcept} disabled={disabled} type="button">
  
                    <FileImage size={15} />
  
                    导入 UI 概念图
  
                  </button>
  
                  <button className="secondary-action tall danger-action" onClick={deleteCurrentUiConcept} disabled={disabled || !selectedConcept} type="button">
  
                    <Trash2 size={15} />
  
                    删除概念图
  
                  </button>
  
                </div>
  
              </section>
  
  
  
              <section className="subpanel">
  
                <div className="section-header">
  
                  <div>
  
                    <div className="section-kicker">贴图组</div>
  
                    <strong>通用控件状态贴图</strong>
  
                  </div>
  
                  <Box size={18} />
  
                </div>
  
                <div className="runtime-list compact-list">
  
                  <span>
  
                    <strong>当前概念图</strong>
  
                    <small>{selectedConcept?.version.path || "未选择"}</small>
  
                  </span>
  
                  <span>
  
                    <strong>引用模式</strong>
  
                    <small>{selectedConcept?.mode === "fixed" ? "固定版本" : "自动最新"}</small>
  
                  </span>
  
                </div>
  
                <div className="asset-kind-summary">
  
                  <div>
  
                    <strong>{DEFAULT_GAME_UI_TEXTURE_TOKEN_COUNT}</strong>
  
                    <span>默认 token</span>
  
                  </div>
  
                  <div>
  
                    <strong>{DEFAULT_GAME_UI_TEXTURE_STATE_COUNT}</strong>
  
                    <span>状态贴图</span>
  
                  </div>
  
                  <div>
  
                    <strong>{DEFAULT_GAME_UI_TEXTURE_BATCH_COUNT}</strong>
  
                    <span>本地预览页</span>
  
                  </div>
  
                </div>
  
                <p className="field-hint">
  
                  默认生成 panel、image、text、button、input、scroll、checkbox、slider、dropdown 的通用 UE 控件贴图；后端会按控件 token 合并生成同一控件的所有状态，先用 rembg/透明度定位状态区域，再拆成状态 PNG 并本地打包预览页，避免整页 atlas 错位裁切。
  
                </p>
  
                <div className="two-col">
  
                  <label className="field">
  
                    <span>贴图组名</span>
  
                    <EditableCommandCombobox
  
                      value={gameUiKitName}
  
                      onValueChange={selectGameUiKitName}
  
                      options={kitNameOptions}
  
                      placeholder="选择或输入贴图组名"
  
                      emptyLabel="没有贴图组"
  
                    />
  
                  </label>
  
                  <label className="field">
  
                    <span>UE 内容路径</span>
  
                    <input value={contentPath} onChange={(event) => setContentPath(event.target.value)} />
  
                  </label>
  
                  <label className="field">
  
                    <span>当前贴图组</span>
  
                    <CommandCombobox
  
                      value={gameUiSelectedKitPath}
  
                      onValueChange={setGameUiSelectedKitPath}
  
                      options={kitOptions}
  
                      placeholder="选择要预览 / 清空的贴图组"
  
                      searchPlaceholder="搜索当前贴图组"
  
                      emptyLabel="没有贴图组"
  
                      allowCustom={false}
  
                    />
  
                    <small className="field-hint">清空会删除该贴图组配置和项目 ui 目录下的生成文件。</small>
  
                  </label>
  
                  <label className="field">
  
                    <span>生成并发数</span>
  
                    <input
  
                      type="number"
  
                      min={1}
  
                      max={4}
  
                      step={1}
  
                      value={gameUiTextureMaxConcurrency}
  
                      onChange={(event) => setGameUiTextureMaxConcurrency(Math.max(1, Math.min(4, Number(event.currentTarget.value) || 1)))}
  
                    />
  
                    <small className="field-hint">按控件组并发生成；同一控件的不同状态仍合在一张状态图里。</small>
  
                  </label>
  
                  <label className="field">
  
                    <span>Key Color</span>
  
                    <select value={gameUiChromaPreset} onChange={(event) => setGameUiChromaPreset(event.currentTarget.value)}>
  
                      {GAME_UI_CHROMA_PRESETS.map((option) => (
  
                        <option key={option.value} value={option.value}>
  
                          {option.label}
  
                        </option>
  
                      ))}
  
                    </select>
  
                    <small className="field-hint">
  
                      背景抠图色会写入 prompt、guide、抠图与验收；当前 {selectedChromaRgb ? selectedChromaHex : "格式无效"}。
  
                    </small>
  
                  </label>
  
                  {gameUiChromaPreset === "custom" && (
  
                    <label className="field">
  
                      <span>自定义 HEX</span>
  
                      <div className="inline-field-row">
  
                        <input
  
                          aria-label="自定义 Key Color"
  
                          type="color"
  
                          value={/^#[0-9A-F]{6}$/i.test(gameUiCustomChromaHex) ? gameUiCustomChromaHex : "#FFFFFF"}
  
                          onChange={(event) => setGameUiCustomChromaHex(event.currentTarget.value.toUpperCase())}
  
                        />
  
                        <input value={gameUiCustomChromaHex} onChange={(event) => setGameUiCustomChromaHex(event.currentTarget.value.toUpperCase())} placeholder="#RRGGBB" />
  
                      </div>
  
                      <small className="field-hint">
  
                        {selectedChromaHex === "#FFFFFF" ? "白色可能误删高光或浅色描边；仅在 UI 主体完全避开白色时使用。" : "自定义颜色不得出现在控件主体、高光、阴影和抗锯齿边缘。"}
  
                      </small>
  
                    </label>
  
                  )}
  
                  <label className="field checkbox-field">
  
                    <span>调试输出</span>
  
                    <label>
  
                      <input type="checkbox" checked={gameUiTextureDebugArtifacts} onChange={(event) => setGameUiTextureDebugArtifacts(event.currentTarget.checked)} />
  
                      保存生成/Mask 调试图
  
                    </label>
  
                  </label>
  
                  <div className="field span-2">
  
                    <span>高级额外 tokens JSON</span>
  
                    <button className="secondary-action compact" onClick={() => setGameUiAdvancedTokensOpen((current) => !current)} type="button">
  
                      {gameUiAdvancedTokensOpen ? "收起高级 JSON" : "展开高级 JSON"}
  
                    </button>
  
                    {gameUiAdvancedTokensOpen && (
  
                      <textarea className="short-textarea" value={gameUiWidgetTokensJson} onChange={(event) => setGameUiWidgetTokensJson(event.target.value)} />
  
                    )}
  
                    <small className="field-hint">留空数组即可生成通用全套；这里仅用于追加项目专属 token。</small>
  
                  </div>
  
                  <label className="field span-2">
  
                    <span>登记已有贴图 JSON</span>
  
                    <textarea className="short-textarea" value={gameUiKitFilesJson} onChange={(event) => setGameUiKitFilesJson(event.target.value)} />
  
                  </label>
  
                </div>
  
                <div className="button-row wrap">
  
                  <button className="secondary-action tall" onClick={registerGameUiTextureKit} disabled={disabled || !gameUiKitName.trim()} type="button">
  
                    <FileJson size={15} />
  
                    登记已有贴图组
  
                  </button>
  
                  <button className="primary-action" onClick={generateGameUiTextureKit} disabled={disabled || !gameUiKitName.trim()} type="button">
  
                    <Box size={15} />
  
                    生成贴图组
  
                  </button>
  
                  <button className="secondary-action tall danger-action" onClick={requestClearGameUiTextureKit} disabled={disabled || !gameUiSelectedKitPath} type="button">
  
                    <Trash2 size={15} />
  
                    清空贴图
  
                  </button>
  
                </div>
  
              </section>
  
            </>
  
          )}
  
        </section>
  
      </div>
  
    );
  
  }
  
  
  
  
  return GameUiPage();
}
