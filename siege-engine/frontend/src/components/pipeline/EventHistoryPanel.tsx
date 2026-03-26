import { useState, useEffect, useCallback, useMemo } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import * as pipelineApi from '../../api/pipeline';
import { pipelineKeys } from '../../hooks/queries/usePipelineQueries';
import type { PipelineEvent, PipelineSnapshot } from '../../types/pipeline';
import { formatDateTimeSec } from '../../utils/dateFormat';

const EVENT_TYPE_COLORS: Record<string, string> = {
  run_created: 'bg-green-700',
  run_completed: 'bg-green-600',
  stage_started: 'bg-blue-600',
  stage_queued: 'bg-blue-800',
  generation_completed: 'bg-blue-500',
  ai_review_started: 'bg-purple-600',
  ai_review_completed: 'bg-purple-500',
  awaiting_human_review: 'bg-yellow-600',
  human_approved: 'bg-green-600',
  human_rejected: 'bg-red-600',
  feedback_saved: 'bg-orange-600',
  stage_failed: 'bg-red-700',
  stage_skipped: 'bg-gray-600',
  stage_retried: 'bg-orange-700',
  artifact_revised: 'bg-indigo-600',
  stale_resolved: 'bg-teal-600',
  staleness_propagated: 'bg-orange-700',
  artifact_pruned: 'bg-red-800',
  artifact_committed: 'bg-emerald-700',
  cascade_started: 'bg-cyan-700',
  cascade_completed: 'bg-cyan-600',
  carried_over: 'bg-gray-500',
  comment_added: 'bg-sky-600',
  generation_progress: 'bg-blue-400',
  pipeline_paused: 'bg-yellow-700',
  pipeline_resumed: 'bg-green-500',
  pipeline_reset: 'bg-red-900',
};

const ROUTINE_EVENTS = new Set([
  'stage_queued', 'stage_started', 'carried_over',
  'cascade_started', 'cascade_completed',
  'generation_progress', 'artifact_committed',
]);

const HIGHLIGHT_EVENTS = new Set([
  'human_approved', 'human_rejected', 'stage_failed',
  'staleness_propagated', 'pipeline_reset',
]);

