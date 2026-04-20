import { useState } from 'react';
import type { DragEndEvent } from '@dnd-kit/core';
import {
  DndContext,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
} from '@dnd-kit/core';

export interface MappingItem {
  id: string;
  name: string;
  subtitle?: string;
}

interface Props {
  sourceLabel: string;
  sourceItems: MappingItem[];
  targetLabel: string;
  targetItems: MappingItem[];
  /**
   * Map from target id to the list of source items currently
   * attached. Rendered as chips inside the target card; click a
   * chip's × to detach.
   */
  attachmentsByTarget: Record<string, MappingItem[]>;
  /** Called when the user drops a source onto a target. */
  onAttach: (sourceId: string, targetId: string) => void;
  /** Called when the user clicks a chip's detach button. */
  onDetach: (sourceId: string, targetId: string) => void;
  emptyMessage?: string;
}

/**
 * Shared drag-drop surface for Phase 11 mapping editors.
 *
 * - Desktop: drag a source card onto a target card to attach.
 * - Mobile: tap a source card to "pick up" (it glows), then tap
 *   the target card to drop. Same handler fires either way.
 *
 * Parent owns the instruction-emission logic — this component
 * only decides when attach / detach fire.
 */
export function TwoColumnMapping({
  sourceLabel,
  sourceItems,
  targetLabel,
  targetItems,
  attachmentsByTarget,
  onAttach,
  onDetach,
  emptyMessage,
}: Props) {
  const [pickedUpId, setPickedUpId] = useState<string | null>(null);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
  );

  const onDragEnd = (event: DragEndEvent) => {
    setPickedUpId(null);
    if (!event.over) return;
    onAttach(event.active.id as string, event.over.id as string);
  };

  const onTapPick = (id: string) =>
    setPickedUpId((cur) => (cur === id ? null : id));

  const onTapTarget = (targetId: string) => {
    if (pickedUpId == null) return;
    onAttach(pickedUpId, targetId);
    setPickedUpId(null);
  };

  return (
    <DndContext
      sensors={sensors}
      onDragStart={(e) => setPickedUpId(e.active.id as string)}
      onDragEnd={onDragEnd}
    >
      <div className="h-full w-full grid grid-cols-1 md:grid-cols-2 gap-4 p-4 overflow-auto">
        <section>
          <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400 mb-2">
            {sourceLabel} ({sourceItems.length})
          </h3>
          {sourceItems.length === 0 ? (
            <p className="text-sm text-gray-500 italic">
              {emptyMessage ?? 'Nothing yet.'}
            </p>
          ) : (
            <ul className="space-y-2">
              {sourceItems.map((item) => (
                <SourceCard
                  key={item.id}
                  item={item}
                  pickedUp={pickedUpId === item.id}
                  onTap={() => onTapPick(item.id)}
                />
              ))}
            </ul>
          )}
        </section>
        <section>
          <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400 mb-2">
            {targetLabel} ({targetItems.length})
          </h3>
          {targetItems.length === 0 ? (
            <p className="text-sm text-gray-500 italic">
              {emptyMessage ?? 'Nothing yet.'}
            </p>
          ) : (
            <ul className="space-y-2">
              {targetItems.map((item) => (
                <TargetCard
                  key={item.id}
                  item={item}
                  chips={attachmentsByTarget[item.id] ?? []}
                  activeTap={pickedUpId !== null}
                  onTap={() => onTapTarget(item.id)}
                  onDetach={(sid) => onDetach(sid, item.id)}
                />
              ))}
            </ul>
          )}
        </section>
      </div>
    </DndContext>
  );
}

function SourceCard({
  item,
  pickedUp,
  onTap,
}: {
  item: MappingItem;
  pickedUp: boolean;
  onTap: () => void;
}) {
  const { setNodeRef, listeners, attributes, isDragging } = useDraggable({
    id: item.id,
  });
  return (
    <li
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      onClick={onTap}
      className={`p-3 rounded border cursor-grab select-none ${
        isDragging || pickedUp
          ? 'border-amber-400 bg-amber-900/20 shadow-lg'
          : 'border-gray-700 bg-gray-800/70 hover:border-gray-500'
      }`}
    >
      <div className="font-medium text-gray-100 text-sm">{item.name}</div>
      {item.subtitle && (
        <div className="mt-0.5 text-xs text-gray-500">{item.subtitle}</div>
      )}
      <div className="mt-1 font-mono text-[10px] text-gray-600">{item.id}</div>
    </li>
  );
}

function TargetCard({
  item,
  chips,
  activeTap,
  onTap,
  onDetach,
}: {
  item: MappingItem;
  chips: MappingItem[];
  activeTap: boolean;
  onTap: () => void;
  onDetach: (sourceId: string) => void;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: item.id });
  return (
    <li
      ref={setNodeRef}
      onClick={activeTap ? onTap : undefined}
      className={`p-3 rounded border ${
        isOver
          ? 'border-emerald-400 bg-emerald-900/20'
          : activeTap
            ? 'border-amber-500/50 bg-gray-900/60 cursor-copy'
            : 'border-gray-700 bg-gray-900/60'
      }`}
    >
      <div className="font-medium text-gray-100 text-sm">{item.name}</div>
      {item.subtitle && (
        <div className="mt-0.5 text-xs text-gray-500">{item.subtitle}</div>
      )}
      <div className="mt-1 font-mono text-[10px] text-gray-600">{item.id}</div>
      {chips.length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-1">
          {chips.map((c) => (
            <li
              key={c.id}
              className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-gray-800 text-xs text-gray-300"
            >
              <span className="truncate max-w-[140px]">{c.name}</span>
              <button
                type="button"
                aria-label={`Detach ${c.name}`}
                onClick={(e) => {
                  e.stopPropagation();
                  onDetach(c.id);
                }}
                className="text-gray-500 hover:text-red-400"
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}
