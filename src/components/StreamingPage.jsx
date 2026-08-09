import { useState } from 'react'
import { Loader2, UploadCloud } from 'lucide-react'
import Header from './Header.jsx'
import EmptyState from './EmptyState.jsx'
import VideoPlayer from './VideoPlayer.jsx'
import VideoUploader from './VideoUploader.jsx'
import DeleteConfirmationModal from './DeleteConfirmationModal.jsx'
import ReplaceConfirmationModal from './ReplaceConfirmationModal.jsx'
import { useVideo } from '../context/VideoContext.jsx'

export default function StreamingPage() {
  const { video, loading, setCurrentVideo, refreshCurrentVideo, clearVideo } = useVideo()

  const [uploaderOpen, setUploaderOpen] = useState(false)
  const [pendingReplace, setPendingReplace] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)

  const handleUploadComplete = (uploadedVideo) => {
    setCurrentVideo(uploadedVideo)
    setUploaderOpen(false)
    setPendingReplace(false)
  }

  const handleReplaceClick = () => setPendingReplace(true)
  const handleConfirmReplace = () => {
    setPendingReplace(false)
    setUploaderOpen(true)
  }

  const handleDeleteClick = () => setDeleteOpen(true)
  const handleConfirmDelete = async () => {
    await clearVideo()
    setDeleteOpen(false)
  }

  const currentVideoIsReady = video?.processingStatus === 'ready'
  const currentVideoIsProcessing = video && !currentVideoIsReady

  return (
    <div className="min-h-screen bg-stage-950">
      <Header />

      <main className="max-w-6xl mx-auto px-6 py-10 md:py-14">
        {loading && (
          <div className="min-h-[50vh] flex items-center justify-center text-ink-500">
            <Loader2 className="w-5 h-5 animate-spin" />
          </div>
        )}

        {!loading && currentVideoIsProcessing && !uploaderOpen && (
          <div className="max-w-2xl mx-auto rounded-2xl border border-stage-700 bg-stage-900/60 px-6 py-12 text-center animate-rise">
            <div className="mx-auto mb-4 w-11 h-11 rounded-full border border-stage-600 flex items-center justify-center">
              <Loader2 className="w-5 h-5 animate-spin text-brass-400" />
            </div>
            <h2 className="font-display text-2xl text-ink-100 mb-2">Preparing video for playback…</h2>
            <p className="text-ink-500 text-sm max-w-md mx-auto">
              StreamBox is analyzing the upload and generating a browser-compatible playback version.
            </p>
          </div>
        )}

        {!loading && video?.processingStatus === 'failed' && !uploaderOpen && (
          <div className="max-w-2xl mx-auto rounded-2xl border border-signal-red/30 bg-signal-red/10 px-6 py-12 text-center animate-rise">
            <h2 className="font-display text-2xl text-ink-100 mb-2">Video processing failed</h2>
            <p className="text-ink-500 text-sm max-w-md mx-auto">
              StreamBox could not prepare this file for browser playback. Upload a different video to try again.
            </p>
          </div>
        )}

        {!loading && !video && !uploaderOpen && <EmptyState onUploadClick={() => setUploaderOpen(true)} />}

        {!loading && !video && uploaderOpen && (
          <div className="max-w-2xl mx-auto">
            <VideoUploader onUploadComplete={handleUploadComplete} autoOpen />
          </div>
        )}

        {!loading && currentVideoIsReady && !uploaderOpen && (
          <VideoPlayer video={video} onReplace={handleReplaceClick} onDelete={handleDeleteClick} onVideoUpdate={setCurrentVideo} />
        )}

        {!loading && video && uploaderOpen && (
          <div className="max-w-2xl mx-auto">
            <VideoUploader onUploadComplete={handleUploadComplete} autoOpen />
            <button
              onClick={() => setUploaderOpen(false)}
              className="mt-4 text-sm text-ink-500 hover:text-ink-100 transition-colors"
            >
              Cancel
            </button>
          </div>
        )}

        {!loading && currentVideoIsReady && !uploaderOpen && (
          <div className="mt-10 flex justify-center">
            <button
              onClick={handleReplaceClick}
              className="flex items-center gap-2 text-sm text-ink-500 hover:text-brass-300 transition-colors"
            >
              <UploadCloud className="w-4 h-4" strokeWidth={1.75} />
              Upload a different video
            </button>
          </div>
        )}
      </main>

      {pendingReplace && (
        <ReplaceConfirmationModal
          videoTitle={video?.title}
          onConfirm={handleConfirmReplace}
          onCancel={() => setPendingReplace(false)}
        />
      )}

      {deleteOpen && (
        <DeleteConfirmationModal
          videoTitle={video?.title}
          onConfirm={handleConfirmDelete}
          onCancel={() => setDeleteOpen(false)}
        />
      )}
    </div>
  )
}
