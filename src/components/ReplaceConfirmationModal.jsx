import { RefreshCw } from 'lucide-react'
import ConfirmationModal from './ConfirmationModal.jsx'

export default function ReplaceConfirmationModal({ videoTitle, onConfirm, onCancel }) {
  return (
    <ConfirmationModal
      icon={RefreshCw}
      iconClassName="bg-brass-400/10 text-brass-400"
      title="Replace this video?"
      description={`"${videoTitle}" will be taken off your stream and replaced with the new upload.`}
      confirmLabel="Choose New Video"
      confirmClassName="bg-brass-400 hover:bg-brass-300 text-stage-950"
      onConfirm={onConfirm}
      onCancel={onCancel}
    />
  )
}
