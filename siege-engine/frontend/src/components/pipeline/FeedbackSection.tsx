interface FeedbackSectionProps {
  notes: string;
  onNotesChange: (v: string) => void;
  feedbackCount: number;
  label?: string;
  placeholder?: string;
}

export function FeedbackSection({
  notes,
  onNotesChange,
  feedbackCount,
  label = 'Review Notes (optional)',
  placeholder = 'Add feedback for re-generation...',
}: FeedbackSectionProps) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <label className="text-xs text-gray-400">{label}</label>
        {feedbackCount > 0 && (
          <span className="text-xs text-orange-400">
            {feedbackCount} previous feedback{feedbackCount !== 1 ? 's' : ''}
          </span>
        )}
      </div>
      <textarea
        value={notes}
        onChange={(e) => onNotesChange(e.target.value)}
        className="w-full h-24 md:h-32 px-2 py-1 bg-gray-800 text-white text-sm rounded border border-gray-600 focus:border-blue-500 focus:outline-none resize-y"
        placeholder={placeholder}
      />
    </div>
  );
}
