import unittest

from app import app


class TestPredictionApplication(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_health_endpoint(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")
        self.assertTrue(response.headers.get("X-Request-ID"))

    def test_health_endpoint_has_request_id(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers.get("X-Request-ID"))

    def test_metrics_endpoint_exposes_application_metrics(self):
        response = self.client.get("/metrics")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/plain", response.content_type)
        body = response.get_data(as_text=True)
        self.assertIn("student_api_http_requests_total", body)
        self.assertIn("student_api_http_request_duration_seconds", body)
        self.assertIn("student_api_predictions_total", body)
        self.assertIn("student_api_model_loaded", body)

    def test_high_performance_prediction(self):
        response = self.client.post(
            "/predict",
            json={
                "attendance": 90,
                "internal_marks": 85,
                "assignment_marks": 88,
                "previous_score": 80,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["prediction"], "PASS")

    def test_low_performance_prediction(self):
        response = self.client.post(
            "/predict",
            json={
                "attendance": 55,
                "internal_marks": 30,
                "assignment_marks": 40,
                "previous_score": 35,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["prediction"], "FAIL")

    def test_missing_field_validation(self):
        response = self.client.post(
            "/predict",
            json={"attendance": 90, "internal_marks": 85},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("missing_fields", response.get_json())

    def test_non_numeric_field_validation(self):
        response = self.client.post(
            "/predict",
            json={
                "attendance": "ninety",
                "internal_marks": 85,
                "assignment_marks": 88,
                "previous_score": 80,
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("attendance", response.get_json()["invalid_fields"])

    def test_missing_route_is_not_found_and_traced(self):
        response = self.client.get("/route-that-does-not-exist")
        self.assertEqual(response.status_code, 404)
        self.assertTrue(response.headers.get("X-Request-ID"))


if __name__ == "__main__":
    unittest.main()
