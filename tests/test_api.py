import io
import os
import secrets
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

# Force all tests into a private local SQLite/filesystem sandbox, even in Webdev.
_TEST_DIR = tempfile.TemporaryDirectory(prefix="leafwise-tests-")
os.environ["LEAFWISE_FORCE_SQLITE"] = "1"
os.environ["LEAFWISE_DATA_DIR"] = _TEST_DIR.name
os.environ["MANUS_API_URL"] = ""
os.environ["MANUS_API_KEY"] = ""
os.environ["DATABASE_URL"] = ""

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import select

from api.database import create_record, get_engine, history, owner_hash
from api.main import app


def make_leaf_png() -> bytes:
    image = Image.new("RGB", (240, 240), (237, 237, 219))
    draw = ImageDraw.Draw(image)
    draw.ellipse((52, 32, 184, 211), fill=(69, 126, 63), outline=(44, 91, 49), width=4)
    draw.line((115, 49, 119, 190), fill=(220, 226, 190), width=3)
    draw.line((117, 91, 84, 73), fill=(220, 226, 190), width=2)
    draw.line((118, 125, 155, 105), fill=(220, 226, 190), width=2)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()
        cls.photo = make_leaf_png()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        _TEST_DIR.cleanup()

    def token(self):
        return secrets.token_hex(32)

    def analyze(self, token, save=False, raw=None):
        return self.client.post(
            "/api/predict",
            headers={"X-Client-Token": token},
            files={"image": ("leaf.png", raw or self.photo, "image/png")},
            data={"top_k": "3", "save_to_history": str(save).lower()},
        )

    def test_health_docs_and_route_manifest(self):
        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["class_count"], 38)
        self.assertTrue(health.json()["history_ready"])
        self.assertEqual(self.client.get("/docs").status_code, 200)
        routes = self.client.get("/manus-routes.json")
        self.assertEqual(routes.status_code, 200)
        self.assertEqual(routes.json()["routes"][0]["path"], "/")
        self.assertEqual(self.client.get("/assets/app.js").status_code, 200)

    def test_classes_and_model_metadata(self):
        classes = self.client.get("/api/classes").json()
        self.assertEqual(classes["count"], 38)
        self.assertEqual(len(classes["classes"]), 38)
        self.assertTrue(all(item["one_method"] for item in classes["classes"]))
        label = classes["classes"][0]["label"]
        care = self.client.get(f"/api/care/{label}")
        self.assertEqual(care.status_code, 200)
        self.assertTrue(care.json()["one_method"])
        self.assertEqual(self.client.get("/api/care/not-a-model-label").status_code, 404)
        info = self.client.get("/api/model").json()
        self.assertIn("Closed-set", " ".join(info["limitations"]))

    def test_prediction_runs_model_and_unsaved_photo_is_not_retained(self):
        token = self.token()
        response = self.analyze(token)
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(response.headers.get("cache-control"), "private, no-store")
        self.assertFalse(data["saved"])
        self.assertFalse(data["image_saved"])
        self.assertEqual(len(data["predictions"]), 3)
        self.assertTrue(data["primary"]["label"])
        self.assertTrue(data["care"]["one_method"])
        self.assertIn("not probabilities", data["notice"])
        history_response = self.client.get("/api/history", headers={"X-Client-Token": token})
        self.assertEqual(history_response.headers.get("cache-control"), "private, no-store")
        self.assertEqual(history_response.json()["items"], [])
        upload_dir = Path(os.environ["LEAFWISE_DATA_DIR"]) / "uploads"
        self.assertFalse(upload_dir.exists() and any(upload_dir.rglob("*.jpg")))

    def test_invalid_file_is_rejected(self):
        response = self.analyze(self.token(), raw=b"not an image")
        self.assertEqual(response.status_code, 400)

    def test_saved_report_is_owner_scoped_and_local_delete_removes_photo(self):
        token = self.token()
        response = self.analyze(token, save=True)
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertTrue(data["saved"])
        self.assertTrue(data["image_saved"])
        record_id = data["history_id"]
        own = self.client.get("/api/history", headers={"X-Client-Token": token}).json()["items"]
        other = self.client.get("/api/history", headers={"X-Client-Token": self.token()}).json()["items"]
        self.assertEqual(len(own), 1)
        self.assertEqual(other, [])
        image_response = self.client.get(f"/api/history/{record_id}/image", headers={"X-Client-Token": token})
        self.assertEqual(image_response.status_code, 200)
        self.assertTrue(image_response.content)
        deleted = self.client.delete(f"/api/history/{record_id}", headers={"X-Client-Token": token})
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertTrue(deleted.json()["photo_removed"])
        self.assertEqual(self.client.get("/api/history", headers={"X-Client-Token": token}).json()["items"], [])
        self.assertFalse(list((Path(os.environ["LEAFWISE_DATA_DIR"]) / "uploads").rglob("*.jpg")))

    def test_managed_delete_hides_record_without_claiming_object_erasure(self):
        token = self.token()
        token_hash = owner_hash(token)
        record_id = str(uuid.uuid4())
        image_key = f"leafwise/{token_hash[:20]}/{uuid.uuid4()}.jpg"
        create_record(record_id, token_hash, "Apple___Apple_scab", 0.8, [], image_key)
        with patch("api.main.storage.is_managed", return_value=True), patch("api.main.storage.delete_image") as delete_mock:
            response = self.client.delete(f"/api/history/{record_id}", headers={"X-Client-Token": token})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["photo_removed"])
        delete_mock.assert_not_called()
        self.assertEqual(self.client.get("/api/history", headers={"X-Client-Token": token}).json()["items"], [])
        with get_engine().connect() as connection:
            hidden = connection.execute(select(history.c.is_deleted).where(history.c.id == record_id)).scalar_one()
        self.assertTrue(hidden)


if __name__ == "__main__":
    unittest.main()
