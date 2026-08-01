import { UploadCloud, Clapperboard } from 'lucide-react'

export default function EmptyState({ onUploadClick }) {
  return (
    <div className="relative aspect-video w-full rounded-2xl border border-stage-700 bg-stage-900/60 flex flex-col items-center justify-center text-center px-6 overflow-hidden animate-rise">
      <div className="absolute inset-0 film-grain opacity-[0.03]" />
      <div className="relative w-14 h-14 rounded-full border border-stage-600 flex items-center justify-center mb-6">
        <Clapperboard className="w-6 h-6 text-ink-500" strokeWidth={1.5} />
      </div>
      <h2 className="relative font-display text-2xl text-ink-100 mb-2">Your stream is empty</h2>
      <p className="relative text-ink-500 text-sm max-w-xs mb-7">
        Upload a video to bring the screen to life. It'll be the only thing showing here.
      </p>
      <button
        onClick={onUploadClick}
        className="relative flex items-center gap-2 bg-brass-400 hover:bg-brass-300 text-stage-950 font-medium rounded-lg px-5 py-2.5 transition-colors"
      >
        <UploadCloud className="w-4 h-4" strokeWidth={2} />
        Upload Video
      </button>
    </div>
  )
}
