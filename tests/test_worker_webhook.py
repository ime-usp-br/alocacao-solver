import json
import logging
from typing import Any
from unittest.mock import MagicMock, patch

import fakeredis
import httpx
import pytest

from app.solver.engine import Pass1Result
from app.worker.processor import _send_webhook
from app.worker.tasks import process_job

WEBHOOK_URL = "http://laravel-app/api/webhooks/allocation-result"


def _make_valid_payload(job_id: str = "test-job") -> dict[str, Any]:
    return {
        "job_id": job_id,
        "meta": {
            "version": "1.0.0",
            "school_term_id": 42,
            "webhook_url": WEBHOOK_URL,
            "progress_webhook_url": "http://laravel-app/api/webhooks/allocation-progress",
        },
        "config": {
            "strict_capacity": False,
            "block_b_restriction_for_pos": True,
            "wasted_seats_weight": 1.5,
            "unassigned_penalty": 1000.0,
            "time_limit_seconds": 300,
        },
        "timeslots": [
            {
                "id": 0,
                "label": "seg_0800_0940",
                "day": "seg",
                "start": "08:00",
                "end": "09:40",
            },
        ],
        "rooms": [{"id": 1, "name": "B09", "capacity": 40}],
        "groups": [
            {
                "id": 101,
                "type": "single",
                "class_ids": [101],
                "coddis": "MAC0110",
                "tiptur": "Graduacao",
                "demand": 55,
                "has_null_enrollment": False,
                "timeslot_ids": [0],
                "preassigned_room_id": None,
            }
        ],
    }


class TestSendWebhook:
    def test_send_webhook_success(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.WARNING)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None

        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_client
            mock_client.post.return_value = mock_response

            _send_webhook(WEBHOOK_URL, {"status": "optimal"})

            mock_client.post.assert_called_once_with(
                WEBHOOK_URL, json={"status": "optimal"}
            )
            mock_response.raise_for_status.assert_called_once()
            assert "Falha de rede" not in caplog.text
            assert "Webhook retornou HTTP" not in caplog.text

    def test_send_webhook_network_failure(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.WARNING)

        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_client
            mock_client.post.side_effect = httpx.ConnectTimeout("Timeout")

            _send_webhook(WEBHOOK_URL, {"status": "optimal"})

            assert "Falha de rede ao enviar webhook" in caplog.text

    def test_send_webhook_http_error(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.WARNING)
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        http_error = httpx.HTTPStatusError(
            "Server error",
            request=MagicMock(),
            response=mock_response,
        )
        mock_response.raise_for_status.side_effect = http_error

        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_client
            mock_client.post.return_value = mock_response

            _send_webhook(WEBHOOK_URL, {"status": "optimal"})

            assert "Webhook retornou HTTP 500" in caplog.text
            assert "Internal Server Error" in caplog.text


class TestProcessJobWebhook:
    def test_process_job_solver_error_sends_error_webhook(self) -> None:
        fake_redis = fakeredis.FakeRedis()
        payload = _make_valid_payload("test-error-job")

        with patch("app.worker.tasks.redis.from_url", return_value=fake_redis):
            with patch(
                "app.worker.tasks.run_pass_1", side_effect=RuntimeError("Solver crash")
            ):
                with patch("httpx.Client") as mock_client_class:
                    mock_client = MagicMock()
                    mock_client_class.return_value.__enter__.return_value = mock_client
                    mock_response = MagicMock()
                    mock_response.status_code = 200
                    mock_response.raise_for_status.return_value = None
                    mock_client.post.return_value = mock_response

                    process_job(payload)

                    raw = fake_redis.get("result:test-error-job")
                    assert raw is not None
                    result = json.loads(raw)
                    assert result["status"] == "error"
                    assert "Solver crash" in result["message"]

                    mock_client.post.assert_called_once()
                    call_args = mock_client.post.call_args
                    assert call_args[0][0] == WEBHOOK_URL
                    assert call_args[1]["json"]["status"] == "error"

    def test_process_job_success_redis_before_webhook(self) -> None:
        fake_redis = fakeredis.FakeRedis()
        payload = _make_valid_payload("test-order-job")
        call_order: list[str] = []

        def mock_save(redis_conn: Any, job_id: str, payload: dict[str, Any]) -> None:
            call_order.append("redis")

        def mock_webhook(url: str, payload: dict[str, Any]) -> None:
            call_order.append("webhook")

        pass1_result = Pass1Result(
            status="optimal",
            solve_time_seconds=1.0,
            objective_value=100.0,
            allocations=[(101, 1)],
            unassigned_groups=[],
            solutions_found=1,
        )

        with patch("app.worker.tasks.redis.from_url", return_value=fake_redis):
            with patch("app.worker.tasks.run_pass_1", return_value=pass1_result):
                with patch(
                    "app.worker.tasks._save_result_to_redis",
                    side_effect=mock_save,
                ):
                    with patch(
                        "app.worker.tasks._send_webhook",
                        side_effect=mock_webhook,
                    ):
                        process_job(payload)

        assert call_order == ["redis", "webhook"]

    def test_process_job_error_redis_before_webhook(self) -> None:
        fake_redis = fakeredis.FakeRedis()
        payload = _make_valid_payload("test-error-order-job")
        call_order: list[str] = []

        def mock_save(redis_conn: Any, job_id: str, payload: dict[str, Any]) -> None:
            call_order.append("redis")

        def mock_webhook(url: str, payload: dict[str, Any]) -> None:
            call_order.append("webhook")

        with patch("app.worker.tasks.redis.from_url", return_value=fake_redis):
            with patch(
                "app.worker.tasks.run_pass_1", side_effect=RuntimeError("Crash")
            ):
                with patch(
                    "app.worker.tasks._save_result_to_redis",
                    side_effect=mock_save,
                ):
                    with patch(
                        "app.worker.tasks._send_webhook",
                        side_effect=mock_webhook,
                    ):
                        process_job(payload)

        assert call_order == ["redis", "webhook"]
