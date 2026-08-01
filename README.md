# Reel — Private Screening Room

A personal, private video streaming frontend prototype. React + Vite + Tailwind CSS.

## Run locally

```bash
npm install
npm run dev
```

Then open the printed local URL (typically http://localhost:5173).

## Login

This is a frontend-only prototype with hardcoded credentials:

- Username: `admin`
- Password: `123`

## What's mocked

Everything is frontend-only for now:

- **Auth** (`src/context/AuthContext.jsx`) — checks credentials against constants and stores a session flag in `sessionStorage`. Swap `mockLogin` for a real `POST /api/auth/login` call later; the rest of the app doesn't need to change.
- **Video state** (`src/context/VideoContext.jsx`) — holds the single "current video" in memory using an object URL created from the selected file. Swap for `GET /api/video/current` plus real playback URLs.
- **Upload** (`src/utils/mockApi.js`) — `simulateUpload` fakes chunked progress with randomized timing. Swap for a real direct-to-storage or multipart upload to `POST /api/video/upload`, keeping the same `onProgress` / `onComplete` / `onError` callback shape.
- **Delete / Replace** — call `clearVideo()` / re-open the uploader; swap for `DELETE /api/video` and a follow-up upload call.

## Project structure

```
src/
  components/
    Login.jsx
    ProtectedRoute.jsx
    Header.jsx
    StreamingPage.jsx
    VideoPlayer.jsx
    VideoUploader.jsx
    UploadProgress.jsx
    EmptyState.jsx
    ConfirmationModal.jsx
    DeleteConfirmationModal.jsx
    ReplaceConfirmationModal.jsx
  context/
    AuthContext.jsx
    VideoContext.jsx
  utils/
    mockApi.js
  App.jsx
  main.jsx
  index.css
```

## Notes for the future backend

- Enforce the 1.5 GB max upload size server-side too, not just in the client.
- Prefer a resumable/chunked upload strategy for large files.
- Stream video via range requests (HTTP 206) rather than serving the whole file at once.
