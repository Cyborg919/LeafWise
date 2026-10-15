# Setup Guide

## Web and API

1. Install Python 3.11 or newer.
2. From the project root, run `./scripts/setup-python.sh`.
3. Run `./scripts/run-local.sh`.
4. Open `http://127.0.0.1:3000`; use `/docs` for the API documentation.

By default, the API is local-only (`127.0.0.1`). It uses the bundled ONNX model, SQLite, and local files without an external AI key. Use `LEAFWISE_DATA_DIR=/path/to/data` to move local history. Unsaved photos are not retained. For tests run `LEAFWISE_FORCE_SQLITE=1 .venv/bin/python -m unittest discover -s tests -v`; tests use an isolated temporary data directory.

In a configured Webdev deployment, the process reads `DATABASE_URL`, `MANUS_API_URL`, and `MANUS_API_KEY` from server-side runtime variables. Never copy these into web JavaScript or commit them. The web checkbox makes persistence opt-in. Managed photos remain in project object storage when a report is hidden because the runtime storage API has no delete operation; the UI warns about this. In local mode, deleting a report removes its photo file too.

## Android

1. Install Android Studio/SDK platform 35 and Java 17+.
2. From the project root run:

   ```bash
   cd android
   ./gradlew assembleDebug
   ```

3. Install the debug APK at `android/app/build/outputs/apk/debug/app-debug.apk` on a device running Android 7.0/API 24 or later.

The Android app uses the phone camera/gallery and performs ONNX inference offline. Photos are never uploaded. When the user chooses to save a report, the app stores it and the photo in private app storage; Remove deletes both. A release APK needs an owner-supplied private signing key.

## Complete ZIP

After building the APK, run `./scripts/package.sh` from the project root. It creates `dist/leafwise-fullstack.zip` and verifies that the APK contains the shared model, labels, care guide, web assets, and ONNX Runtime libraries.

## API quick reference

- `GET /api/health`, `/api/model`, `/api/classes`, `/api/care/{label}`
- `POST /api/predict` with multipart fields `image`, `top_k` (1–5), and optional `save_to_history` (default `false`)
- `GET /api/history`, `GET /api/history/{id}/image`, `DELETE /api/history/{id}`

Send `X-Client-Token: <64 lowercase hexadecimal characters>` for saved history operations. This is a browser ownership token, not an account/login system. API docs are served at `/docs`.
