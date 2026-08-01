export default function ConfirmationModal({
  icon: Icon,
  iconClassName,
  title,
  description,
  confirmLabel,
  confirmClassName,
  onConfirm,
  onCancel,
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-6">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm animate-rise" onClick={onCancel} />
      <div className="relative bg-stage-850 border border-stage-700 rounded-2xl p-7 max-w-sm w-full shadow-stage animate-rise">
        <div className={`w-10 h-10 rounded-full flex items-center justify-center mb-4 ${iconClassName}`}>
          <Icon className="w-5 h-5" strokeWidth={1.75} />
        </div>
        <h2 className="font-display text-xl text-ink-100 mb-2">{title}</h2>
        <p className="text-sm text-ink-500 leading-relaxed mb-6">{description}</p>
        <div className="flex items-center gap-3">
          <button
            onClick={onCancel}
            className="flex-1 text-sm border border-stage-600 hover:border-stage-500 text-ink-300 rounded-lg py-2.5 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className={`flex-1 text-sm font-medium rounded-lg py-2.5 transition-colors ${confirmClassName}`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
