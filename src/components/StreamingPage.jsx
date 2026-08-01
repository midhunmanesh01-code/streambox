import { useState } from 'react'
import { UploadCloud } from 'lucide-react'
import Header from './Header.jsx'
import EmptyState from './EmptyState.jsx'
import VideoPlayer from './VideoPlayer.jsx'
import VideoUploader from './VideoUploader.jsx'
import DeleteConfirmationModal from './DeleteConfirmationModal.jsx'
import ReplaceConfirmationModal from './ReplaceConfirmationModal.jsx'
import { useVideo } from '../context/VideoContext.jsx'

export default function StreamingPage() {
  const { video, setCurrentVideo, clearVideo } = useVideo()

  const [uploaderOpen, setUploaderOpen] = useState(false)
  const [pendingReplace, setPendingReplace] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)

  const handleUploadComplete = (file) => {
    setCurrentVideo(file)
    setUploaderOpen(false)
    setPendingReplace(false)
  }

  const handleReplaceClick = () => setPendingReplace(true)
  const handleConfirmReplace = () => {
    setPendingReplace(false)
    setUploaderOpen(true)
  }

  const handleDeleteClick = () => setDeleteOpen(true)
  const handleConfirmDelete = () => {
    clearVideo()
    setDeleteOpen(false)
  }

  return (
    <div className="min-h-screen bg-stage-950">
      <Header />

      <main className="max-w-6xl mx-auto px-6 py-10 md:py-14">
        {!video && !uploaderOpen && <EmptyState onUploadClick={() => setUploaderOpen(true)} />}

        {!video && uploaderOpen && (
          <div className="max-w-2xl mx-auto">
            <VideoUploader onUploadComplete={handleUploadComplete} autoOpen />
          </div>
        )}

        {video && !uploaderOpen && (
          <VideoPlayer video={video} onReplace={handleReplaceClick} onDelete={handleDeleteClick} />
        )}

        {video && uploaderOpen && (
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

        {video && !uploaderOpen && (
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
