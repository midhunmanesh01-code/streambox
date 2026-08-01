# 🎥StreamBox

A modern, private personal video streaming platform built with **React, Vite, and Tailwind CSS**.

StreamBox provides a simple and distraction-free space to upload and watch a personal video through a clean, cinematic streaming interface.

> **Note:** The project currently focuses on the frontend experience. Authentication and video uploads are simulated. Real backend authentication, cloud storage, and persistent video streaming will be implemented in future versions.

## ✨ Features

- Modern dark-themed streaming interface
- Responsive design for desktop and mobile
- Login-protected streaming page
- Single active video architecture
- Drag-and-drop video uploader
- Maximum video size of **1.5 GB**
- Upload progress simulation
- Built-in video player
- Replace current video functionality
- Delete video functionality
- Confirmation modals for delete and replace actions
- Empty state when no video is available
- Reusable React component architecture

## 🛠️ Tech Stack

- **React** — Frontend UI
- **Vite** — Development and build tooling
- **Tailwind CSS** — Styling
- **React Context API** — Authentication and video state management
- **JavaScript (ES6+)**

## 📁 Project Structure

```text
private-stream/
├── package.json
├── vite.config.js
├── tailwind.config.js
├── postcss.config.js
├── index.html
├── README.md
└── src/
    ├── main.jsx
    ├── App.jsx
    ├── index.css
    ├── context/
    │   ├── AuthContext.jsx
    │   └── VideoContext.jsx
    ├── utils/
    │   └── mockApi.js
    └── components/
        ├── Login.jsx
        ├── ProtectedRoute.jsx
        ├── Header.jsx
        ├── StreamingPage.jsx
        ├── VideoPlayer.jsx
        ├── VideoUploader.jsx
        ├── UploadProgress.jsx
        ├── EmptyState.jsx
        ├── ConfirmationModal.jsx
        ├── DeleteConfirmationModal.jsx
        └── ReplaceConfirmationModal.jsx
```

## 🚀 Getting Started

### 1. Clone the Repository

```bash
git clone https://github.com/midhunmanesh01-code/streambox.git
cd streambox
```

### 2. Install Dependencies

```bash
npm install
```

### 3. Start the Development Server

```bash
npm run dev
```

Open the local development URL provided by Vite in your browser.

## 🔐 Authentication

The current version uses mock frontend authentication for development.

Authentication state is stored using `sessionStorage`, while protected routes prevent access to the streaming interface without an active session.

> The current authentication system is **not intended for production use**. It will later be replaced with secure backend authentication.

## 🎬 Video Upload

StreamBox currently uses frontend mock functionality to simulate video uploads.

The application supports:

- Video selection
- Drag-and-drop uploads
- File size validation
- Upload progress simulation
- Replacing the current video
- Deleting the current video
- Video playback

The maximum supported video size is:

```text
1.5 GB
```

Persistent cloud storage is not yet implemented.

## 🏗️ Planned Architecture

```text
Browser
   │
   ├── React Frontend
   │
   ├── Authentication
   │        │
   │        ▼
   │   Flask Backend
   │
   └── Direct Video Upload
            │
            ▼
       Object Storage
            │
            ▼
       Video Playback
```

Large video files will eventually be uploaded directly to object storage instead of being transferred through the application server.

## 🗺️ Roadmap

- [x] React frontend
- [x] Responsive streaming interface
- [x] Mock authentication
- [x] Protected routes
- [x] Video player interface
- [x] Drag-and-drop uploader
- [x] Upload progress UI
- [x] Replace video workflow
- [x] Delete video workflow
- [ ] Flask REST API
- [ ] Secure backend authentication
- [ ] Environment-based configuration
- [ ] Object storage integration
- [ ] Real uploads up to 1.5 GB
- [ ] Persistent video metadata
- [ ] Private video access
- [ ] Real video streaming
- [ ] Production deployment

## 🔒 Security

The current authentication system is intended only for frontend development.

Before production deployment:

- Authentication will be moved to the backend
- Passwords and secrets will not be stored in frontend source code
- Environment variables will be used for sensitive configuration
- Video storage will remain private
- Video access will require authorization
- Temporary or signed URLs will be used where appropriate

## 📄 License

This project is licensed under the **MIT License**.

---

Built as a personal full-stack project exploring modern frontend development, authentication, large-file uploads, cloud storage, and private video streaming.

With ❤️- By Midhun Manesh
