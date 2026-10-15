import json
import unittest
from pathlib import Path

from api.guidance import class_details, load_guide
from api.inference import classifier

ROOT = Path(__file__).resolve().parents[1]


class CareGuideTests(unittest.TestCase):
    def test_all_model_labels_have_one_sourced_method(self):
        guide = load_guide()
        self.assertEqual(set(guide), set(classifier.labels))
        self.assertEqual(len(guide), 38)
        for label in classifier.labels:
            with self.subTest(label=label):
                item = guide[label]
                self.assertTrue(item["one_method"].strip())
                self.assertTrue(item["summary"].strip())
                self.assertIsInstance(item["immediate_steps"], list)
                self.assertIsInstance(item["prevention"], list)
                self.assertTrue(item["caution"].strip())
                self.assertTrue(item["references"])
                self.assertTrue(all(ref["url"].startswith("https://") for ref in item["references"]))
                self.assertIn("display_name", class_details(label))

    def test_model_order_and_metrics_are_bundled(self):
        labels = json.loads((ROOT / "shared/class_names.json").read_text(encoding="utf-8"))
        metrics = json.loads((ROOT / "shared/model_metrics.json").read_text(encoding="utf-8"))
        self.assertEqual(labels, classifier.labels)
        self.assertTrue(metrics)
        self.assertEqual(classifier.session.get_outputs()[0].shape[-1], len(labels))


if __name__ == "__main__":
    unittest.main()