function formatEventType(type: string): string {
  return type.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

const TRIGGER_LABELS: Record<string, string> = {
  pipeline_run: 'Pipeline Run',
  force_restart: 'Force Restart',
  rejection_regenerate: 'Rejection Regenerate',
  revision: 'Revision',
};

function formatPayload(
  payload: Record<string, unknown>,
  artifactNames: Record<string, string>,
): string {
  const parts: string[] = [];
  if (payload.trigger) parts.push(`via ${TRIGGER_LABELS[String(payload.trigger)] || payload.trigger}`);
  if (payload.stage_key) parts.push(`stage: ${payload.stage_key}`);
  if (payload.component_key) parts.push(`component: ${payload.component_key}`);
  if (payload.artifact_id) {
    const aid = String(payload.artifact_id);
    const name = payload.artifact_name as string || artifactNames[aid];
    parts.push(`artifact: ${name || aid.slice(0, 8)}`);
  }
  if (payload.action) parts.push(`action: ${payload.action}`);
  if (payload.status) parts.push(`status: ${payload.status}`);
  if (payload.version != null) parts.push(`v${payload.version}`);
  if (payload.retry_count != null && Number(payload.retry_count) > 0) parts.push(`retry #${payload.retry_count}`);
  if (payload.stale_ids) parts.push(`stale: ${(payload.stale_ids as string[]).length} artifacts`);
  if (payload.git_commit_sha) parts.push(`sha: ${String(payload.git_commit_sha).slice(0, 7)}`);
  if (payload.parent_run_id) parts.push(`parent: ${String(payload.parent_run_id).slice(0, 8)}`);
  if (payload.step) parts.push(`step: ${payload.step}`);
  if (payload.comment_type) parts.push(`type: ${payload.comment_type}`);
  if (parts.length === 0) return JSON.stringify(payload);
  return parts.join(' | ');
}

function formatError(payload: Record<string, unknown>): string | null {
  const err = payload.error;
  if (!err || (typeof err === 'string' && !err.trim())) return null;
  return String(err);
}

function formatTime(isoStr: string | null): string {
  if (!isoStr) return '';
  return formatDateTimeSec(isoStr);
}

interface Props {
  projectId: string;
}

interface RunGroup {
  runId: string | null;
  runNumber: number | null;
  events: PipelineEvent[];
}

export function EventHistoryPanel({ projectId }: Props) {
  const [events, setEvents] = useState<PipelineEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [offset, setOffset] = useState(0);
  const [filterRunId, setFilterRunId] = useState<string>('');
  const [filterEventType, setFilterEventType] = useState<string>('');
  const [selectedSeq, setSelectedSeq] = useState<number | null>(null);
  const [previewSnapshot, setPreviewSnapshot] = useState<PipelineSnapshot | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [reverting, setReverting] = useState(false);
  const [revertResult, setRevertResult] = useState<string | null>(null);
  const [compactMode, setCompactMode] = useState(true);
  const [collapsedRuns, setCollapsedRuns] = useState<Set<string>>(new Set());
  const [artifactNames, setArtifactNames] = useState<Record<string, string>>({});
  const [runNumbers, setRunNumbers] = useState<Record<string, number>>({});
  const queryClient = useQueryClient();

  const PAGE_SIZE = 50;

  const loadEvents = useCallback(async () => {
    setLoading(true);
    try {
      const result = await pipelineApi.listEvents(projectId, {
        run_id: filterRunId || undefined,
        event_type: filterEventType || undefined,
        limit: PAGE_SIZE,
        offset,
      });
      setEvents(result.events);
      setTotal(result.total);
      setArtifactNames((prev) => ({ ...prev, ...result.artifact_names }));
      setRunNumbers((prev) => ({ ...prev, ...result.run_numbers }));
    } catch (err) {
      console.error('Failed to load events:', err);
    } finally {
      setLoading(false);
    }
  }, [projectId, filterRunId, filterEventType, offset]);

  useEffect(() => {
    loadEvents();
  }, [loadEvents]);

  // Reset offset when filters change
  useEffect(() => {
    setOffset(0);
  }, [filterRunId, filterEventType]);

  // Group events by run
  const runGroups = useMemo<RunGroup[]>(() => {
    const groupMap = new Map<string, PipelineEvent[]>();
    const order: string[] = [];

    for (const event of events) {
      const key = event.run_id || '__ungrouped__';
      if (!groupMap.has(key)) {
        groupMap.set(key, []);
        order.push(key);
      }
      groupMap.get(key)!.push(event);
    }

    return order.map((key) => ({
      runId: key === '__ungrouped__' ? null : key,
      runNumber: key === '__ungrouped__' ? null : (runNumbers[key] ?? null),
      events: groupMap.get(key)!,
    }));
  }, [events, runNumbers]);

  // Filter events in compact mode
  const filterEvents = useCallback((evts: PipelineEvent[]) => {
    if (!compactMode) return evts;
    return evts.filter((e) => !ROUTINE_EVENTS.has(e.event_type));
  }, [compactMode]);

  const toggleRunCollapsed = (runId: string) => {
    setCollapsedRuns((prev) => {
      const next = new Set(prev);
      if (next.has(runId)) {
        next.delete(runId);
      } else {
        next.add(runId);
      }
      return next;
    });
  };

  const handlePreview = async (seq: number) => {
    if (selectedSeq === seq) {
      setSelectedSeq(null);
      setPreviewSnapshot(null);
      return;
    }
    setSelectedSeq(seq);
    setPreviewLoading(true);
    try {
      const snapshot = await pipelineApi.getSnapshotAtSequence(projectId, seq);
      setPreviewSnapshot(snapshot);
    } catch (err) {
      console.error('Failed to load snapshot:', err);
      setPreviewSnapshot(null);
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleRevert = async (seq: number) => {
    if (!window.confirm(
      `Revert pipeline to sequence #${seq}?\n\nThis will restore all documents to their state at this point. Events, artifacts, and runs created after this point will be permanently deleted.`
    )) return;

    setReverting(true);
    setRevertResult(null);
    try {
      const result = await pipelineApi.revertToSequence(projectId, seq);
      const parts = [`Reverted to #${seq}`];
      parts.push(`${result.events_deleted} events deleted`);
      if (result.artifacts_restored > 0) parts.push(`${result.artifacts_restored} artifacts restored`);
      if (result.artifacts_deleted > 0) parts.push(`${result.artifacts_deleted} artifacts removed`);
      setRevertResult(parts.join(' — '));
      // Refresh everything
      loadEvents();
      queryClient.invalidateQueries({ queryKey: pipelineKeys.status(projectId) });
      queryClient.invalidateQueries({ queryKey: pipelineKeys.runs(projectId) });
      setSelectedSeq(null);
      setPreviewSnapshot(null);
    } catch (err) {
      console.error('Revert failed:', err);
      setRevertResult('Revert failed');
    } finally {
      setReverting(false);
    }
  };

  // Collect unique run_ids from events for the filter dropdown
  const uniqueRunIds = Array.from(new Set(events.map((e) => e.run_id).filter(Boolean))) as string[];

  const totalPages = Math.ceil(total / PAGE_SIZE);
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header & Filters */}
      <div className="shrink-0 p-4 border-b border-gray-700 space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold text-white">Event History</h2>
          <div className="flex items-center gap-2">
            <label className="flex items-center gap-1.5 text-xs text-gray-400 cursor-pointer">
              <input
                type="checkbox"
                checked={compactMode}
                onChange={(e) => setCompactMode(e.target.checked)}
                className="w-3.5 h-3.5 rounded border-gray-600 bg-gray-700 text-blue-500 focus:ring-blue-500 focus:ring-offset-gray-900"
              />
              Compact
            </label>
            <button
              onClick={loadEvents}
              disabled={loading}
              className="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-white text-xs rounded disabled:opacity-50"
            >
              {loading ? 'Loading...' : 'Refresh'}
            </button>
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          <select
            value={filterRunId}
            onChange={(e) => setFilterRunId(e.target.value)}
            className="px-2 py-1 bg-gray-700 text-white text-xs rounded border border-gray-600 focus:border-blue-500 focus:outline-none"
          >
            <option value="">All runs</option>
            {uniqueRunIds.map((rid) => (
              <option key={rid} value={rid}>
                Run #{runNumbers[rid] ?? rid.slice(0, 8)}
              </option>
            ))}
          </select>

          <select
            value={filterEventType}
            onChange={(e) => setFilterEventType(e.target.value)}
            className="px-2 py-1 bg-gray-700 text-white text-xs rounded border border-gray-600 focus:border-blue-500 focus:outline-none"
          >
            <option value="">All event types</option>
            {Object.keys(EVENT_TYPE_COLORS).map((t) => (
              <option key={t} value={t}>
                {formatEventType(t)}
              </option>
            ))}
          </select>

          <span className="text-xs text-gray-400 self-center">
            {total} events total
          </span>
        </div>

        {revertResult && (
          <div className={`text-xs px-2 py-1 rounded ${revertResult.startsWith('Reverted') ? 'bg-green-900/50 text-green-300' : 'bg-red-900/50 text-red-300'}`}>
            {revertResult}
          </div>
        )}
      </div>

      {/* Event List & Preview side by side */}
      <div className="flex-1 flex overflow-hidden">
        {/* Event timeline */}
        <div className={`${previewSnapshot ? 'w-1/2 border-r border-gray-700' : 'w-full'} overflow-auto`}>
          {events.length === 0 && !loading && (
            <p className="p-4 text-gray-500 text-sm">No events found.</p>
          )}

          <div className="divide-y divide-gray-800">
            {runGroups.map((group) => {
              const groupKey = group.runId || '__ungrouped__';
              const isCollapsed = collapsedRuns.has(groupKey);
              const filteredEvents = filterEvents(group.events);
              const hiddenCount = group.events.length - filteredEvents.length;

              return (
                <div key={groupKey}>
                  {/* Run group header */}
                  <div
                    className="px-4 py-2 bg-gray-800/80 border-b border-gray-700 cursor-pointer hover:bg-gray-800 flex items-center gap-2"
                    onClick={() => toggleRunCollapsed(groupKey)}
                  >
                    <svg
                      className={`w-3 h-3 text-gray-400 transition-transform ${isCollapsed ? '' : 'rotate-90'}`}
                      fill="none" stroke="currentColor" viewBox="0 0 24 24"
                    >
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                    </svg>
                    <span className="text-xs font-semibold text-gray-300">
                      {group.runNumber != null ? `Run #${group.runNumber}` : group.runId ? `Run ${group.runId.slice(0, 8)}` : 'System Events'}
                    </span>
                    <span className="text-xs text-gray-500">
                      {filteredEvents.length} event{filteredEvents.length !== 1 ? 's' : ''}
                      {hiddenCount > 0 && ` (+${hiddenCount} routine)`}
                    </span>
                  </div>

                  {/* Events within group */}
                  {!isCollapsed && filteredEvents.map((event) => {
                    const isHighlight = HIGHLIGHT_EVENTS.has(event.event_type);
                    return (
                      <div
                        key={event.id}
                        className={`px-4 py-2 hover:bg-gray-800/50 cursor-pointer transition-colors ${
                          selectedSeq === event.sequence ? 'bg-gray-800 ring-1 ring-blue-500' : ''
                        } ${isHighlight ? 'border-l-2 border-l-yellow-500' : ''}`}
                        onClick={() => handlePreview(event.sequence)}
                      >
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-xs text-gray-500 font-mono w-8 shrink-0 text-right">
                            #{event.sequence}
                          </span>
                          <span className={`text-xs text-white px-1.5 py-0.5 rounded ${EVENT_TYPE_COLORS[event.event_type] || 'bg-gray-600'}`}>
                            {formatEventType(event.event_type)}
                          </span>
                          <span className="text-xs text-gray-500 ml-auto">
                            {formatTime(event.created_at)}
                          </span>
                        </div>
                        <div className="text-xs text-gray-400 ml-10 truncate">
                          {formatPayload(event.payload, artifactNames)}
                        </div>
                        {formatError(event.payload) && (
                          <div className="text-xs text-red-400 ml-10 mt-0.5 truncate" title={formatError(event.payload)!}>
                            {formatError(event.payload)}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-2 p-3 border-t border-gray-700">
              <button
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                disabled={offset === 0}
                className="px-2 py-1 bg-gray-700 hover:bg-gray-600 text-white text-xs rounded disabled:opacity-30"
              >
                Prev
              </button>
              <span className="text-xs text-gray-400">
                Page {currentPage} of {totalPages}
              </span>
              <button
                onClick={() => setOffset(offset + PAGE_SIZE)}
                disabled={offset + PAGE_SIZE >= total}
                className="px-2 py-1 bg-gray-700 hover:bg-gray-600 text-white text-xs rounded disabled:opacity-30"
              >
                Next
              </button>
            </div>
          )}
        </div>

        {/* Snapshot preview */}
        {selectedSeq !== null && (
          <div className="w-1/2 overflow-auto p-4 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-white">
                Snapshot at #{selectedSeq}
              </h3>
              <button
                onClick={() => handleRevert(selectedSeq)}
                disabled={reverting}
                className="px-3 py-1.5 bg-red-600 hover:bg-red-700 text-white text-xs rounded disabled:opacity-50"
              >
                {reverting ? 'Reverting...' : 'Revert to this point'}
              </button>
            </div>

            {previewLoading ? (
              <p className="text-gray-400 text-sm animate-pulse">Loading snapshot...</p>
            ) : previewSnapshot ? (
              <div className="space-y-3">
                {/* Status flags */}
                <div className="flex flex-wrap gap-2">
                  <span className={`text-xs px-2 py-1 rounded ${previewSnapshot.is_running ? 'bg-blue-600 text-white' : 'bg-gray-700 text-gray-400'}`}>
                    {previewSnapshot.is_running ? 'Running' : 'Stopped'}
                  </span>
                  {previewSnapshot.is_paused && (
                    <span className="text-xs px-2 py-1 rounded bg-yellow-600 text-white">
                      Paused {previewSnapshot.paused_stage ? `at ${previewSnapshot.paused_stage}` : ''}
                    </span>
                  )}
                </div>

                {/* Run statuses */}
                {Object.keys(previewSnapshot.run_status).length > 0 && (
                  <div>
                    <h4 className="text-xs text-gray-400 mb-1 font-semibold">Runs</h4>
                    <div className="space-y-1">
                      {Object.entries(previewSnapshot.run_status).map(([runId, status]) => (
                        <div key={runId} className="flex items-center gap-2 text-xs">
                          <span className="text-gray-500 font-mono">
                            {runNumbers[runId] != null ? `#${runNumbers[runId]}` : runId.slice(0, 8)}
                          </span>
                          <span className={`px-1.5 py-0.5 rounded ${
                            status === 'running' ? 'bg-blue-600 text-white' :
                            status === 'completed' ? 'bg-green-700 text-white' :
                            'bg-gray-600 text-gray-300'
                          }`}>
                            {status}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Stage statuses */}
                {Object.keys(previewSnapshot.stage_statuses).length > 0 && (
                  <div>
                    <h4 className="text-xs text-gray-400 mb-1 font-semibold">Stages</h4>
                    <div className="space-y-1 max-h-40 overflow-auto">
                      {Object.entries(previewSnapshot.stage_statuses).map(([key, status]) => {
                        const stageError = previewSnapshot.stage_errors?.[key];
                        const trigger = previewSnapshot.stage_triggers?.[key];
                        return (
                          <div key={key}>
                            <div className="flex items-center gap-2 text-xs">
                              <span className="text-gray-300 font-mono truncate flex-1">{key}</span>
                              {trigger && (
                                <span className="text-gray-500 text-[10px]">
                                  {TRIGGER_LABELS[trigger] || trigger}
                                </span>
                              )}
                              <span className={`px-1.5 py-0.5 rounded shrink-0 ${
                                status === 'approved' ? 'bg-green-700 text-white' :
                                status === 'running' ? 'bg-blue-600 text-white' :
                                status === 'awaiting_review' ? 'bg-yellow-600 text-white' :
                                status === 'failed' ? 'bg-red-700 text-white' :
                                'bg-gray-600 text-gray-300'
                              }`}>
                                {status}
                              </span>
                            </div>
                            {stageError?.error && (
                              <div className="text-[10px] text-red-400 ml-2 truncate" title={stageError.error}>
                                {stageError.error}
                                {stageError.retry_count != null && stageError.retry_count > 0 && ` (retry #${stageError.retry_count})`}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                {/* Artifact statuses */}
                {Object.keys(previewSnapshot.artifact_statuses).length > 0 && (
                  <div>
                    <h4 className="text-xs text-gray-400 mb-1 font-semibold">Artifacts</h4>
                    <div className="space-y-1 max-h-40 overflow-auto">
                      {Object.entries(previewSnapshot.artifact_statuses).map(([aid, status]) => {
                        const version = previewSnapshot.artifact_versions?.[aid];
                        const comments = previewSnapshot.comment_counts?.[aid];
                        const meta = previewSnapshot.artifact_meta?.[aid];
                        const sha = previewSnapshot.artifact_git_shas?.[aid];
                        return (
                          <div key={aid} className="flex items-center gap-2 text-xs">
                            <span className="text-gray-300 truncate flex-1">
                              {meta?.name || artifactNames[aid] || aid.slice(0, 8)}
                            </span>
                            {version != null && (
                              <span className="text-gray-500 text-[10px]">v{version}</span>
                            )}
                            {comments != null && comments > 0 && (
                              <span className="text-sky-400 text-[10px]">{comments} comment{comments !== 1 ? 's' : ''}</span>
                            )}
                            {sha && (
                              <span className="text-gray-500 font-mono text-[10px]">{sha.slice(0, 7)}</span>
                            )}
                            <span className={`px-1.5 py-0.5 rounded shrink-0 ${
                              status === 'approved' ? 'bg-green-700 text-white' :
                              status === 'generating' ? 'bg-blue-600 text-white' :
                              status === 'awaiting_review' ? 'bg-yellow-600 text-white' :
                              status === 'pending' ? 'bg-gray-600 text-gray-300' :
                              'bg-gray-600 text-gray-300'
                            }`}>
                              {status}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <p className="text-gray-500 text-sm">No snapshot data.</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
