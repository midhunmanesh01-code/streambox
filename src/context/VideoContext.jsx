import { createContext, useContext, useState } from 'react'

const VideoContext = createContext(null)

// Shape of the "current video" record. Later this comes from
// GET /api/video/current instead of local state.
export function VideoProvider({ children }) {
  const [video, setVideo] = useState(null)
  // video = { title, sizeBytes, uploadedAt, url }

  const setCurrentVideo = (file) => {
    const url = URL.createObjectURL(file)
    setVideo({
      title: file.name.replace(/\.[^/.]+$/, ''),
      sizeBytes: file.size,
      uploadedAt: new Date(),
      url,
    })
  }

  const clearVideo = () => {
    if (video?.url) URL.revokeObjectURL(video.url)
    setVideo(null)
  }

  return (
    <VideoContext.Provider value={{ video, setCurrentVideo, clearVideo }}>
      {children}
    </VideoContext.Provider>
  )
}

export function useVideo() {
  const ctx = useContext(VideoContext)
  if (!ctx) throw new Error('useVideo must be used within VideoProvider')
  return ctx
}
