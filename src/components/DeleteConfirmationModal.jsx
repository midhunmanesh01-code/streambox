import { Trash2 } from 'lucide-react'
import ConfirmationModal from './ConfirmationModal.jsx'

export default function DeleteConfirmationModal({ videoTitle, onConfirm, onCancel }) {
  return (
    <ConfirmationModal
      icon={Trash2}
      iconClassName="bg-signal-red/10 text-signal-red"
      title="Delete this video?"
      description={`"${videoTitle}" will be permanently removed from your stream. This can't be undone.`}
      confirmLabel="Delete Video"
      confirmClassName="bg-signal-red hover:bg-signal-red/90 text-white"
      onConfirm={onConfirm}
      onCancel={onCancel}
    />
  )
}
