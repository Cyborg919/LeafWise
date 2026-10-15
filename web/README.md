# Leafwise web interface

The app is served from FastAPI at `/`; its shared web resources are under `/assets/`. The same static files are bundled into the Android APK and loaded from Android's local asset origin. No framework CDN, tracking script, or paid inference SDK is required.

The upload control sends no photo to history unless the save checkbox is checked. In standalone local mode, saved pictures live under `~/.leafwise/uploads` (or `LEAFWISE_DATA_DIR`) and Remove deletes them. In managed Webdev mode, opted-in photos use the project's object store. Because the platform runtime supports signed upload/download but not object deletion, Hide removes a report from that device's history view while leaving its object in project storage. The save checkbox and history screen state this limitation; a project owner must remove those managed objects separately.
