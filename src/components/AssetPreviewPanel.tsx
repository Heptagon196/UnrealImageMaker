// @ts-nocheck
import React from "react";
import { PhotoProvider, PhotoView } from "react-photo-view";
import { Tree } from "react-arborist";
import { FileImage, Folder, FolderOpen, Sparkles } from "lucide-react";
import "react-photo-view/dist/react-photo-view.css";
import { useAppContext } from "../AppContext";

function ImageVersionTreeRow({ node, style }) {
  const {
    activeAssetName,
    activePreviewPath,
    activePreviewVersionId,
    selectedAsset,
    setActivePreviewLabel,
    setActivePreviewPath,
    setActivePreviewVersionId,
    setPendingDelete,
    versionDisplayLabel
  } = useAppContext();
  const data = node.data;
  const isActive = Boolean(data.version && (data.version.id === activePreviewVersionId || data.version.path === activePreviewPath));
  const handleOpen = () => {
    if (data.kind === "folder") {
      node.toggle();
      return;
    }
    if (data.kind === "file" && data.version) {
      setActivePreviewVersionId(data.version.id);
      setActivePreviewPath(data.version.path);
      setActivePreviewLabel(`${selectedAsset?.name || activeAssetName} / ${versionDisplayLabel(data.version)}`);
    }
  };

  return (
    <div
      className={`image-tree-row ${data.kind} ${isActive ? "active" : ""}`}
      onClick={handleOpen}
      onContextMenu={(event) => {
        if (!data.version) return;
        event.preventDefault();
        setPendingDelete({ kind: "version", version: data.version });
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          handleOpen();
        }
      }}
      role="treeitem"
      style={{ ...style, paddingLeft: `${12 + node.level * 14}px` }}
      tabIndex={0}
    >
      <span className="image-tree-icon" aria-hidden="true">
        {data.kind === "folder" ? node.isOpen ? <FolderOpen size={16} /> : <Folder size={16} /> : <FileImage size={15} />}
      </span>
      <span className="image-tree-main">
        <span className="image-tree-name">
          {data.name}
          {data.kind === "folder" && <em>{data.count ?? 0}</em>}
        </span>
        {data.kind === "file" && (
          <span className="image-tree-meta">
            {data.roleLabel}
            {data.dateLabel ? ` · ${data.dateLabel}` : ""}
          </span>
        )}
      </span>
    </div>
  );
}

function ImageVersionBrowser() {
  const { currentImageBrowserTree, previewHeight, selectedAsset, activePreviewVersionId } = useAppContext();
  const { title, data } = currentImageBrowserTree();
  const treeHeight = Math.max(160, previewHeight - 72);
  const inputCount = data[0]?.count ?? 0;
  const outputCount = data[1]?.count ?? 0;

  return (
    <aside className="image-version-browser" aria-label="当前工序图片树">
      <div className="image-browser-header">
        <div>
          <span>当前工序</span>
          <strong>{title}</strong>
        </div>
        <small>
          输入 {inputCount} / 输出 {outputCount}
        </small>
      </div>
      {selectedAsset ? (
        <Tree
          aria-label="当前工序输入输出图片"
          className="image-tree"
          data={data}
          disableDrag
          disableDrop
          disableEdit
          disableMultiSelection
          height={treeHeight}
          indent={14}
          openByDefault
          rowHeight={36}
          selection={activePreviewVersionId ? `output:${activePreviewVersionId}` : undefined}
          width="100%"
        >
          {ImageVersionTreeRow}
        </Tree>
      ) : (
        <div className="image-tree-empty">
          <FileImage size={22} />
          <span>先在左侧选择或创建当前资产</span>
        </div>
      )}
    </aside>
  );
}

export default function AssetPreviewPanel(options = {}) {
  const {
    currentManifest,
    endPreviewResize,
    lastResult,
    movePreviewResize,
    previewHeight,
    previewName,
    previewPath,
    previewUrlForPath,
    project,
    projectRoot,
    selectedAsset,
    startPreviewResize
  } = useAppContext();
  const displayPreviewPath = options.overridePath || previewPath;
  const displayPreviewName = options.overrideName || previewName;
  const displayPreviewUrl = previewUrlForPath(projectRoot, displayPreviewPath);

  return (
    <PhotoProvider maskOpacity={0.88}>
      <section className="preview-panel" aria-label="资产预览" style={{ height: previewHeight }}>
        <div className="preview-browser-layout">
          <ImageVersionBrowser />
          <div className="checkerboard">
            {displayPreviewPath && displayPreviewUrl ? (
              <PhotoView src={displayPreviewUrl}>
                <button className="preview-image-button" type="button" aria-label="放大查看当前图片">
                  <img className="preview-image" src={displayPreviewUrl} alt={displayPreviewName || "资产预览"} />
                </button>
              </PhotoView>
            ) : (
              <div className="preview-object">
                {displayPreviewPath ? (
                  <FileImage size={44} />
                ) : (
                  <>
                    <Sparkles size={44} />
                    <strong>选择工序开始生产</strong>
                    <span>生成结果会显示在这里，可拖动下边界调整预览高度。</span>
                  </>
                )}
              </div>
            )}
          </div>
        </div>
        <div
          className="preview-resize-handle"
          onPointerDown={startPreviewResize}
          onPointerMove={movePreviewResize}
          onPointerUp={endPreviewResize}
          onPointerCancel={endPreviewResize}
          role="separator"
          aria-label="拖动调整图片显示器高度"
        >
          <span />
        </div>
        <div className="pipeline-bar">
          <span className={project ? "done" : ""}>项目</span>
          <span className={selectedAsset ? "done" : ""}>资产</span>
          <span className={currentManifest ? "done" : ""}>清单</span>
          <span className={lastResult ? "done" : ""}>结果</span>
        </div>
      </section>
    </PhotoProvider>
  );
}
