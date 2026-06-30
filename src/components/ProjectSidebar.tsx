// @ts-nocheck
import React from "react";
import { Tree } from "react-arborist";
import { Database, FileImage, Folder, FolderOpen, FolderPlus, History, Wand2, X } from "lucide-react";
import { useAppContext } from "../AppContext";

function AssetTreeRow({ node, style }) {
  const {
    assetTypeLabel,
    latestAssetThumbnailPath,
    previewUrlForPath,
    projectRoot,
    selectAssetFromTree,
    selectedAsset,
    setPendingDelete
  } = useAppContext();
  const data = node.data;
  const isActive = data.asset?.id === selectedAsset?.id;
  const thumbnailPath = data.asset ? latestAssetThumbnailPath(data.asset) : "";
  const thumbnailUrl = thumbnailPath ? previewUrlForPath(projectRoot, thumbnailPath) : "";
  const handleOpen = () => {
    if (data.kind === "group") {
      node.toggle();
      return;
    }
    if (data.asset) selectAssetFromTree(data.asset);
  };
  const handlePointerDown = (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    handleOpen();
  };

  return (
    <div
      className={`asset-tree-row ${data.kind} ${isActive ? "active" : ""}`}
      aria-selected={isActive}
      onContextMenu={(event) => {
        if (!data.asset) return;
        event.preventDefault();
        setPendingDelete({ kind: "asset", asset: data.asset });
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          handleOpen();
        }
      }}
      onPointerDown={handlePointerDown}
      role="treeitem"
      style={{ ...style, paddingLeft: `${8 + node.level * 14}px` }}
      tabIndex={0}
    >
      <span className="asset-tree-icon" aria-hidden="true">
        {data.kind === "group" ? (
          node.isOpen ? <FolderOpen size={15} /> : <Folder size={15} />
        ) : thumbnailUrl ? (
          <img src={thumbnailUrl} alt="" />
        ) : (
          <FileImage size={14} />
        )}
      </span>
      <span className="asset-tree-main">
        <span className="asset-tree-name">{data.name}</span>
        {data.kind === "asset" && data.asset && <span className="asset-tree-meta">{assetTypeLabel(data.asset.type)}</span>}
      </span>
    </div>
  );
}

