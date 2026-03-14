import { useEffect, useState, useCallback, useRef } from 'react';
import { listComments, createComment } from '../../api/comments';
import type { Comment } from '../../api/comments';
import { usePipelineStore } from '../../store/pipelineStore';

interface CommentsPanelProps {
  projectId: string;
  artifactId: string;
  /** Compact mode for inline use inside ReviewPanel */
  compact?: boolean;
}

export function CommentsPanel({ projectId, artifactId, compact }: CommentsPanelProps) {
  const [comments, setComments] = useState<Comment[]>([]);
  const [loading, setLoading] = useState(true);
  const [newComment, setNewComment] = useState('');
  const [replyTo, setReplyTo] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [expandedThreads, setExpandedThreads] = useState<Set<string>>(new Set());
  const bottomRef = useRef<HTMLDivElement>(null);

  // Subscribe to WS events for live refresh
  const wsEvents = usePipelineStore((s) => s.lastWSEvent);

  const fetchComments = useCallback(async () => {
    try {
      const data = await listComments(projectId, artifactId);
      setComments(data);
    } catch (err) {
      console.error('[Comments] Failed to load:', err);
    } finally {
      setLoading(false);
    }
  }, [projectId, artifactId]);

  useEffect(() => {
    setLoading(true);
    fetchComments();
  }, [fetchComments]);

  // Refresh comments when comment_added WS event fires
  useEffect(() => {
    if (
      wsEvents &&
      wsEvents.type === 'comment_added' &&
      wsEvents.artifact_id === artifactId
    ) {
      fetchComments();
    }
  }, [wsEvents, artifactId, fetchComments]);

  const handleSubmit = async () => {
    if (!newComment.trim() || submitting) return;
    setSubmitting(true);
    try {
      await createComment(projectId, artifactId, newComment, replyTo ?? undefined);
      setNewComment('');
      setReplyTo(null);
      await fetchComments();
      // Scroll to bottom after posting
      setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' }), 100);
    } finally {
      setSubmitting(false);
    }
  };

  const toggleThread = (commentId: string) => {
    setExpandedThreads((prev) => {
      const next = new Set(prev);
      if (next.has(commentId)) next.delete(commentId);
      else next.add(commentId);
      return next;
    });
  };

  // Separate top-level comments and replies
  const topLevel = comments.filter((c) => !c.parent_id);
  const repliesByParent = new Map<string, Comment[]>();
  for (const c of comments) {
    if (c.parent_id) {
      const list = repliesByParent.get(c.parent_id) || [];
      list.push(c);
      repliesByParent.set(c.parent_id, list);
    }
  }

  const formatTime = (iso: string) => {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  if (loading) {
    return (
      <div className={`flex items-center justify-center ${compact ? 'py-4' : 'flex-1 py-8'} text-gray-500 text-sm`}>
        Loading comments...
      </div>
    );
  }

  return (
    <div className={`flex flex-col ${compact ? '' : 'flex-1'} overflow-hidden`}>
      {/* Comment list */}
      <div className={`overflow-auto ${compact ? 'max-h-48' : 'flex-1'} px-3 py-2 space-y-1`}>
        {topLevel.length === 0 && (
          <p className="text-gray-500 text-xs text-center py-4">No comments yet</p>
        )}
        {topLevel.map((comment) => {
          if (comment.comment_type === 'system_event') {
            return (
              <div key={comment.id} className="flex items-center gap-2 py-2">
                <div className="flex-1 h-px bg-gray-700" />
                <span className="text-xs text-gray-500 italic whitespace-nowrap">
                  {comment.content}
                  {comment.artifact_version != null && (
                    <span className="text-gray-600 ml-1">
                      (v{comment.artifact_version})
                    </span>
                  )}
                </span>
                <div className="flex-1 h-px bg-gray-700" />
              </div>
            );
          }

          if (comment.comment_type === 'feedback') {
            return (
              <div key={comment.id} className="border-l-2 border-orange-500/60 bg-orange-950/20 rounded-r px-3 py-2 my-1">
                <div className="flex items-baseline gap-2 mb-0.5">
                  <span className="text-xs font-medium text-orange-400">Feedback</span>
                  <span className="text-xs text-gray-400">
                    {comment.author?.username || 'Unknown'}
                  </span>
                  <span className="text-xs text-gray-600">
                    {formatTime(comment.created_at)}
                  </span>
                  {comment.artifact_version != null && (
                    <span className="text-xs text-gray-600">
                      v{comment.artifact_version}
                    </span>
                  )}
                </div>
                <p className="text-sm text-gray-300 whitespace-pre-wrap break-words">
                  {comment.content}
                </p>
              </div>
            );
          }

          const replies = repliesByParent.get(comment.id) || [];
          const isExpanded = expandedThreads.has(comment.id);

          return (
            <div key={comment.id} className="group">
              {/* Top-level comment */}
              <div className="flex gap-2 py-1.5">
                <div className="w-6 h-6 rounded-full bg-blue-900 text-blue-300 flex items-center justify-center text-xs font-medium shrink-0 mt-0.5">
                  {comment.author?.username?.[0]?.toUpperCase() || '?'}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-baseline gap-2">
                    <span className="text-xs font-medium text-gray-200">
                      {comment.author?.username || 'Unknown'}
                    </span>
                    <span className="text-xs text-gray-600">
                      {formatTime(comment.created_at)}
                    </span>
                    {comment.artifact_version != null && (
                      <span className="text-xs text-gray-600">
                        v{comment.artifact_version}
                      </span>
                    )}
                  </div>
                  <p className="text-sm text-gray-300 whitespace-pre-wrap break-words">
                    {comment.content}
                  </p>
                  <div className="flex items-center gap-3 mt-0.5">
                    <button
                      onClick={() => {
                        setReplyTo(replyTo === comment.id ? null : comment.id);
                      }}
                      className="text-xs text-gray-500 hover:text-blue-400"
                    >
                      Reply
                    </button>
                    {replies.length > 0 && (
                      <button
                        onClick={() => toggleThread(comment.id)}
                        className="text-xs text-gray-500 hover:text-blue-400"
                      >
                        {isExpanded
                          ? 'Hide replies'
                          : `${replies.length} ${replies.length === 1 ? 'reply' : 'replies'}`}
                      </button>
                    )}
                  </div>
                </div>
              </div>

              {/* Replies */}
              {isExpanded &&
                replies.map((reply) => (
                  <div key={reply.id} className="flex gap-2 py-1 ml-8 border-l border-gray-700 pl-3">
                    <div className="w-5 h-5 rounded-full bg-gray-700 text-gray-400 flex items-center justify-center text-xs font-medium shrink-0 mt-0.5">
                      {reply.author?.username?.[0]?.toUpperCase() || '?'}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-baseline gap-2">
                        <span className="text-xs font-medium text-gray-300">
                          {reply.author?.username || 'Unknown'}
                        </span>
                        <span className="text-xs text-gray-600">
                          {formatTime(reply.created_at)}
                        </span>
                      </div>
                      <p className="text-sm text-gray-400 whitespace-pre-wrap break-words">
                        {reply.content}
                      </p>
                    </div>
                  </div>
                ))}

              {/* Reply input (inline under the comment being replied to) */}
              {replyTo === comment.id && (
                <div className="ml-8 mt-1 flex gap-2">
                  <input
                    type="text"
                    value={newComment}
                    onChange={(e) => setNewComment(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        handleSubmit();
                      }
                    }}
                    placeholder={`Reply to ${comment.author?.username || 'comment'}...`}
                    className="flex-1 px-2 py-1 bg-gray-800 text-white text-sm rounded border border-gray-600 focus:border-blue-500 focus:outline-none"
                    autoFocus
                  />
                  <button
                    onClick={handleSubmit}
                    disabled={submitting || !newComment.trim()}
                    className="px-2 py-1 bg-blue-600 hover:bg-blue-700 text-white text-xs rounded disabled:opacity-50 whitespace-nowrap"
                  >
                    {submitting ? '...' : 'Reply'}
                  </button>
                  <button
                    onClick={() => {
                      setReplyTo(null);
                      setNewComment('');
                    }}
                    className="px-2 py-1 text-gray-400 hover:text-white text-xs"
                  >
                    Cancel
                  </button>
                </div>
              )}
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>

      {/* New comment input (top-level) — only show when not replying */}
      {!replyTo && (
        <div className="border-t border-gray-700 px-3 py-2 flex gap-2">
          <input
            type="text"
            value={newComment}
            onChange={(e) => setNewComment(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSubmit();
              }
            }}
            placeholder="Add a comment..."
            className="flex-1 px-2 py-1.5 bg-gray-800 text-white text-sm rounded border border-gray-600 focus:border-blue-500 focus:outline-none"
          />
          <button
            onClick={handleSubmit}
            disabled={submitting || !newComment.trim()}
            className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-xs rounded disabled:opacity-50"
          >
            {submitting ? '...' : 'Send'}
          </button>
        </div>
      )}
    </div>
  );
}
