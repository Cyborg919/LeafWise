# Leafwise — Crop Health & Care

Leafwise is a complete web-and-Android app built around the supplied 38-class ONNX crop-disease model. It provides a responsive photo workflow, ranked model results, one suggested management method per class, further cited care guidance, a searchable 38-class library, and history you explicitly choose to save.

## Creator

- **Name:** Vignesh P
- **Instagram:** [@vignesh_pgd](https://www.instagram.com/vignesh_pgd/)
- **Email:** [vigneshperingode352@gmail.com](mailto:vigneshperingode352@gmail.com)
- **Project email:** [cybrogofficial@gmail.com](mailto:cybrogofficial@gmail.com)

## What is included

- **Web app:** a polished responsive interface for photo upload/camera capture, results, care notes, class browsing, model information, and opt-in history.
- **Self-hosted API:** a free-to-run FastAPI backend with automatic OpenAPI docs at `/docs`. Its inference endpoint uses the bundled ONNX model; it does not call a paid third-party AI/prediction service and needs no model API key for a local run.
- **Android app:** an installable Android shell with a native Kotlin bridge for camera/gallery selection, ONNX Runtime inference on the phone, and app-private local history. Prediction works offline; phone photos are not sent to the web server.
- **Shared model data:** the ONNX file, exact 38-label order, source-repository metrics, and source-linked treatment guidance are shared between web, API, and Android.

The project does **not** retrain the model. The supplied training dataset is not included, so model weights and the reported validation metric are preserved rather than described as independently improved or reproduced.

## Run the web app locally

Requirements: Python 3.11 or newer.

```bash
./scripts/setup-python.sh
./scripts/run-local.sh
```

Open <http://127.0.0.1:3000>. The API is at `/api`; automatic Swagger/OpenAPI docs are at `/docs`. With no Manus platform runtime variables, saved web history uses SQLite and local image files under `~/.leafwise`. Set `LEAFWISE_DATA_DIR` to choose another data directory. Unsaved photos are processed in memory and are not retained.

### API endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/health` | Model, class-count, history and storage-mode readiness |
| `GET` | `/api/model` | Model metadata and scope limitations |
| `GET` | `/api/classes` | All 38 labels and their full care advice |
| `GET` | `/api/care/{label}` | One label's suggested method, steps, cautions, and sources |
| `POST` | `/api/predict` | Multipart photo inference (`image`, optional `top_k`, `save_to_history`) |
| `GET` | `/api/history` | Saved reports for the requesting browser token |
| `GET` | `/api/history/{id}/image` | Saved photo after owner-token validation |
| `DELETE` | `/api/history/{id}` | Remove a local report/photo or hide a managed report |

For saving and reading history, send a random 64-character lowercase hex `X-Client-Token`. The website creates and keeps one in that browser's local storage. It is a lightweight per-browser ownership token, **not an account or login system**. Photos are saved only when `save_to_history=true` is explicitly selected.

## Build and install Android

Requirements: Android SDK platform 35 and Java 17 or newer. The Gradle wrapper and configuration are included.

```bash
cd android
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

The app supports Android 7.0 / API 24 and newer. It loads the shared web interface from a local Android asset origin and executes inference in Kotlin with the bundled ONNX Runtime. Gallery and camera selection, class browsing, care guidance, and opt-in history are available offline. Gallery photos are copied into a bounded private cache before decoding; camera captures are decoded from their app-private file, with EXIF orientation treated as optional metadata. The separate **Creator** navigation section contains the project creator's links. Saved Android images stay in app-private storage; removing an Android report physically removes its image. The debug APK is intended for testing and direct install. A signed release APK requires the publisher's own private signing key; none is included.

The debug APK was clean-built for SDK 35 and its bundled model/UI assets were verified. No Android phone or emulator was connected in this environment, so direct installation and on-device camera/permission behavior still need a smoke test on the target phone.

## Create the complete ZIP

After building the Android APK, run `./scripts/package.sh` from the project root. The validated archive is written to `dist/leafwise-fullstack.zip`; it includes the web/API source, Android project and debug APK, shared model/data, tests, and setup docs, while excluding SDK caches and local secrets.

## Data retention and removal

- **Unsaved photos:** never added to history. Web analysis does not retain them; Android temporarily stages a private app-cache copy while selected, cleared when removed or on the next app launch.
- **Standalone ZIP:** saved web photos use local files and SQLite; removing a report deletes its local file and history row.
- **Android:** saved photos and records stay inside app-private storage; deleting a record deletes both.
- **Managed Webdev preview/deployment:** opt-in photos use the selected project database and object storage. The platform runtime supports presigned upload/download but has **no object-delete operation**. Hiding a managed report removes it from the browser history view while the object remains in project storage. The UI discloses this before save/removal. The project owner must separately remove managed objects using owner-level storage controls.

The API does not log image bytes, temporary signed URLs, or secret values. Avoid exposing a self-hosted API to the public Internet without adding suitable HTTPS, access control and operational monitoring; this project has per-IP inference rate limiting but no user-account authentication.

## Model and care-guide limits

The model is closed-set: it always ranks among its 38 labels. It is not a general plant species identifier and has no reliable “unknown plant” class, so unsupported plants or field photos can be assigned a wrong label. Its output score is a **ranking score, not a calibrated probability or confirmed diagnosis**. Check the model information in the UI and confirm serious symptoms with a local agricultural extension service. Do not use this result alone to select or apply pesticides. Healthy labels receive routine care guidance instead of disease treatment. The original dataset is absent, so the source-reported validation metric cannot be independently reproduced here.

## Development checks

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
LEAFWISE_FORCE_SQLITE=1 .venv/bin/python -m unittest discover -s tests -v
```

The tests use synthetic leaf images, temporary SQLite, and temporary files; they do not write test diagnoses to the managed database. For the cloud container, use the included `Dockerfile`. The Webdev runtime configuration is prepared for a container health check at `/_app/health`; no public production site is published by this project build.

## Provenance

The original ONNX model, labels, metrics, and care material came from the GitHub project supplied for this task: <https://github.com/harshitd842/hackathon>. Review that project's and model's applicable license before commercial use or redistribution. See [NOTICE.md](NOTICE.md).