export default function ProjectSidebar() {
  const {
    assetTreeData,
    assetTreeSelectionId,
    backend,
    busy,
    chooseAndCreateProject,
    chooseAndOpenProject,
    createProject,
    disconnectProject,
    forgetRecentProject,
    formatRecentProjectTime,
    openProject,
    project,
    projectName,
    projectNameFromRoot,
    projectPanelMode,
    projectRoot,
    recentProjects,
    selectedAsset,
    setProjectName,
    setProjectPanelMode,
    workerBlocked
  } = useAppContext();
  const hasOpenProject = Boolean(project?.project.id);
  const currentProjectName = hasOpenProject ? project?.project.name || projectName || projectNameFromRoot(projectRoot) : "未打开项目";
  const currentProjectPathLabel = hasOpenProject ? projectRoot : "选择文件夹后打开或创建项目";
  const projectStatusLabel = backend === "online" ? "已连接" : backend === "checking" ? "连接中" : "离线";
  const visibleRecentProjects = recentProjects.slice(0, 4);
  const projectOperationDisabled = backend === "checking" || busy !== null;

  return (
    <aside className="left-rail" aria-label="项目与资产">
      <div className="brand-row">
        <div className="product-mark">
          <div className="product-icon">
            <Wand2 size={20} />
          </div>
          <div>
            <h1>UnrealImageMaker</h1>
            <span>游戏贴图生产管线</span>
          </div>
        </div>
      </div>

      <section className="rail-section project-manager-section">
        <div className="project-current-card">
          <span className="project-current-icon">
            <Database size={17} />
          </span>
          <div className="project-current-main">
            <span className="section-kicker">当前项目</span>
            <strong>{currentProjectName}</strong>
            <small title={currentProjectPathLabel}>{currentProjectPathLabel}</small>
          </div>
          <span className={`project-status-pill ${backend}`}>{projectStatusLabel}</span>
        </div>

        <div className="project-mode-tabs" role="tablist" aria-label="项目操作">
          <button
            className={projectPanelMode === "open" ? "active" : ""}
            onClick={() => setProjectPanelMode("open")}
            type="button"
            aria-selected={projectPanelMode === "open"}
          >
            <FolderOpen size={14} />
            打开
          </button>
          <button
            className={projectPanelMode === "create" ? "active" : ""}
            onClick={() => setProjectPanelMode("create")}
            type="button"
            aria-selected={projectPanelMode === "create"}
          >
            <FolderPlus size={14} />
            创建
          </button>
        </div>

        <div className="project-form">
          <label className="field compact">
            <span>{projectPanelMode === "create" ? "新项目目录" : "项目目录"}</span>
            <div className="project-folder-picker">
              <input value={projectRoot || "未选择文件夹"} readOnly title={projectRoot} />
            </div>
          </label>
          {projectPanelMode === "create" && (
            <label className="field compact">
              <span>项目名</span>
              <input
                value={projectName}
                onChange={(event) => setProjectName(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    void createProject();
                  }
                }}
                placeholder={projectNameFromRoot(projectRoot)}
              />
            </label>
          )}
        </div>

        <div className="button-row project-submit-row">
          {projectPanelMode === "create" ? (
            <button className="primary-action" onClick={chooseAndCreateProject} disabled={projectOperationDisabled} type="button">
              <FolderPlus size={15} />
              创建
            </button>
          ) : (
            <button className="primary-action" onClick={chooseAndOpenProject} disabled={projectOperationDisabled} type="button">
              <FolderOpen size={15} />
              打开
            </button>
          )}
          <button className="secondary-action" onClick={disconnectProject} disabled={!hasOpenProject || busy !== null} type="button">
            <X size={14} />
            断开
          </button>
        </div>

        {workerBlocked && (
          <div className="rail-warning">
            <span>本地服务未连接。打开或创建项目时会自动尝试启动后端。</span>
          </div>
        )}

        {!hasOpenProject && (
          <div className="recent-projects">
            <div className="recent-project-header">
              <span>
                <History size={13} />
                最近打开
              </span>
              {recentProjects.length > visibleRecentProjects.length && <small>显示最近 {visibleRecentProjects.length} 个</small>}
            </div>
            {visibleRecentProjects.length > 0 ? (
              <div className="recent-project-list">
                {visibleRecentProjects.map((item) => (
                  <div className="recent-project-row" key={item.root}>
                    <button className="recent-project-main" onClick={() => openProject(item.root, item.name)} disabled={projectOperationDisabled} type="button">
                      <strong>{item.name || projectNameFromRoot(item.root)}</strong>
                      <small title={item.root}>{item.root}</small>
                      <em>{formatRecentProjectTime(item.lastOpenedAt)}</em>
                    </button>
                    <button
                      className="icon-action compact-icon recent-project-remove"
                      onClick={() => forgetRecentProject(item.root)}
                      aria-label={`从最近项目移除 ${item.name}`}
                      type="button"
                    >
                      <X size={14} />
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <div className="recent-project-empty">创建或打开项目后会保留在这里。</div>
            )}
          </div>
        )}
      </section>

      {hasOpenProject && (
        <section className="rail-section current-asset-section">
          <div className="section-header">
            <div>
              <div className="section-kicker">当前资产</div>
              <strong>{selectedAsset?.name || "新资产"}</strong>
            </div>
            <FileImage size={18} />
          </div>
          {assetTreeData.length > 0 && (
            <Tree
              aria-label="已有资产树"
              className="asset-tree"
              data={assetTreeData}
              disableDrag
              disableDrop
              disableEdit
              disableMultiSelection
              height={Math.min(260, Math.max(128, assetTreeData.reduce((rows, group) => rows + 1 + (group.children?.length ?? 0), 0) * 34 + 8))}
              indent={14}
              openByDefault
              rowHeight={34}
              selection={assetTreeSelectionId}
              width="100%"
            >
              {AssetTreeRow}
            </Tree>
          )}
        </section>
      )}
    </aside>
  );
}
