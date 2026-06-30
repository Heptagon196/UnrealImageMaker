// @ts-nocheck
import React from "react";
import * as AlertDialog from "@radix-ui/react-alert-dialog";
import { Play, SkipBack, SkipForward, Trash2 } from "lucide-react";
import { useAppContext } from "../AppContext";

function GameUiSkinPreviewDialog() {
  const {
    exportGameUiUmg,
    flattenGameUiPreviewNodes,
    gameUiColorOrFallback,
    gameUiPreviewCanvasRef,
    gameUiPreviewCanvasWidth,
    gameUiPreviewData,
    gameUiPreviewLoading,
    gameUiPreviewOpen,
    gameUiSelectedKitPath,
    gameUiStructurePath,
    renderGameUiPreviewNode,
    selectedKitNameFromPath,
    selectedStructureNameFromPath,
    setGameUiPreviewOpen
  } = useAppContext();
  const structure = gameUiPreviewData?.structure;
  const root = structure?.root;
  const refWidth = Math.max(1, structure?.referenceResolution?.width || root?.width || 1920);
  const refHeight = Math.max(1, structure?.referenceResolution?.height || root?.height || 1080);
  const nodes = flattenGameUiPreviewNodes(root, refWidth, refHeight);
  const previewScale = Math.max(0.05, gameUiPreviewCanvasWidth > 0 ? gameUiPreviewCanvasWidth / refWidth : Math.min(1, 760 / refWidth));
  const screenName = structure?.screenName || selectedStructureNameFromPath(gameUiPreviewData?.structurePath || gameUiStructurePath);
  const kitName = gameUiPreviewData?.textureKit.kitName || selectedKitNameFromPath(gameUiPreviewData?.textureKitPath || gameUiSelectedKitPath);

  return (
    <AlertDialog.Root open={gameUiPreviewOpen} onOpenChange={setGameUiPreviewOpen}>
      <AlertDialog.Portal>
        <AlertDialog.Overlay className="alert-dialog-overlay" />
        <AlertDialog.Content className="alert-dialog-content game-ui-preview-dialog">
          <AlertDialog.Title className="alert-dialog-title">UI 贴图应用预览</AlertDialog.Title>
          <AlertDialog.Description className="alert-dialog-description">
            按当前结构 JSON 的坐标和 style token，套用已选择的 UI 贴图组；正式导出 UMG 时会使用同一组输入。
          </AlertDialog.Description>
          <div className="game-ui-preview-meta">
            <span>
              <strong>{screenName || "未命名屏幕"}</strong>
              <small>{refWidth}x{refHeight}</small>
            </span>
            <span>
              <strong>{kitName || "未命名贴图组"}</strong>
              <small>{nodes.length} nodes</small>
            </span>
          </div>
          {gameUiPreviewLoading ? (
            <div className="game-ui-preview-empty">正在加载预览数据...</div>
          ) : root ? (
            <div className="game-ui-preview-viewport">
              <div
                ref={gameUiPreviewCanvasRef}
                className="game-ui-preview-canvas"
                style={{
                  aspectRatio: `${refWidth} / ${refHeight}`,
                  backgroundColor: gameUiColorOrFallback(root.color, "#171d26")
                }}
              >
                {nodes.map((node, index) => renderGameUiPreviewNode(node, refWidth, refHeight, previewScale, index))}
              </div>
            </div>
          ) : (
            <div className="game-ui-preview-empty">没有可预览的结构数据。</div>
          )}
          <div className="alert-dialog-actions">
            <AlertDialog.Cancel className="dialog-button secondary">关闭</AlertDialog.Cancel>
            <AlertDialog.Action className="dialog-button" onClick={exportGameUiUmg} disabled={!gameUiStructurePath || !gameUiSelectedKitPath}>
              一键导出到 UE
            </AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}

function GameUiClearTextureKitDialog() {
  const { clearGameUiTextureKit, gameUiClearTextureKitTarget, pushLog, setGameUiClearTextureKitTarget } = useAppContext();
  if (!gameUiClearTextureKitTarget) return null;

  const target = gameUiClearTextureKitTarget;
  const confirmClear = () => {
    setGameUiClearTextureKitTarget(null);
    clearGameUiTextureKit(target).catch((error) => pushLog(error.message));
  };

  return (
    <AlertDialog.Root open={Boolean(gameUiClearTextureKitTarget)} onOpenChange={(open) => !open && setGameUiClearTextureKitTarget(null)}>
      <AlertDialog.Portal>
        <AlertDialog.Overlay className="alert-dialog-overlay" />
        <AlertDialog.Content className="alert-dialog-content">
          <div className="alert-dialog-icon" aria-hidden="true">
            <Trash2 size={20} />
          </div>
          <AlertDialog.Title className="alert-dialog-title">清空 UI 贴图组</AlertDialog.Title>
          <AlertDialog.Description className="alert-dialog-description">
            确定要清空“{target.kitName}”吗？这会删除该贴图组配置，并删除项目 ui 目录下由它引用或生成的贴图文件、状态图和调试工作目录。
          </AlertDialog.Description>
          <div className="alert-dialog-actions">
            <AlertDialog.Cancel className="dialog-button secondary">取消</AlertDialog.Cancel>
            <AlertDialog.Action className="dialog-button danger" onClick={confirmClear}>
              清空贴图
            </AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}

function DeleteConfirmDialog() {
  const {
    deleteAssetFromTree,
    deleteAssetVersion,
    pendingDelete,
    pushLog,
    setPendingDelete,
    versionDisplayLabel
  } = useAppContext();
  if (pendingDelete === null) return null;

  const title = pendingDelete?.kind === "asset" ? "删除资产" : "删除版本";
  const targetName =
    pendingDelete?.kind === "asset"
      ? pendingDelete.asset.name
      : pendingDelete?.kind === "version"
        ? versionDisplayLabel(pendingDelete.version)
        : "";
  const description =
    pendingDelete?.kind === "asset"
      ? "这会删除当前 .uim 项目中的资产目录及其所有版本图片。"
      : "这会从当前资产中移除该版本；如果图片位于当前 .uim 项目内，也会同时删除图片文件。";
  const confirmDelete = () => {
    const target = pendingDelete;
    setPendingDelete(null);
    if (!target) return;
    if (target.kind === "asset") {
      deleteAssetFromTree(target.asset).catch((error) => pushLog(error.message));
    } else {
      deleteAssetVersion(target.version).catch((error) => pushLog(error.message));
    }
  };

  return (
    <AlertDialog.Root open={pendingDelete !== null} onOpenChange={(open) => !open && setPendingDelete(null)}>
      <AlertDialog.Portal>
        <AlertDialog.Overlay className="alert-dialog-overlay" />
        <AlertDialog.Content className="alert-dialog-content">
          <div className="alert-dialog-icon" aria-hidden="true">
            <Trash2 size={20} />
          </div>
          <AlertDialog.Title className="alert-dialog-title">{title}</AlertDialog.Title>
          <AlertDialog.Description className="alert-dialog-description">
            确定要删除“{targetName}”吗？{description}
          </AlertDialog.Description>
          <div className="alert-dialog-actions">
            <AlertDialog.Cancel className="dialog-button secondary">取消</AlertDialog.Cancel>
            <AlertDialog.Action className="dialog-button danger" onClick={confirmDelete}>
              删除
            </AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}

function VideoFramePickerDialog() {
  const {
    DEFAULT_VIDEO_LOOP_MIN_SCORE,
    addCurrentVideoFrame,
    autoSelectVideoFramesByFps,
    clearVideoSelectionPreview,
    clampVideoPickerTime,
    currentVideoSourcePath,
    exportVideoFrameQueue,
    findVideoLoopFrame,
    formatVideoTime,
    handleVideoFrameDragStart,
    handleVideoFrameDrop,
    handleVideoFrameTileClick,
    hydrateVideoFrameSelectionThumbnails,
    playVideoLoopPreview,
    playVideoSelectionPreview,
    previewUrlForPath,
    projectRoot,
    pushLog,
    removeSelectedVideoFrames,
    removeVideoFrameSelection,
    seekVideoFrameSelection,
    selectedLoopFrameId,
    selectedLoopFrameIndex,
    setAllVideoFrameSelections,
    setSelectedLoopFrameId,
    setVideoAutoFps,
    setVideoFramePickerOpen,
    setVideoFrameSelections,
    setVideoLoopMinScore,
    setVideoPickerCurrentTime,
    setVideoPickerDuration,
    setVideoPreviewNaturalSize,
    setVideoRangeEnd,
    setVideoRangeStart,
    setVideoSourceAspectRatio,
    stepVideoFrame,
    trimVideoFramesToLoopPoint,
    updateVideoRangeEnd,
    updateVideoRangeStart,
    videoAutoFps,
    videoFramePickerOpen,
    videoFramePickerRef,
    videoFrameSelections,
    videoFrameThumbnailsLoading,
    videoLoopMinScore,
    videoLoopPreviewing,
    videoPickerCurrentTime,
    videoPickerDuration,
    videoPreviewNaturalSize,
    videoPreviewStageRef,
    videoPreviewStageSize,
    videoRangeEnd,
    videoRangeStart,
    videoSelectionPreviewIndex,
    videoSelectionPreviewing,
    videoSheetLayoutForFrameCount,
    videoSourceAspectRatio
  } = useAppContext();
  if (!videoFramePickerOpen) return null;

  const source = currentVideoSourcePath();
  const sourceUrl = source ? previewUrlForPath(projectRoot, source) : "";
  const rangeDuration = Math.max(0, videoPickerDuration);
  const rangeStart = Math.min(videoRangeStart, videoRangeEnd || rangeDuration);
  const rangeEnd = Math.max(videoRangeStart, videoRangeEnd || rangeDuration);
  const rangeStartPercent = rangeDuration > 0 ? (clampVideoPickerTime(rangeStart, rangeDuration) / rangeDuration) * 100 : 0;
  const rangeEndPercent = rangeDuration > 0 ? (clampVideoPickerTime(rangeEnd, rangeDuration) / rangeDuration) * 100 : 100;
  const selectedQueueCount = videoFrameSelections.filter((selection) => selection.selected).length;
  const loopCandidates = videoFrameSelections.filter((selection) => selection.loopHint);
  const loopFrame = videoFrameSelections.find((selection) => selection.loopHint && selection.id === selectedLoopFrameId) || loopCandidates[0];
  const queueReady = videoFrameSelections.length > 0;
  const queueLayout = videoSheetLayoutForFrameCount(videoFrameSelections.length);
  const previewFrame = videoSelectionPreviewIndex !== null ? videoFrameSelections[videoSelectionPreviewIndex] : null;
  const previewFrameActive = Boolean((videoSelectionPreviewing || videoLoopPreviewing) && previewFrame?.thumbnail);
  const previewSequenceLength = videoLoopPreviewing ? Math.max(1, selectedLoopFrameIndex(videoFrameSelections)) : Math.max(1, videoFrameSelections.length);
  const previewSequencePosition = previewFrameActive && videoSelectionPreviewIndex !== null ? Math.min(videoSelectionPreviewIndex + 1, previewSequenceLength) : 0;
  const previewProgressPercent = previewFrameActive ? Math.max(0, Math.min(100, (previewSequencePosition / previewSequenceLength) * 100)) : 0;
  const previewPadding = 32;
  const previewAvailableWidth = Math.max(1, videoPreviewStageSize.width - previewPadding);
  const previewAvailableHeight = Math.max(1, videoPreviewStageSize.height - previewPadding);
  const previewScale =
    videoPreviewNaturalSize.width > 0 && videoPreviewNaturalSize.height > 0
      ? Math.min(previewAvailableWidth / videoPreviewNaturalSize.width, previewAvailableHeight / videoPreviewNaturalSize.height)
      : 1;
  const previewImageStyle =
    videoPreviewNaturalSize.width > 0 && videoPreviewNaturalSize.height > 0
      ? {
          width: `${Math.max(1, Math.floor(videoPreviewNaturalSize.width * previewScale))}px`,
          height: `${Math.max(1, Math.floor(videoPreviewNaturalSize.height * previewScale))}px`
        }
      : undefined;

  return (
    <AlertDialog.Root open={videoFramePickerOpen} onOpenChange={setVideoFramePickerOpen}>
      <AlertDialog.Portal>
        <AlertDialog.Overlay className="alert-dialog-overlay" />
        <AlertDialog.Content className="alert-dialog-content frame-picker-dialog">
          <AlertDialog.Title className="alert-dialog-title">选择视频帧</AlertDialog.Title>
          <AlertDialog.Description className="alert-dialog-description">
            从当前动作视频中管理一组帧；正式生成会按当前队列顺序自动计算行列并打包。
          </AlertDialog.Description>
          <div className="frame-picker-body">
            <div className="frame-picker-video-panel">
              {sourceUrl ? (
                <div className="frame-picker-video-wrap" style={{ aspectRatio: videoSourceAspectRatio }}>
                  <video
                    className="frame-picker-video"
                    controls
                    crossOrigin="anonymous"
                    onLoadedMetadata={(event) => {
                      const sourceWidth = event.currentTarget.videoWidth || 0;
                      const sourceHeight = event.currentTarget.videoHeight || 0;
                      setVideoSourceAspectRatio(sourceWidth > 0 && sourceHeight > 0 ? `${sourceWidth} / ${sourceHeight}` : "1 / 1");
                      const duration = event.currentTarget.duration || 0;
                      setVideoPickerDuration(duration);
                      setVideoPickerCurrentTime(event.currentTarget.currentTime || 0);
                      setVideoRangeStart((current) => clampVideoPickerTime(current, duration));
                      setVideoRangeEnd((current) => (current > 0 ? clampVideoPickerTime(current, duration) : duration));
                      const timesNeedingThumbnails = videoFrameSelections.filter((selection) => !selection.thumbnail).map((selection) => selection.time);
                      if (timesNeedingThumbnails.length > 0) {
                        hydrateVideoFrameSelectionThumbnails(timesNeedingThumbnails).catch(() => undefined);
                      }
                    }}
                    onPlay={clearVideoSelectionPreview}
                    onTimeUpdate={(event) => setVideoPickerCurrentTime(event.currentTarget.currentTime || 0)}
                    ref={videoFramePickerRef}
                    src={sourceUrl}
                  />
                  {previewFrameActive ? (
                    <div className="frame-picker-preview-overlay">
                      <div className="frame-picker-preview-stage" ref={videoPreviewStageRef}>
                        <img
                          alt="当前选帧预览"
                          onLoad={(event) =>
                            setVideoPreviewNaturalSize({
                              width: event.currentTarget.naturalWidth,
                              height: event.currentTarget.naturalHeight
                            })
                          }
                          src={previewFrame?.thumbnail}
                          style={previewImageStyle}
                        />
                      </div>
                      <div className="frame-picker-playback-status">
                        <span>
                          #{(videoSelectionPreviewIndex ?? 0) + 1} / {previewSequenceLength} · {formatVideoTime(previewFrame?.time ?? 0)}
                        </span>
                        <div className="frame-picker-playback-track" aria-hidden="true">
                          <div style={{ width: `${previewProgressPercent}%` }} />
                        </div>
                      </div>
                    </div>
                  ) : null}
                </div>
              ) : (
                <div className="preview-object">
                  <strong>没有视频源</strong>
                  <span>先生成动作视频或填写视频路径。</span>
                </div>
              )}
              <div className="video-range-control">
                <div className="video-range-meta">
                  <span>取帧区间</span>
                  <b>{formatVideoTime(rangeStart)} - {formatVideoTime(rangeEnd)}</b>
                </div>
                <div className="video-range-track-wrap">
                  <div className="video-range-track" />
                  <div
                    className="video-range-fill"
                    style={{ left: `${rangeStartPercent}%`, width: `${Math.max(0, rangeEndPercent - rangeStartPercent)}%` }}
                  />
                  <input
                    aria-label="取帧区间起点"
                    className="video-range-input video-range-input-start"
                    disabled={!sourceUrl || rangeDuration <= 0}
                    max={rangeDuration || 0}
                    min={0}
                    onChange={(event) => updateVideoRangeStart(Number(event.currentTarget.value))}
                    step={0.001}
                    type="range"
                    value={clampVideoPickerTime(rangeStart, rangeDuration)}
                  />
                  <input
                    aria-label="取帧区间终点"
                    className="video-range-input video-range-input-end"
                    disabled={!sourceUrl || rangeDuration <= 0}
                    max={rangeDuration || 0}
                    min={0}
                    onChange={(event) => updateVideoRangeEnd(Number(event.currentTarget.value))}
                    step={0.001}
                    type="range"
                    value={clampVideoPickerTime(rangeEnd, rangeDuration)}
                  />
                </div>
              </div>
              <div className="frame-picker-controls">
                <span>{formatVideoTime(videoPickerCurrentTime)} / {formatVideoTime(videoPickerDuration)}</span>
                <button className="secondary-action icon-action" onClick={() => stepVideoFrame(-1)} disabled={!sourceUrl} title="前一帧" type="button">
                  <SkipBack size={15} />
                </button>
                <button className="secondary-action icon-action" onClick={() => stepVideoFrame(1)} disabled={!sourceUrl} title="后一帧" type="button">
                  <SkipForward size={15} />
                </button>
                <button className="secondary-action" onClick={addCurrentVideoFrame} disabled={!sourceUrl} type="button">
                  加入当前帧
                </button>
                <label className="frame-fps-field">
                  <span>FPS</span>
                  <input
                    max={60}
                    min={1}
                    onChange={(event) => setVideoAutoFps(Math.max(1, Math.min(60, Number(event.currentTarget.value) || 1)))}
                    type="number"
                    value={videoAutoFps}
                  />
                </label>
                <button className="secondary-action" onClick={() => autoSelectVideoFramesByFps().catch((error) => pushLog(error.message))} disabled={!sourceUrl || !videoPickerDuration || videoFrameThumbnailsLoading} type="button">
                  {videoFrameThumbnailsLoading ? "取帧中" : "按 FPS 取帧"}
                </button>
                <button className="secondary-action" onClick={playVideoSelectionPreview} disabled={!sourceUrl || videoFrameSelections.length === 0} type="button">
                  <Play size={15} />
                  {videoSelectionPreviewing ? "停止所有帧" : "播放所有帧"}
                </button>
                <button className="secondary-action" onClick={playVideoLoopPreview} disabled={!sourceUrl || !loopFrame} type="button">
                  <Play size={15} />
                  {videoLoopPreviewing ? "停止循环段" : "播放至循环帧"}
                </button>
                <button
                  className="secondary-action"
                  onClick={() => {
                    clearVideoSelectionPreview();
                    setSelectedLoopFrameId(null);
                    setVideoFrameSelections([]);
                  }}
                  disabled={videoFrameSelections.length === 0}
                  type="button"
                >
                  清空
                </button>
              </div>
            </div>
            <div className="frame-queue-panel">
              <div className="frame-queue-header">
                <div>
                  <strong>帧队列</strong>
                  <span>
                    {videoFrameSelections.length} 帧{videoFrameSelections.length > 0 ? `，生成 ${queueLayout.columns}x${queueLayout.rows}` : ""}
                    {selectedQueueCount > 0 ? `，已选 ${selectedQueueCount}` : ""}
                    {loopCandidates.length > 0 ? `，循环候选 ${loopCandidates.length} 个` : ""}
                    {loopFrame ? `，当前终点 ${formatVideoTime(loopFrame.time)}` : ""}
                  </span>
                </div>
                <b className={queueReady ? "ready" : ""}>
                  {queueReady ? "可生成" : "待选帧"}
                </b>
              </div>
              <label className="frame-loop-threshold">
                <span>循环相似度</span>
                <input
                  max={0.99}
                  min={0.7}
                  onChange={(event) => setVideoLoopMinScore(Math.max(0.7, Math.min(0.99, Number(event.currentTarget.value) || DEFAULT_VIDEO_LOOP_MIN_SCORE)))}
                  step={0.01}
                  type="range"
                  value={videoLoopMinScore}
                />
                <b>{videoLoopMinScore.toFixed(2)}</b>
              </label>
              <div className="frame-queue-actions">
                <button className="secondary-action" onClick={() => setAllVideoFrameSelections(true)} disabled={videoFrameSelections.length === 0} type="button">
                  全选
                </button>
                <button className="secondary-action" onClick={() => setAllVideoFrameSelections(false)} disabled={selectedQueueCount === 0} type="button">
                  取消选择
                </button>
                <button className="secondary-action" onClick={removeSelectedVideoFrames} disabled={selectedQueueCount === 0} type="button">
                  删除选中
                </button>
                <button className="secondary-action" onClick={findVideoLoopFrame} disabled={videoFrameSelections.length < 3} type="button">
                  寻找循环帧
                </button>
                <button className="secondary-action" onClick={trimVideoFramesToLoopPoint} disabled={!loopFrame} type="button">
                  删除终点及后帧
                </button>
              </div>
              <div className="frame-queue-export-actions">
                <button className="secondary-action" onClick={() => exportVideoFrameQueue("png_sequence")} disabled={videoFrameSelections.length === 0} type="button">
                  导出 PNG
                </button>
                <button className="secondary-action" onClick={() => exportVideoFrameQueue("gif")} disabled={videoFrameSelections.length === 0} type="button">
                  导出 GIF
                </button>
                <button className="secondary-action" onClick={() => exportVideoFrameQueue("sheet")} disabled={videoFrameSelections.length === 0} type="button">
                  导出 Sheet
                </button>
              </div>
              <div className="frame-selection-grid" style={{ gridTemplateColumns: `repeat(${Math.min(Math.max(queueLayout.columns, 2), 5)}, minmax(0, 1fr))` }}>
                {videoFrameSelections.map((selection, index) => (
                  <button
                    className={`frame-selection-tile filled ${selection.selected ? "selected" : ""} ${selection.loopHint ? "loop" : ""} ${selection.id === selectedLoopFrameId ? "loop-selected" : ""} ${videoSelectionPreviewIndex === index ? "previewing" : ""}`}
                    draggable
                    key={selection.id}
                    onClick={() => handleVideoFrameTileClick(index)}
                    onDragOver={(event) => event.preventDefault()}
                    onDragStart={(event) => handleVideoFrameDragStart(event, index)}
                    onDrop={(event) => handleVideoFrameDrop(event, index)}
                    type="button"
                  >
                    <span>#{index + 1}</span>
                    {selection.loopHint && <em>{selection.id === selectedLoopFrameId ? "终点" : "候选"} {selection.loopScore ? selection.loopScore.toFixed(2) : ""}</em>}
                    {selection.thumbnail ? (
                      <img src={selection.thumbnail} alt={`队列第 ${index + 1} 帧预览`} />
                    ) : (
                      <b className="thumbnail-pending">{formatVideoTime(selection.time)}</b>
                    )}
                    <div className="frame-tile-actions">
                      <i
                        onClick={(event) => {
                          event.stopPropagation();
                          seekVideoFrameSelection(selection.time);
                        }}
                      >
                        定位
                      </i>
                      <i
                        onClick={(event) => {
                          event.stopPropagation();
                          removeVideoFrameSelection(index);
                        }}
                      >
                        移除
                      </i>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          </div>
          <div className="alert-dialog-actions">
            <AlertDialog.Cancel className="dialog-button secondary">关闭</AlertDialog.Cancel>
            <AlertDialog.Action className="dialog-button" disabled={!queueReady}>
              使用选帧
            </AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}

export default function AppDialogs() {
  return (
    <>
      <DeleteConfirmDialog />
      <GameUiSkinPreviewDialog />
      <GameUiClearTextureKitDialog />
      <VideoFramePickerDialog />
    </>
  );
}
