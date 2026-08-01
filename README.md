# StreamBox

StreamBox is a private personal video streaming app built with React, Vite, Tailwind CSS, and a Python Flask backend. It is designed for a single authenticated user and keeps the current video persistent across refreshes, browser restarts, and devices.

The existing UI is preserved. The login page, streaming page, upload progress UI, video player, and replace/delete modals still provide the same experience, but the mock data flow has been replaced by real backend state.

## Architecture

```text
Browser
     ├─ React + Vite + Tailwind UI
     ├─ Session-cookie auth
     ├─ Real upload progress via XMLHttpRequest
     └─ Native <video> playback

Flask backend
     ├─ /api/auth/login, /api/auth/logout, /api/auth/status
     ├─ /api/video/current
     ├─ /api/video/upload/init
     ├─ /api/video/upload/<id>
     ├─ /api/video/upload/complete
     └─ /api/video/playback/<signed-token>

Storage and processing
     ├─ SQLite metadata store
     ├─ Private storage adapter for local development
     ├─ S3-compatible storage configuration scaffold
     ├─ ffprobe media inspection
     └─ ffmpeg browser-compatible playback generation
```

The backend stores metadata only. Video binaries are stored outside the React app, and the browser plays a signed playback URL rather than a blob URL.

## Features

- Single active video
- Backend-authenticated private access
- Persistent current video state
- Real upload progress
- 1.5 GB maximum upload size
- Media probing with ffprobe
- Playback preparation with ffmpeg
- Replace and delete workflows
- Processing state while playback media is being prepared
- Signed playback URLs with limited lifetime

## Local Setup

### Frontend

```bash
npm install
npm run dev
```

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

On Windows, activate the virtual environment with the `Scripts\activate` path shown above.

The root package also includes a helper script:

```bash
npm run backend
```

## Environment Variables

Backend configuration lives in `backend/.env`.

```bash
SECRET_KEY=
ADMIN_USERNAME=
ADMIN_PASSWORD_HASH=
SESSION_COOKIE_SECURE=0
API_ALLOWED_ORIGIN=http://localhost:5173
APP_HOST=127.0.0.1
APP_PORT=5000
STORAGE_BACKEND=local
STREAMBOX_DATA_DIR=./data
STREAMBOX_STORAGE_DIR=./data/storage
STREAMBOX_DB_PATH=./data/streambox.sqlite3
UPLOAD_SESSION_TTL_SECONDS=3600
SIGNED_URL_TTL_SECONDS=900

S3_ENDPOINT=
S3_REGION=
S3_BUCKET=
S3_ACCESS_KEY_ID=
S3_SECRET_ACCESS_KEY=
```

Use `ADMIN_PASSWORD_HASH`, not a plaintext password, for the admin login. Generate the hash with Werkzeug before placing it in your `.env` file.

## Authentication

Authentication is handled by the backend using secure session cookies. The frontend calls the Flask auth endpoints and checks `/api/auth/status` on load. Protected video routes require an authenticated session.

## Upload Flow

1. The frontend validates the file size before upload.
2. `/api/video/upload/init` creates an upload session and reserved storage keys.
3. The file is uploaded with real byte-level progress updates.
4. The backend stores the original file privately and probes it with ffprobe.
5. ffmpeg generates a browser-compatible MP4 playback copy when needed.
6. The current video becomes the new upload only after processing succeeds.

The app is structured for direct-to-object-storage multipart/resumable uploads later, while the local development adapter keeps the workflow runnable now.

## Media Processing

StreamBox probes the actual media container and codecs instead of trusting the extension. The backend records:

- container
- video codec
- audio codec
- whether audio exists
- resolution
- duration

For browser playback, the safe target format is MP4 with H.264 video, AAC audio, and yuv420p pixel format.

If the source is already browser-compatible, unnecessary transcoding is avoided where safe. If only the audio is incompatible, the playback path is prepared to preserve the video stream where possible while generating browser-friendly audio.

Supported/common source containers include:

- .mp4
- .mkv
- .mov
- .webm
- .m4v
- .avi

## Storage

The repository uses a private local storage adapter for development. The backend is structured around S3-compatible configuration variables so the storage layer can be swapped without changing the UI flow.

Storage remains private, and playback uses signed URLs rather than public bucket access.

## Notes

- Refreshing the browser keeps the current video.
- Opening StreamBox on another device with the same account shows the same current video.
- Replace uploads only switch the active video after the new upload finishes processing.
- Delete removes the stored source, playback copy, and metadata.

## License

MIT
