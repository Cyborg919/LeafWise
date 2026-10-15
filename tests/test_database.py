import json
import unittest

import certifi
from sqlalchemy.engine import URL

from api.database import _database_url_and_options


class DatabaseUrlTests(unittest.TestCase):
    def test_managed_mysql_tls_is_converted_to_verified_pymysql_options(self):
        raw = URL.create(
            "mysql",
            username="leafwise-test",
            password="not-a-real-password",
            host="db.example.invalid",
            database="leafwise_test",
            query={"ssl": json.dumps({"rejectUnauthorized": True}), "charset": "utf8mb4"},
        )
        url, options = _database_url_and_options(str(raw))
        self.assertEqual(url.drivername, "mysql+pymysql")
        self.assertNotIn("ssl", url.query)
        self.assertEqual(url.query["charset"], "utf8mb4")
        self.assertEqual(options["ssl"]["verify_mode"], "required")
        self.assertTrue(options["ssl"]["check_hostname"])
        self.assertEqual(options["ssl"]["ca"], certifi.where())

    def test_managed_mysql_tls_can_enforce_encryption_without_cert_validation_if_selected(self):
        raw = URL.create(
            "mysql",
            username="leafwise-test",
            password="not-a-real-password",
            host="db.example.invalid",
            database="leafwise_test",
            query={"ssl": json.dumps({"rejectUnauthorized": False})},
        )
        _, options = _database_url_and_options(str(raw))
        self.assertEqual(options["ssl"]["verify_mode"], "none")
        self.assertFalse(options["ssl"]["check_hostname"])
        self.assertNotIn("ca", options["ssl"])


if __name__ == "__main__":
    unittest.main()
