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
    │   ├── AuthContext.jsx      # mock login, sessionStorage-backed
    │   └── VideoContext.jsx     # single "current video" state
    ├── utils/
    │   └── mockApi.js           # formatBytes, formatDate, simulateUpload
    └── components/
        ├── Login.jsx
        ├── ProtectedRoute.jsx
        ├── Header.jsx
        ├── StreamingPage.jsx
        ├── VideoPlayer.jsx
        ├── VideoUploader.jsx
        ├── UploadProgress.jsx
        ├── EmptyState.jsx
        ├── ConfirmationModal.jsx    (shared shell)
        ├── DeleteConfirmationModal.jsx
        └── ReplaceConfirmationModal.jsx