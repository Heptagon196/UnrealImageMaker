// @ts-nocheck
import React from "react";
import { Database, FileJson } from "lucide-react";
import { useAppContext } from "../AppContext";

export default function RightPanel() {
  const {
    activeStreamSession,
    assets,
    busy,
    cancelActiveTask,
    cancelRequested,
    consoleOutputRef,
    handleConsoleScroll,
    installedCount,
    issueCount,
    log,
    RailContext,
    taskProgress
  } = useAppContext();

  return (
    <aside className="right-rail" aria-label="工作台概览与日志">
      <section className="side-panel">
        <div className="section-header">
          <div>
            <div className="section-kicker">概览</div>
            <strong>当前工作台</strong>
          </div>
          <Database size={17} />
        </div>
        <div className="rail-metrics">
          <span>
            <strong>{assets.length}</strong>
            <small>资产</small>
          </span>
          <span>
            <strong>{installedCount}</strong>
            <small>模型</small>
          </span>
          <span>
            <strong>{issueCount}</strong>
            <small>问题</small>
          </span>
        </div>
        <div className="rail-context">
          <div className="section-kicker">上下文</div>
          <RailContext />
        </div>
      </section>

      <section className="side-panel console-panel" aria-live="polite">
        <div className="section-header">
          <div>
            <div className="section-kicker">日志</div>
            <strong>{busy ? `执行中：${busy}` : "任务日志"}</strong>
          </div>
          {busy && activeStreamSession ? (
            <button className="secondary-action compact" onClick={cancelActiveTask} disabled={cancelRequested} type="button">
              {cancelRequested ? "中断中" : "中断任务"}
            </button>
          ) : (
            <FileJson size={16} />
          )}
        </div>
        {busy && taskProgress ? (
          <div className="task-progress" role="progressbar" aria-valuemin={0} aria-valuemax={taskProgress.total} aria-valuenow={taskProgress.current}>
            <div className="task-progress-meta">
              <span>{taskProgress.label}</span>
              <strong>{Math.round((taskProgress.current / taskProgress.total) * 100)}%</strong>
            </div>
            <div className="task-progress-track">
              <div style={{ width: `${Math.max(2, Math.min(100, (taskProgress.current / taskProgress.total) * 100))}%` }} />
            </div>
          </div>
        ) : null}
        <div className="console-output" ref={consoleOutputRef} onScroll={handleConsoleScroll} role="log">
          {log.length === 0 ? (
            <div className="console-line muted">等待操作</div>
          ) : (
            log.map((item, index) => (
              <div className="console-line" key={`${item}-${index}`}>
                <span className="console-prefix">{String(index + 1).padStart(2, "0")}</span>
                <span>{item}</span>
              </div>
            ))
          )}
        </div>
      </section>
    </aside>
  );
}
