// @ts-nocheck
import React, { useEffect, useState } from "react";
import { Command } from "cmdk";
import { Check, CheckCircle2, ChevronDown, Eraser, FileImage, FileJson, Layers, Play, RefreshCw, Scissors, SkipBack, SkipForward, Sparkles, Trash2, Wand2 } from "lucide-react";
import { useAppContext } from "../AppContext";

export default function PixelPage() {
  const {
    AssetPreview,
    CommandCombobox,
    PIXEL_MASK_MODE_OPTIONS,
    PIXEL_RESTORE_MODE_OPTIONS,
    SEEDANCE_MODEL_OPTIONS,
    SlotPicker,
    WorkerAlert,
    anchorConceptReferencePath,
    anchorOutputOptions,
    anchorPathForDirection,
    applyPixelKindSelection,
    assetIdFromName,
    assetName,
    browserVersionDate,
    composeTilemapFromSeed,
    contentPath,
    createTilemapManifest,
    currentCutoutRole,
    currentPixelActionId,
    currentPixelActionLabel,
    currentSeedanceModel,
    currentSeedanceResolution,
    currentSheetDirection,
    currentSheetRole,
    currentVideoDirection,
    currentVideoSourcePath,
    cutoutSourceSlot,
    defaultSeedanceModel,
    defaultSeedanceResolution,
    disabled,
    generatePixelAnchor,
    generatePixelConcept,
    generatePixelSheet,
    generatePixelSheetFromVideo,
    generateSeedanceVideo,
    generateTilemapSeedConcept,
    handlePixelMatrixCellClick,
    imageProvider,
    importPixelSheet,
    knownActionLabel,
    normalizePixelSheet,
    normalizeSourceSlot,
    openVideoFramePicker,
    pixelAction,
    pixelActionDescription,
    pixelActionMenuOpen,
    pixelActionOptions,
    pixelActionQuery,
    pixelAnchorOutputSize,
    pixelAnchorUseConcept,
    pixelAttackName,
    pixelBatchQueue,
    pixelCellSize,
    pixelColumns,
    pixelConceptPath,
    pixelCustomActionName,
    pixelCutoutPath,
    pixelDebugArtifacts,
    pixelDecontaminateEdges,
    pixelDirection,
    pixelDirectionLabel,
    pixelDynamicEffect,
    pixelEffectColor,
    pixelI2vActionDescription,
    pixelKind,
    pixelKindCopy,
    pixelKindLabel,
    pixelMaskMode,
    pixelMatrixActionLabel,
    pixelMatrixActions,
    pixelMatrixCellKey,
    pixelMatrixCellState,
    pixelMatrixDirections,
    pixelMatrixSelection,
    pixelMirrorEastFromWest,
    pixelPreviewOpen,
    pixelProjectileEffect,
    pixelRestoreMode,
    pixelRows,
    pixelSeedanceSeconds,
    pixelSheetMode,
    pixelSheetPath,
    pixelStage,
    pixelSubject,
    pixelTileSetPath,
    pixelTileSize,
    pixelTilemapOuterMaterial,
    pixelTilemapOuterPath,
    pixelTilemapPrimaryMaterial,
    pixelTilemapPrimaryPath,
    pixelTilemapSeedPath,
    pixelTilemapStandard,
    pixelTilemapSubject,
    pixelVideoPath,
    previewUrlForPath,
    projectRoot,
    rembgModel,
    removePixelSheetBackground,
    runPixelBatch,
    seedanceResolutionOptions,
    setActivePreviewLabel,
    setActivePreviewPath,
    setActivePreviewVersionId,
    setAssetName,
    setContentPath,
    setImageProvider,
    setPixelActionDescription,
    setPixelActionFromId,
    setPixelActionMenuOpen,
    setPixelActionQuery,
    setPixelAnchorUseConcept,
    setPixelAttackName,
    setPixelColumns,
    setPixelConceptPath,
    setPixelCustomActionName,
    setPixelDebugArtifacts,
    setPixelDecontaminateEdges,
    setPixelDirection,
    setPixelDynamicEffect,
    setPixelEffectColor,
    setPixelI2vActionDescription,
    setPixelMaskMode,
    setPixelMatrixSelection,
    setPixelMirrorEastFromWest,
    setPixelPreviewOpen,
    setPixelProjectileEffect,
    setPixelRestoreMode,
    setPixelRows,
    setPixelSeedanceResolution,
    setPixelSeedanceSeconds,
    setPixelSheetMode,
    setPixelStage,
    setPixelSubject,
    setPixelTileSetPath,
    setPixelTileSize,
    setPixelTilemapOuterMaterial,
    setPixelTilemapOuterPath,
    setPixelTilemapPrimaryMaterial,
    setPixelTilemapPrimaryPath,
    setPixelTilemapSeedPath,
    setPixelTilemapStandard,
    setPixelTilemapSubject,
    setPixelVideoPath,
    setRembgModel,
    setTilemapImportOpen,
    tilemapImportOpen,
    tilemapStandardOption,
    togglePixelMatrixCell,
    updatePixelAnchorOutputSize,
    updatePixelCellSize,
    updatePixelSeedanceModel,
    useDismissableCombobox,
    videoFrameSelections,
    videoSheetLayoutForFrameCount,
    videoSourceSlot
  } = useAppContext();

  function PixelSpritesheetPage() {  
    const isCharacter = pixelKind === "character";  
    const isTilemap = pixelKind === "tilemap";  
    const kindCopy = pixelKindCopy(pixelKind);  
    const activePixelStage = isTilemap ? (["tilemap_seed", "tilemap_tileset"].includes(pixelStage) ? pixelStage : "tilemap_seed") : pixelStage;
    const tileSizeOptions = [16, 32, 64, 128, 256];
    const TileSizeSelect = ({ label = "单个 tile 边长", hint = "" }: { label?: string; hint?: string }) => (
      <label className="field">
        <span>{label}</span>
        <select value={pixelTileSize} onChange={(event) => setPixelTileSize(Number(event.target.value))}>
          {tileSizeOptions.map((size) => (
            <option key={size} value={size}>{size}px</option>
          ))}
        </select>
        {hint && <small>{hint}</small>}
      </label>
    );
    const seedanceAnchorCandidate = anchorPathForDirection(currentVideoDirection());
    const seedanceDefaultModel = defaultSeedanceModel();  
    const seedanceDefaultResolution = defaultSeedanceResolution();  
    const activeSeedanceModel = currentSeedanceModel();  
    const activeSeedanceResolution = currentSeedanceResolution();  
    const workspaceSeedanceModelOptions = [  
      ...(SEEDANCE_MODEL_OPTIONS.some((option) => option.value === seedanceDefaultModel)  
        ? []  
        : [{ value: seedanceDefaultModel, label: `${seedanceDefaultModel}（默认）`, description: "设置页默认" }]),  
      ...SEEDANCE_MODEL_OPTIONS.map((option) =>  
        option.value === seedanceDefaultModel  
          ? { ...option, label: `${option.label}（默认）`, description: option.description ? `设置页默认 · ${option.description}` : "设置页默认" }  
          : option  
      )  
    ];  
    const workspaceSeedanceResolutionOptions = seedanceResolutionOptions(activeSeedanceModel, seedanceDefaultResolution).map((resolution) => ({  
      value: resolution,  
      label: resolution === seedanceDefaultResolution ? `${resolution}（默认）` : resolution,  
      description: resolution === seedanceDefaultResolution ? "设置页默认" : undefined  
    }));  
    const pixelWorkflowSteps: Array<{ id: PixelStage; label: string; detail: string }> = isTilemap  
      ? [
          { id: "tilemap_seed", label: "材质样例", detail: "生成 outer / primary 格子" },
          { id: "tilemap_tileset", label: "Dual-Grid 16", detail: "生成最终地形集" }
        ]
      : isCharacter  
        ? [  
            { id: "concept", label: "角色概念图", detail: "确定轮廓、配色、气质" },  
            { id: "south_anchor", label: "正面基准图", detail: "文本 + 像素网格" },  
            { id: "neutral_anchor", label: "中性姿态修正", detail: "移除火球、光效等动态元素" },  
            { id: "direction_anchor", label: "方向基准图", detail: "生成左侧/背面/右侧" },  
            { id: "sheet", label: "动作序列图", detail: "直接生成或图生视频" },  
            { id: "cutout", label: "背景透明化", detail: "Hybrid Mask 去背景" },  
            { id: "normalize", label: "归一化", detail: "定脚底、裁切、重打包" }  
          ]  
        : [  
            { id: "concept", label: kindCopy.conceptTitle, detail: kindCopy.conceptStepDetail },  
            { id: "south_anchor", label: kindCopy.anchorTitle, detail: kindCopy.anchorStepDetail },  
            { id: "sheet", label: kindCopy.sheetTitle, detail: kindCopy.sheetStepDetail },  
            { id: "cutout", label: "背景透明化", detail: "Hybrid Mask 去背景" },  
            { id: "normalize", label: "归一化", detail: "裁切、重打包" }  
          ];  
    
    function switchPixelKind(kind: PixelKind) {  
      applyPixelKindSelection(kind, { resetStage: true });  
    }  
    
    function StageNav() {  
      return (  
        <nav className="workflow-steps" aria-label="像素生产阶段">  
          {pixelWorkflowSteps.map((step, index) => (  
            <button  
              className={activePixelStage === step.id ? "active" : ""}  
              key={step.id}  
              onClick={() => setPixelStage(step.id)}  
              type="button"  
            >  
              <span className="step-index">{index + 1}</span>  
              <span>  
                <strong>{step.label}</strong>  
                <small>{step.detail}</small>  
              </span>  
            </button>  
          ))}  
        </nav>  
      );  
    }  
    
    function PixelActionCommandField({ className = "" }: { className?: string }) {  
      const queryValue = pixelActionQuery.trim();  
      const canUseCustom = queryValue && !pixelActionOptions.some((option) => option.value.toLowerCase() === assetIdFromName(queryValue).toLowerCase());  
      const selected = pixelActionOptions.find((option) => option.value === currentPixelActionId());  
      const actionComboboxDismiss = useDismissableCombobox<HTMLDivElement>(setPixelActionMenuOpen);  
      const chooseAction = (value: string) => {  
        setPixelActionFromId(value);  
        setPixelActionQuery("");  
        setPixelActionMenuOpen(false);  
      };  
      return (  
        <div className={`field ${className}`.trim()}>  
          <span>动作</span>  
          <div  
            className="cmdk-combobox action-combobox"  
            onBlur={actionComboboxDismiss.handleBlur}  
            onKeyDown={actionComboboxDismiss.handleKeyDown}  
            ref={actionComboboxDismiss.rootRef}  
          >  
            <button className="cmdk-combobox-trigger" onClick={() => setPixelActionMenuOpen((current) => !current)} type="button">  
              <span>  
                <strong>{selected?.label || currentPixelActionLabel()}</strong>  
                <small>{selected?.description || currentPixelActionId()}</small>  
              </span>  
              <ChevronDown size={16} />  
            </button>  
            {pixelActionMenuOpen && (  
              <Command className="cmdk-combobox-menu" shouldFilter>  
                <Command.Input autoFocus value={pixelActionQuery} onValueChange={setPixelActionQuery} placeholder="搜索动作，或输入新动作名" />  
                <Command.List>  
                  <Command.Empty>没有匹配动作</Command.Empty>  
                  <Command.Group>  
                    {pixelActionOptions.map((option) => (  
                      <Command.Item key={option.value} value={`${option.label} ${option.value} ${option.description || ""}`} onSelect={() => chooseAction(option.value)}>  
                        <span>  
                          <strong>{option.label}</strong>  
                          <small>{option.value}{option.description ? ` · ${option.description}` : ""}</small>  
                        </span>  
                        {option.value === currentPixelActionId() && <Check size={15} />}  
                      </Command.Item>  
                    ))}  
                    {canUseCustom && (  
                      <Command.Item value={queryValue} onSelect={() => chooseAction(queryValue)}>  
                        <span>  
                          <strong>使用“{queryValue}”</strong>  
                          <small>新动作</small>  
                        </span>  
                        <CheckCircle2 size={15} />  
                      </Command.Item>  
                    )}  
                  </Command.Group>  
                </Command.List>  
              </Command>  
            )}  
          </div>  
          <small className="field-hint">已有动作来自当前资产；也可以直接输入新动作名。</small>  
        </div>  
      );  
    }  
    
    function PixelGlobals() {  
      return (  
        <section className="subpanel no-border">  
          <div className="module-switcher" role="tablist" aria-label="像素工作流">  
            {(["character", "weapon", "decoration", "tilemap"] as PixelKind[]).map((kind) => (  
              <button className={pixelKind === kind ? "active" : ""} key={kind} onClick={() => switchPixelKind(kind)} type="button">  
                {pixelKindLabel(kind)}  
              </button>  
            ))}  
          </div>  
          <div className="two-col">  
            <label className="field">  
              <span>资产名</span>  
              <input value={assetName} onChange={(event) => setAssetName(event.target.value)} />  
            </label>  
            <label className="field">  
              <span>生成方式</span>  
              <select value={imageProvider} onChange={(event) => setImageProvider(event.target.value as ImageProvider)}>  
                <option value="openai_api">OpenAI 密钥（gpt-image-2）</option>  
                <option value="codex_oauth">ChatGPT 订阅账号</option>  
              </select>  
            </label>  
            <label className="field">  
              <span>逻辑帧尺寸</span>  
              <input type="number" min={16} step={16} value={pixelCellSize} onChange={(event) => updatePixelCellSize(Number(event.target.value))} />  
            </label>  
            <label className="field">  
              <span>基准图输出尺寸</span>  
              <select value={pixelAnchorOutputSize} onChange={(event) => updatePixelAnchorOutputSize(event.target.value)}>  
                {anchorOutputOptions.length === 0 && <option value={pixelAnchorOutputSize}>没有可用的整数倍尺寸</option>}  
                {anchorOutputOptions.map((option) => (  
                  <option key={option.value} value={option.value}>  
                    {option.value}（逻辑帧 {option.scale}x）  
                  </option>  
                ))}  
              </select>  
              <small>基准图按逻辑帧尺寸整数倍生成，参考项目默认是 256 到 1024（4x）。</small>  
            </label>  
          </div>  
        </section>  
      );  
    }  
    
    function PixelStagePanel() {  
      if (activePixelStage === "tilemap_seed") {
        return (
          <section className="stage-card">
            <div className="section-header">
              <div>
                <div className="section-kicker">阶段 1</div>
                <strong>生成材质样例</strong>
              </div>
              <Wand2 size={18} />
            </div>
            <p className="field-hint">阶段一同步生成 outer / primary 两个纯材质样例格子。确认材质风格可用后，阶段二会读取这两个样例生成最终 Dual-Grid 16 地形集。</p>
            <label className="field">
              <span>整体风格备注</span>
              <textarea className="short-textarea" value={pixelTilemapSubject} onChange={(event) => setPixelTilemapSubject(event.target.value)} />
              <small>可选，用于统一调色、纹理密度和俯视角像素风格。</small>
            </label>
            <div className="two-col">
              <label className="field">
                <span>Outer 材质描述</span>
                <textarea className="short-textarea" value={pixelTilemapOuterMaterial} onChange={(event) => setPixelTilemapOuterMaterial(event.target.value)} />
                <small>例如泥土、道路、水、沙地等外侧/背景地形。</small>
              </label>
              <label className="field">
                <span>Primary 材质描述</span>
                <textarea className="short-textarea" value={pixelTilemapPrimaryMaterial} onChange={(event) => setPixelTilemapPrimaryMaterial(event.target.value)} />
                <small>例如草地、雪地、平台等内侧/主体地形。</small>
              </label>
            </div>
            <div className="three-col">
              <TileSizeSelect hint="样例格子会归一化为 256px 工作 tile；最终地形集按这个逻辑 tile 边长输出。" />
              <label className="field span-2">
                <span>UE 内容路径</span>
                <input value={contentPath} onChange={(event) => setContentPath(event.target.value)} />
              </label>
            </div>
            <button className="run-button" onClick={generateTilemapSeedConcept} disabled={disabled || !pixelTilemapOuterMaterial.trim() || !pixelTilemapPrimaryMaterial.trim()}>
              <Wand2 size={17} />
              生成材质样例
            </button>
          </section>
        );
      }

      if (activePixelStage === "tilemap_tileset") {
        return (
          <section className="stage-card">
            <div className="section-header">
              <div>
                <div className="section-kicker">阶段 2</div>
                <strong>生成 Dual-Grid 16 地形集</strong>
              </div>
              <Layers size={18} />
            </div>
            <p className="field-hint">读取阶段一的 outer / primary 样例格子，先程序化拼出 4x4 dual-grid 16 硬模板，再让 AI 只精修真实材质交界。</p>
            <div className="two-col">
              <label className="field">
                <span>Outer 样例路径</span>
                <input value={pixelTilemapOuterPath || pixelTilemapSeedPath} onChange={(event) => {
                  setPixelTilemapOuterPath(event.target.value);
                  setPixelTilemapSeedPath(event.target.value);
                }} placeholder="阶段 1 生成的 outer 样例路径" />
              </label>
              <label className="field">
                <span>Primary 样例路径</span>
                <input value={pixelTilemapPrimaryPath} onChange={(event) => setPixelTilemapPrimaryPath(event.target.value)} placeholder="阶段 1 生成的 primary 样例路径" />
              </label>
            </div>
            {(pixelTilemapOuterPath || pixelTilemapSeedPath || pixelTilemapPrimaryPath) && (
              <div className="sync-preview-grid">
                {[
                  { label: "Outer 样例格子", path: pixelTilemapOuterPath || pixelTilemapSeedPath },
                  { label: "Primary 样例格子", path: pixelTilemapPrimaryPath }
                ].map((sample) => (
                  <div className="sync-preview-tile" key={sample.label}>
                    <div className="sync-preview-title">
                      <strong>{sample.label}</strong>
                      <span>{sample.path ? "已选择" : "缺失"}</span>
                    </div>
                    <div className="sync-preview-frame">
                      {sample.path ? (
                        <img src={previewUrlForPath(projectRoot, sample.path)} alt={sample.label} />
                      ) : (
                        <span>暂无产物</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
            <TileSizeSelect hint="必须和阶段一材质样例使用的逻辑 tile 边长一致。" />
            <button className="run-button" onClick={composeTilemapFromSeed} disabled={disabled || !(pixelTilemapOuterPath || pixelTilemapSeedPath).trim() || !pixelTilemapPrimaryPath.trim()}>
              <Layers size={17} />
              生成 Dual-Grid 16 地形集
            </button>
            <div className="advanced-toggle">
              <button type="button" onClick={() => setTilemapImportOpen((current) => !current)}>
                {tilemapImportOpen ? "收起已有地形集导入" : "导入已有地形集图片"}
              </button>
            </div>
            {tilemapImportOpen && (
              <div className="three-col">
                <label className="field span-2">
                  <span>地形集图片路径</span>
                  <input value={pixelTileSetPath} onChange={(event) => setPixelTileSetPath(event.target.value)} placeholder="项目内相对路径或绝对路径" />
                </label>
                <TileSizeSelect label="导入尺寸" hint="单个 tile 边长，必须为 2 的幂次。" />
                <button className="run-button span-3" onClick={createTilemapManifest} disabled={disabled || !pixelTileSetPath.trim()}>
                  <FileJson size={17} />
                  只生成{tilemapStandardOption.label}规则清单
                </button>
              </div>
            )}
          </section>
        );
      }

      if (activePixelStage === "concept") {  
        return (  
          <section className="stage-card">  
            <div className="section-header">  
              <div>  
                <div className="section-kicker">阶段 0</div>  
                <strong>{kindCopy.conceptTitle}</strong>  
              </div>  
              <Wand2 size={18} />  
            </div>  
            <p className="field-hint">{kindCopy.conceptHint.replace("{size}", pixelAnchorOutputSize)}</p>  
            <label className="field">  
              <span>{kindCopy.subjectLabel}</span>  
              <textarea className="short-textarea" value={pixelSubject} onChange={(event) => setPixelSubject(event.target.value)} />  
            </label>  
            <label className="field">  
              <span>概念图路径（可选记录）</span>  
              <input value={pixelConceptPath} onChange={(event) => setPixelConceptPath(event.target.value)} placeholder="可留空；正面基准图只使用文本和像素网格" />  
            </label>  
            <button className="run-button" onClick={generatePixelConcept} disabled={disabled}>  
              <Wand2 size={17} />  
              {kindCopy.conceptButton}  
            </button>  
          </section>  
        );  
      }  
    
      if (activePixelStage === "south_anchor") {  
        return (  
          <section className="stage-card">  
            <div className="section-header">  
              <div>  
                <div className="section-kicker">阶段 1</div>  
                <strong>{kindCopy.anchorTitle}</strong>  
              </div>  
              <Sparkles size={18} />  
            </div>  
            <p className="field-hint">{kindCopy.anchorHint}</p>  
            <label className="field">  
              <span>{kindCopy.subjectLabel}</span>  
              <textarea className="short-textarea" value={pixelSubject} onChange={(event) => setPixelSubject(event.target.value)} />  
            </label>  
            <label className="toggle-row">  
              <input type="checkbox" checked={pixelAnchorUseConcept} onChange={(event) => setPixelAnchorUseConcept(event.target.checked)} />  
              <span>使用概念图作为基准图参考</span>  
            </label>  
            <div className="three-col">  
              <label className="field span-3">  
                <span>背景</span>  
                <input value={pixelAnchorUseConcept ? `概念图 + 像素网格 + #FF00FF 抠图色` : "文本 + 像素网格 + #FF00FF 抠图色"} readOnly />  
              </label>  
            </div>  
            {pixelAnchorUseConcept && !anchorConceptReferencePath() && <p className="field-hint warning">开启概念图参考时，需要先生成或填写当前资产的概念图路径。</p>}  
            <button className="run-button" onClick={() => generatePixelAnchor("south")} disabled={disabled || (pixelAnchorUseConcept && !anchorConceptReferencePath())}>  
              <Sparkles size={17} />  
              {kindCopy.anchorButton}  
            </button>  
          </section>  
        );  
      }  
    
      if (activePixelStage === "neutral_anchor") {  
        return (  
          <section className="stage-card">  
            <div className="section-header">  
              <div>  
                <div className="section-kicker">阶段 2</div>  
                <strong>中性姿态修正</strong>  
              </div>  
              <Eraser size={18} />  
            </div>  
            <p className="field-hint">当正面基准图带了火球、光效、武器挥动或施法姿势时，用“已有正面基准图 + 像素网格”重新生成无动态效果版本。</p>  
            <SlotPicker  
              group="pixel"  
              slotKey="southAnchor"  
              label="正面基准图"  
              roles={["anchor:south", "anchor:single"]}  
              description="中性姿态修正会读取这里的基准图。默认自动使用当前资产最新正面基准图。"  
            />  
            <div className="two-col">  
              <label className="field span-2">  
                <span>要移除的动态效果</span>  
                <textarea className="short-textarea" value={pixelDynamicEffect} onChange={(event) => setPixelDynamicEffect(event.target.value)} />  
              </label>  
            </div>  
            <button className="run-button" onClick={() => generatePixelAnchor("neutral")} disabled={disabled || !anchorPathForDirection("south")}>  
              <Eraser size={17} />  
              生成中性正面基准图  
            </button>  
          </section>  
        );  
      }  
    
      if (activePixelStage === "direction_anchor") {  
        return (  
          <section className="stage-card">  
            <div className="section-header">  
              <div>  
                <div className="section-kicker">阶段 3</div>  
                <strong>方向基准图</strong>  
              </div>  
              <Layers size={18} />  
            </div>  
            <p className="field-hint">左侧、背面、右侧都可以独立生成；选择右侧时也可以手动改为从左侧水平镜像生成。</p>  
            <SlotPicker  
              group="pixel"  
              slotKey="southAnchor"  
              label="身份基准图"  
              roles={["anchor:south"]}  
              description="方向基准图会读取这里的正面身份图，并与像素网格合成参考图。"  
            />  
            <div className="two-col">  
              <label className="field">  
                <span>方向</span>  
                <select value={pixelDirection} onChange={(event) => setPixelDirection(event.target.value)}>  
                  <option value="west">左侧</option>  
                  <option value="north">背面</option>  
                  <option value="east">右侧</option>  
                </select>  
              </label>  
              {pixelDirection === "east" && (  
                <div className="field checkbox-field">  
                  <span>右侧来源</span>  
                  <label>  
                    <input type="checkbox" checked={pixelMirrorEastFromWest} onChange={(event) => setPixelMirrorEastFromWest(event.currentTarget.checked)} />  
                    由左侧镜像生成  
                  </label>  
                  <small className="field-hint">关闭时会调用图像模型独立生成右侧基准图。</small>  
                </div>  
              )}  
            </div>  
            {pixelDirection === "east" && !pixelMirrorEastFromWest && (  
              <p className="field-hint warning">右侧独立生成会同时读取正面基准图和左侧基准图；请先生成左侧，否则后端会拒绝生成。</p>  
            )}  
            <button className="run-button" onClick={() => generatePixelAnchor("direction")} disabled={disabled}>  
              <Layers size={17} />  
              {pixelDirection === "east" && pixelMirrorEastFromWest ? "镜像右侧基准图" : "生成方向基准图"}  
            </button>  
          </section>  
        );  
      }  
    
      if (activePixelStage === "sheet") {  
        return (  
          <section className="stage-card">  
            <div className="section-header">  
              <div>  
                <div className="section-kicker">阶段 4</div>  
                <strong>{kindCopy.sheetTitle}</strong>  
              </div>  
              <Layers size={18} />  
            </div>  
            <div className="module-switcher sheet-mode-switcher" role="tablist" aria-label="动作序列图生成方式">  
              <button className={pixelSheetMode === "direct" ? "active" : ""} onClick={() => setPixelSheetMode("direct")} type="button">  
                直接生成序列图  
              </button>  
              <button className={pixelSheetMode === "video" ? "active" : ""} onClick={() => setPixelSheetMode("video")} type="button">  
                图生视频转序列图  
              </button>  
            </div>  
            <p className="field-hint">  
              {pixelSheetMode === "direct"  
                ? kindCopy.sheetDirectHint  
                : "视频模式适合行走、攻击等连续性要求高的动作；当前先生成动作视频，并保持在同一工序内管理。"}  
            </p>  
            <SlotPicker  
              group="pixel"  
              slotKey="directionAnchor"  
              label={kindCopy.anchorSlotLabel}  
              roles={[`anchor:${isCharacter ? (pixelSheetMode === "video" ? currentVideoDirection() : pixelDirection) : "single"}`]}  
              description={pixelSheetMode === "direct" ? kindCopy.anchorSlotDescription : "图生视频只使用这一张方向基准图作为图片输入。"}  
            />  
            {pixelSheetMode === "direct" ? (  
              <>  
                <div className="three-col">  
                  <PixelActionCommandField />  
                  {isCharacter ? (  
                    <label className="field">  
                      <span>方向</span>  
                      <select value={pixelDirection} onChange={(event) => setPixelDirection(event.target.value)}>  
                        <option value="south">正面</option>  
                        <option value="west">左侧</option>  
                        <option value="north">背面</option>  
                        <option value="east">右侧</option>  
                      </select>  
                    </label>  
                  ) : (  
                    <label className="field">  
                      <span>方向</span>  
                      <input readOnly value="单物件" />  
                    </label>  
                  )}  
                  <label className="field">  
                    <span>单帧尺寸</span>  
                    <input type="number" value={pixelCellSize} onChange={(event) => updatePixelCellSize(Number(event.target.value))} />  
                  </label>  
                  {isCharacter && pixelDirection === "east" && (  
                    <div className="field checkbox-field">  
                      <span>右侧来源</span>  
                      <label>  
                        <input type="checkbox" checked={pixelMirrorEastFromWest} onChange={(event) => setPixelMirrorEastFromWest(event.currentTarget.checked)} />  
                        由左侧序列图镜像  
                      </label>  
                      <small className="field-hint">关闭时会使用右侧基准图独立生成右侧序列图。</small>  
                    </div>  
                  )}  
                  <label className="field">  
                    <span>列数</span>  
                    <input type="number" value={pixelColumns} onChange={(event) => setPixelColumns(Number(event.target.value))} />  
                  </label>  
                  <label className="field">  
                    <span>行数</span>  
                    <input type="number" value={pixelRows} onChange={(event) => setPixelRows(Number(event.target.value))} />  
                  </label>  
                  {pixelAction === "attack" && (  
                    <>  
                      <label className="field">  
                        <span>攻击名</span>  
                        <input value={pixelAttackName} onChange={(event) => setPixelAttackName(event.target.value)} />  
                      </label>  
                      <label className="field">  
                        <span>效果颜色</span>  
                        <input value={pixelEffectColor} onChange={(event) => setPixelEffectColor(event.target.value)} />  
                      </label>  
                      <label className="field">  
                        <span>投射物/效果</span>  
                        <input value={pixelProjectileEffect} onChange={(event) => setPixelProjectileEffect(event.target.value)} />  
                      </label>  
                    </>  
                  )}  
                  {!knownActionLabel(currentPixelActionId()) && (  
                    <>  
                      <label className="field">  
                        <span>显示名</span>  
                        <input value={pixelCustomActionName} onChange={(event) => setPixelCustomActionName(event.target.value)} placeholder="例如：闪避翻滚 / 施法 / 装填" />  
                      </label>  
                      <label className="field span-3">  
                        <span>动作描述</span>  
                        <textarea className="short-textarea" value={pixelActionDescription} onChange={(event) => setPixelActionDescription(event.target.value)} />  
                      </label>  
                    </>  
                  )}  
                </div>  
                <div className="button-row wrap">  
                  <button className="run-button" onClick={generatePixelSheet} disabled={disabled}>  
                    <Layers size={17} />  
                    生成{currentPixelActionLabel()}序列图  
                  </button>  
                  <button className="secondary-action tall" onClick={importPixelSheet} disabled={disabled} type="button">  
                    <FileImage size={15} />  
                    导入序列帧  
                  </button>  
                </div>  
              </>  
            ) : (  
              <>  
                <div className="three-col">  
                  <PixelActionCommandField />  
                  {isCharacter ? (  
                    <label className="field">  
                      <span>方向</span>  
                      <select value={currentVideoDirection()} onChange={(event) => setPixelDirection(event.target.value)}>  
                        <option value="south">正面</option>  
                        <option value="west">左侧</option>  
                        <option value="north">背面</option>  
                        <option value="east">右侧</option>  
                      </select>  
                    </label>  
                  ) : (  
                    <label className="field">  
                      <span>方向</span>  
                      <input readOnly value="单物件" />  
                    </label>  
                  )}  
                  <label className="field">  
                    <span>视频时长（秒）</span>  
                    <input type="number" min={4} max={15} value={pixelSeedanceSeconds} onChange={(event) => setPixelSeedanceSeconds(Number(event.target.value))} />  
                  </label>  
                  <div className="field span-3 seedance-workspace-field">  
                    <span>本次 Seedance 模型</span>  
                    <CommandCombobox  
                      value={activeSeedanceModel}  
                      onValueChange={updatePixelSeedanceModel}  
                      options={workspaceSeedanceModelOptions}  
                      placeholder={seedanceDefaultModel}  
                      searchPlaceholder="搜索 Seedance 模型"  
                    />  
                    <small className="field-hint">默认：{seedanceDefaultModel}，可为当前工作区生成覆盖选择。</small>  
                  </div>  
                  <div className="field span-3 seedance-workspace-field">  
                    <span>本次视频分辨率</span>  
                    <CommandCombobox  
                      value={activeSeedanceResolution}  
                      onValueChange={setPixelSeedanceResolution}  
                      options={workspaceSeedanceResolutionOptions}  
                      placeholder={seedanceDefaultResolution}  
                      searchPlaceholder="搜索或输入分辨率"  
                    />  
                    <small className="field-hint">默认：{seedanceDefaultResolution}，可用选项会随本次 Seedance 模型变化。</small>  
                  </div>  
                  <label className="field">  
                    <span>单帧尺寸</span>  
                    <input type="number" value={pixelCellSize} onChange={(event) => updatePixelCellSize(Number(event.target.value))} />  
                  </label>  
                  <label className="field">  
                    <span>自动布局</span>  
                    <input readOnly value={videoFrameSelections.length > 0 ? `${videoSheetLayoutForFrameCount(videoFrameSelections.length).columns} x ${videoSheetLayoutForFrameCount(videoFrameSelections.length).rows}` : "选帧后计算"} />  
                    <small className="field-hint">按已选帧数自动计算列数和行数。</small>  
                  </label>  
                  {!knownActionLabel(currentPixelActionId()) && (  
                    <label className="field">  
                      <span>显示名</span>  
                      <input value={pixelCustomActionName} onChange={(event) => setPixelCustomActionName(event.target.value)} placeholder="例如：闪避翻滚 / 施法 / 装填" />  
                    </label>  
                  )}  
                  <label className="field span-3">  
                    <span>图生视频动作描述</span>  
                    <textarea className="short-textarea" value={pixelI2vActionDescription} onChange={(event) => setPixelI2vActionDescription(event.target.value)} />  
                  </label>  
                  <label className="field span-3">  
                    <span>动作视频路径</span>  
                    <input value={pixelVideoPath} onChange={(event) => setPixelVideoPath(event.target.value)} placeholder={videoSourceSlot()?.version.path || "生成视频后自动填入，也可粘贴项目内相对路径或绝对路径"} />  
                  </label>  
                </div>  
                <button className="run-button" onClick={generateSeedanceVideo} disabled={disabled || !seedanceAnchorCandidate}>  
                  <Play size={17} />  
                  生成{currentPixelActionLabel()}动作视频  
                </button>  
                <div className="video-frame-summary video-frame-middle-step">  
                  <span>  
                    已选 {videoFrameSelections.length} 帧{videoFrameSelections.length > 0 ? `，自动打包为 ${videoSheetLayoutForFrameCount(videoFrameSelections.length).columns}x${videoSheetLayoutForFrameCount(videoFrameSelections.length).rows}` : "，选帧后自动计算布局"}  
                  </span>  
                  <button className="secondary-action" onClick={openVideoFramePicker} disabled={disabled || !currentVideoSourcePath()} type="button">  
                    <Scissors size={15} />  
                    选择视频帧  
                  </button>  
                </div>  
                <button className="run-button" onClick={generatePixelSheetFromVideo} disabled={disabled || !currentVideoSourcePath() || videoFrameSelections.length === 0}>  
                  <Layers size={17} />  
                  抽帧打包为序列图  
                </button>  
              </>  
            )}  
          </section>  
        );  
      }  
    
      if (activePixelStage === "cutout") {  
        return (  
          <section className="stage-card">  
            <div className="section-header">  
              <div>  
                <div className="section-kicker">阶段 5</div>  
                <strong>背景透明化</strong>  
              </div>  
              <Eraser size={18} />  
            </div>  
            <p className="field-hint">使用 Hybrid Mask 对当前动作序列图逐帧透明化：OpenCV 找边缘连通背景，rembg 提供语义参考，并保持每个 cell 的原始位置。</p>  
            <SlotPicker  
              group="pixel"  
              slotKey="cutoutSource"  
              label="待透明化序列图"  
              roles={[currentSheetRole()]}  
              description="默认读取动作序列图阶段最新生成的 Sheet。"  
            />  
            <div className="two-col">  
              <div className="field">  
                <span>Mask 模式</span>  
                <CommandCombobox  
                  value={pixelMaskMode}  
                  onValueChange={(value) => setPixelMaskMode(value as PixelMaskMode)}  
                  options={PIXEL_MASK_MODE_OPTIONS}  
                  placeholder="hybrid"  
                  searchPlaceholder="搜索透明化模式"  
                  allowCustom={false}  
                />  
              </div>  
              <label className="field">  
                <span>rembg 模型</span>  
                <select value={rembgModel} onChange={(event) => setRembgModel(event.target.value)}>  
                  <option value="isnet-general-use">isnet-general-use</option>  
                  <option value="isnet-anime">isnet-anime</option>  
                  <option value="u2netp">u2netp</option>  
                </select>  
              </label>  
              <label className="mini-toggle">  
                <input type="checkbox" checked={pixelDecontaminateEdges} onChange={(event) => setPixelDecontaminateEdges(event.currentTarget.checked)} />  
                白边去污染  
              </label>  
              <label className="mini-toggle">  
                <input type="checkbox" checked={pixelDebugArtifacts} onChange={(event) => setPixelDebugArtifacts(event.currentTarget.checked)} />  
                输出 debug mask  
              </label>  
            </div>  
            <button className="run-button" onClick={removePixelSheetBackground} disabled={disabled || !(pixelSheetPath || cutoutSourceSlot())}>  
              <Eraser size={17} />  
              透明化序列图背景  
            </button>  
          </section>  
        );  
      }  
    
      return (  
        <section className="stage-card">  
          <div className="section-header">  
            <div>  
              <div className="section-kicker">阶段 6</div>  
              <strong>归一化</strong>  
            </div>  
            <Scissors size={18} />  
          </div>  
          <p className="field-hint">读取透明化后的 Sheet，测透明区域、统一可见高度、锁定脚底基线、重建图集并生成预览图。</p>  
          <SlotPicker  
            group="pixel"  
            slotKey="normalizeSource"  
            label="归一化源图"  
            roles={[currentCutoutRole(), currentSheetRole()]}  
            description="默认优先读取背景透明化输出；没有透明化版本时才回退到原始动画 Sheet。"  
          />  
          <div className="three-col">  
            <label className="field span-2">  
              <span>行列</span>  
              <input readOnly value="自动从源 Sheet 尺寸推断" />  
            </label>  
            <label className="field">  
              <span>单帧尺寸</span>  
              <input type="number" value={pixelCellSize} onChange={(event) => updatePixelCellSize(Number(event.target.value))} />  
            </label>  
          </div>  
          <div className="field">  
            <span>像素修复</span>  
            <CommandCombobox  
              value={pixelRestoreMode}  
              onValueChange={(value) => setPixelRestoreMode(value as PixelRestoreMode)}  
              options={PIXEL_RESTORE_MODE_OPTIONS}  
              placeholder="none"  
              searchPlaceholder="搜索 unfake 模式"  
              allowCustom={false}  
            />  
          </div>  
          <button className="run-button" onClick={normalizePixelSheet} disabled={disabled || !(pixelCutoutPath || normalizeSourceSlot() || pixelSheetPath)}>  
            <Scissors size={17} />  
            归一化运行时序列图  
          </button>  
        </section>  
      );  
    }  
    
    function currentMatrixActionKey(): PixelMatrixActionKey {  
      return currentPixelActionId();  
    }  
    
    function MatrixStatusBadge({ cell }: { cell: PixelMatrixCellState }) {  
      return (  
        <span className={`matrix-status ${cell.status}`}>  
          {cell.status === "runtime" && <CheckCircle2 size={13} />}  
          {cell.status === "stale" && <RefreshCw size={13} />}  
          {cell.status === "cutout" && <Eraser size={13} />}  
          {cell.status === "sheet" && <Layers size={13} />}  
          {cell.status === "video" && <Play size={13} />}  
          {cell.status === "missing" && <FileImage size={13} />}  
          {cell.statusLabel}  
        </span>  
      );  
    }  
    
    function PixelMatrixWorkbench() {  
      const selectedCount = pixelMatrixSelection.length;  
      const activeKey = pixelMatrixCellKey(currentMatrixActionKey(), currentSheetDirection() as PixelMatrixDirection);  
      return (  
        <section className="pixel-workbench" aria-label="动作方向矩阵">  
          <div className="workbench-header">  
            <div>  
              <div className="section-kicker">资产工作台</div>  
              <strong>动作 x 方向矩阵</strong>  
              <span>点击格子编辑当前任务，勾选格子后批量执行后处理。</span>  
            </div>  
            <div className="batch-toolbar" aria-label="批处理操作">  
              <span>{selectedCount ? `已选 ${selectedCount} 项` : "未选择批处理项"}</span>  
              <button className="secondary-action" onClick={() => runPixelBatch("generate_missing")} disabled={disabled || selectedCount === 0} type="button">  
                <Sparkles size={15} />  
                生成缺失  
              </button>  
              <button className="secondary-action" onClick={() => runPixelBatch("cutout")} disabled={disabled || selectedCount === 0} type="button">  
                <Eraser size={15} />  
                背景透明化  
              </button>  
              <button className="secondary-action" onClick={() => runPixelBatch("normalize")} disabled={disabled || selectedCount === 0} type="button">  
                <Scissors size={15} />  
                归一化/预览  
              </button>  
              <button className="run-button compact" onClick={() => runPixelBatch("cutout_normalize")} disabled={disabled || selectedCount === 0} type="button">  
                <CheckCircle2 size={15} />  
                透明化+归一化  
              </button>  
              <button className="secondary-action icon-only" onClick={() => setPixelMatrixSelection([])} disabled={selectedCount === 0} type="button" aria-label="清空矩阵选择" title="清空选择">  
                <Trash2 size={15} />  
              </button>  
            </div>  
          </div>  
          <div className="pixel-matrix" role="grid" aria-label="动作方向状态">  
            <div className="matrix-corner">动作</div>  
            {pixelMatrixDirections.map((direction) => (  
              <div className="matrix-heading" key={direction}>  
                {pixelDirectionLabel(direction)}  
              </div>  
            ))}  
            {pixelMatrixActions.map((action) => (  
              <React.Fragment key={action.key}>  
                <div className="matrix-row-label">  
                  <strong>{action.label}</strong>  
                  <small>{action.id}</small>  
                </div>  
                {pixelMatrixDirections.map((direction) => {  
                  const cell = pixelMatrixCellState(action.key, direction);  
                  const selected = pixelMatrixSelection.includes(cell.key);  
                  const active = activeKey === cell.key;  
                  return (  
                    <div  
                      className={`matrix-cell ${selected ? "selected" : ""} ${active ? "active" : ""} ${cell.stale ? "stale" : ""}`}  
                      key={cell.key}  
                      onClick={() => handlePixelMatrixCellClick(action.key, direction)}  
                    >  
                      <label className="matrix-cell-top" onClick={(event) => event.stopPropagation()}>  
                        <input  
                          aria-label={`选择 ${cell.actionLabel} ${cell.directionLabel}`}  
                          checked={selected}  
                          onClick={(event) => event.stopPropagation()}  
                          onChange={() => togglePixelMatrixCell(action.key, direction)}  
                          type="checkbox"  
                        />  
                        <MatrixStatusBadge cell={cell} />  
                      </label>  
                      <button  
                        className="matrix-cell-button"  
                        onClick={(event) => {  
                          event.stopPropagation();  
                          handlePixelMatrixCellClick(action.key, direction);  
                        }}  
                        type="button"  
                      >  
                        <strong>{cell.directionLabel}</strong>  
                        <small>{cell.preview ? browserVersionDate(cell.preview) : cell.runtime ? browserVersionDate(cell.runtime) : cell.cutout ? browserVersionDate(cell.cutout) : cell.sheet ? browserVersionDate(cell.sheet) : "没有产物"}</small>  
                      </button>  
                    </div>  
                  );  
                })}  
              </React.Fragment>  
            ))}  
          </div>  
        </section>  
      );  
    }  
    
    function BatchQueuePanel() {  
      return (  
        <section className="batch-queue-panel" aria-label="批处理队列">  
          <div className="section-header">  
            <div>  
              <div className="section-kicker">批处理队列</div>  
              <strong>串行执行状态</strong>  
            </div>  
            <RefreshCw size={18} />  
          </div>  
          {pixelBatchQueue.length === 0 ? (  
            <p className="field-hint">勾选矩阵格子后执行批处理，队列会显示每个方向/动作的阶段和日志。</p>  
          ) : (  
            <div className="batch-task-list">  
              {pixelBatchQueue.map((task) => (  
                <article className={`batch-task ${task.status}`} key={task.id}>  
                  <div className="batch-task-main">  
                    <strong>  
                      {pixelMatrixActionLabel(task.actionKey)} / {pixelDirectionLabel(task.direction)}  
                    </strong>  
                    <span>{task.currentStep ? `正在执行 ${task.currentStep}` : task.status === "done" ? "完成" : task.status === "failed" ? "失败" : "等待"}</span>  
                  </div>  
                  <div className="batch-task-steps">  
                    {task.steps.map((step) => (  
                      <span className={task.currentStep === step ? "active" : ""} key={step}>  
                        {step}  
                      </span>  
                    ))}  
                  </div>  
                  {task.error && <p className="batch-error">{task.error}</p>}  
                  {task.logs.length > 0 && (  
                    <div className="batch-task-log">  
                      {task.logs.slice(-4).map((entry, index) => (  
                        <span key={`${task.id}:${index}`}>{entry}</span>  
                      ))}  
                    </div>  
                  )}  
                  {task.status === "failed" && (  
                    <button className="secondary-action" onClick={() => runPixelBatch("cutout_normalize", task)} disabled={disabled} type="button">  
                      <RefreshCw size={15} />  
                      重试  
                    </button>  
                  )}  
                </article>  
              ))}  
            </div>  
          )}  
        </section>  
      );  
    }  
    
    function CurrentTaskDetails() {  
      const cell = pixelMatrixCellState(currentMatrixActionKey(), currentSheetDirection() as PixelMatrixDirection);  
      const versions = [  
        ["Sheet", cell.sheet],  
        ["透明化", cell.cutout],  
        ["Runtime", cell.runtime],  
        ["Preview", cell.preview],  
        ["Video", cell.video]  
      ] as Array<[string, AssetImageVersion | undefined]>;  
      return (  
        <section className="current-task-panel" aria-label="当前任务详情">  
          <div className="section-header">  
            <div>  
              <div className="section-kicker">当前任务</div>  
              <strong>  
                {cell.actionLabel} / {cell.directionLabel}  
              </strong>  
            </div>  
            <MatrixStatusBadge cell={cell} />  
          </div>  
          {cell.stale && <p className="stale-warning">当前 runtime 来自旧 pipeline 或仍包含裁切信息，建议重新执行归一化。</p>}  
          <div className="version-strip">  
            {versions.map(([label, version]) => (  
              <button  
                className={version ? "version-pill available" : "version-pill"}  
                disabled={!version}  
                key={label}  
                onClick={() => {  
                  if (!version) return;  
                  setActivePreviewVersionId(version.id);  
                  setActivePreviewPath(version.path);  
                  setActivePreviewLabel(`${cell.actionLabel} / ${cell.directionLabel} / ${label}`);  
                }}  
                type="button"  
              >  
                <strong>{label}</strong>  
                <span>{version ? browserVersionDate(version) || version.role : "缺失"}</span>  
              </button>  
            ))}  
          </div>  
        </section>  
      );  
    }  
    
    function SyncPreviewPanel() {  
      const actionKey = currentMatrixActionKey();  
      const [syncPreviewFrame, setSyncPreviewFrame] = useState(0);  
      const [syncPreviewPlaying, setSyncPreviewPlaying] = useState(false);  
      const [syncPreviewShowGrid, setSyncPreviewShowGrid] = useState(true);  
      const [syncPreviewShowBaseline, setSyncPreviewShowBaseline] = useState(true);  
      const frameCount = Math.max(1, pixelColumns * pixelRows);  
      const frame = Math.max(0, Math.min(syncPreviewFrame, frameCount - 1));  
      const frameColumn = frame % pixelColumns;  
      const frameRow = Math.floor(frame / pixelColumns);  
      const backgroundPositionX = pixelColumns <= 1 ? "0%" : `${(frameColumn / (pixelColumns - 1)) * 100}%`;  
      const backgroundPositionY = pixelRows <= 1 ? "0%" : `${(frameRow / (pixelRows - 1)) * 100}%`;  
    
      useEffect(() => {  
        if (!syncPreviewPlaying) return undefined;  
        const timer = window.setInterval(() => {  
          setSyncPreviewFrame((current) => (current + 1) % frameCount);  
        }, 150);  
        return () => window.clearInterval(timer);  
      }, [syncPreviewPlaying, frameCount]);  
    
      return (  
        <section className="sync-preview-panel" aria-label="四方向同步预览">  
          <div className="sync-preview-toolbar">  
            <div>  
              <div className="section-kicker">同步预览</div>  
              <strong>{pixelMatrixActionLabel(actionKey)} 四方向</strong>  
            </div>  
            <div className="sync-preview-actions">  
              <button className="secondary-action icon-only" onClick={() => setSyncPreviewFrame((current) => (current - 1 + frameCount) % frameCount)} type="button" aria-label="上一帧" title="上一帧">  
                <SkipBack size={15} />  
              </button>  
              <button className="secondary-action" onClick={() => setSyncPreviewPlaying((current) => !current)} type="button">  
                <Play size={15} />  
                {syncPreviewPlaying ? "暂停" : "播放"}  
              </button>  
              <button className="secondary-action icon-only" onClick={() => setSyncPreviewFrame((current) => (current + 1) % frameCount)} type="button" aria-label="下一帧" title="下一帧">  
                <SkipForward size={15} />  
              </button>  
              <label className="mini-toggle">  
                <input checked={syncPreviewShowGrid} onChange={(event) => setSyncPreviewShowGrid(event.target.checked)} type="checkbox" />  
                格线  
              </label>  
              <label className="mini-toggle">  
                <input checked={syncPreviewShowBaseline} onChange={(event) => setSyncPreviewShowBaseline(event.target.checked)} type="checkbox" />  
                脚线  
              </label>  
            </div>  
          </div>  
          <div className="sync-preview-grid">  
            {pixelMatrixDirections.map((direction) => {  
              const cell = pixelMatrixCellState(actionKey, direction);  
              const controlled = cell.runtime;  
              const fallback = cell.preview || cell.cutout || cell.sheet;  
              return (  
                <div className="sync-preview-tile" key={direction}>  
                  <div className="sync-preview-title">  
                    <strong>{pixelDirectionLabel(direction)}</strong>  
                    <span>{controlled ? "runtime" : fallback ? "preview" : "缺失"}</span>  
                  </div>  
                  <div className={`sync-preview-frame ${syncPreviewShowGrid ? "show-grid" : ""} ${syncPreviewShowBaseline ? "show-baseline" : ""}`}>  
                    {controlled ? (  
                      <div  
                        className="sync-preview-sheet"  
                        style={{  
                          backgroundImage: `url("${previewUrlForPath(projectRoot, controlled.path)}")`,  
                          backgroundPosition: `${backgroundPositionX} ${backgroundPositionY}`,  
                          backgroundSize: `${pixelColumns * 100}% ${pixelRows * 100}%`  
                        }}  
                      />  
                    ) : fallback ? (  
                      <img src={previewUrlForPath(projectRoot, fallback.path)} alt={`${pixelDirectionLabel(direction)} 预览`} />  
                    ) : (  
                      <span>暂无产物</span>  
                    )}  
                  </div>  
                </div>  
              );  
            })}  
          </div>  
        </section>  
      );  
    }  
    
    return (  
      <div className="module-page pixel-compact-page">  
        <section className="form-panel">  
          {WorkerAlert()}  
          <div className="panel-heading">  
            <Layers size={18} />  
            <div>  
              <h3>像素序列帧专项生产</h3>  
              <p>按参考仓库拆成明确阶段：概念图、基准图、动作序列图、背景透明化、归一化。动作序列图阶段可选择直接生成或图生视频路径。</p>  
            </div>  
          </div>  
          {PixelGlobals()}  
          {isCharacter && !isTilemap && (  
            <>  
              <PixelMatrixWorkbench />  
              <div className="pixel-summary-grid">  
                <CurrentTaskDetails />  
                <BatchQueuePanel />  
              </div>  
              <section className="collapsible-workbench-panel">  
                <button className="collapsible-panel-trigger" onClick={() => setPixelPreviewOpen((current) => !current)} type="button">  
                  <span>  
                    <strong>同步预览</strong>  
                    <small>{pixelPreviewOpen ? "收起四方向播放面板" : "展开查看四方向播放与帧控制"}</small>  
                  </span>  
                  <ChevronDown className={pixelPreviewOpen ? "expanded" : ""} size={16} />  
                </button>  
                {pixelPreviewOpen && <SyncPreviewPanel />}  
              </section>  
            </>  
          )}  
          {AssetPreview()}  
          <div className="workflow-layout secondary-workflow">  
            {StageNav()}  
            <div className="task-detail-stack">  
              {PixelStagePanel()}  
            </div>  
          </div>  
        </section>  
      </div>  
    );  
  }  
    
  
  return PixelSpritesheetPage();
}
