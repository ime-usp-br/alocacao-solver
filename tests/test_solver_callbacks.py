"""Testes unitários para o callback de progresso e soft stop do solver."""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.solver.callbacks import StopAwareCallback


@pytest.fixture
def fake_redis() -> MagicMock:
    return MagicMock()


class TestStopAwareCallback:
    def test_progress_reported_on_first_solution(self, fake_redis: MagicMock) -> None:
        cb = StopAwareCallback(
            job_id="test-1",
            redis_conn=fake_redis,
            time_limit_seconds=100,
            progress_offset=15.0,
            progress_scale=70.0,
            min_report_interval_seconds=1.0,
            report_every_n_solutions=10,
        )
        fake_redis.exists.return_value = 0

        with patch.object(cb, "StopSearch"):
            cb.on_solution_callback()

        assert cb.solution_count == 1
        fake_redis.setex.assert_called_once()
        key, ttl, raw_payload = fake_redis.setex.call_args[0]
        assert key == "progress:job_test-1"
        assert ttl == 3600
        payload = json.loads(raw_payload)
        assert payload["progress"] == 15.0
        assert "Otimizando distribuição" in payload["message"]
        assert "Soluções encontradas: 1" in payload["message"]

    def test_throttle_skips_intermediate_solutions(self, fake_redis: MagicMock) -> None:
        cb = StopAwareCallback(
            job_id="test-2",
            redis_conn=fake_redis,
            time_limit_seconds=100,
            progress_offset=15.0,
            progress_scale=70.0,
            min_report_interval_seconds=60.0,  # muito alto para não disparar por tempo
            report_every_n_solutions=10,
        )
        fake_redis.exists.return_value = 0

        with patch.object(cb, "StopSearch"):
            for _ in range(9):
                cb.on_solution_callback()

        # A primeira solução sempre reporta (feedback imediato).
        # As demais (2 a 9) são suprimidas pelo throttle.
        assert fake_redis.setex.call_count == 1

    def test_progress_respects_bounds(self, fake_redis: MagicMock) -> None:
        cb = StopAwareCallback(
            job_id="test-3",
            redis_conn=fake_redis,
            time_limit_seconds=10,
            progress_offset=15.0,
            progress_scale=70.0,
            min_report_interval_seconds=0.0,  # sempre reporta por tempo
            report_every_n_solutions=1_000_000,  # nunca reporta por contagem
        )
        fake_redis.exists.return_value = 0

        with patch.object(cb, "StopSearch"):
            cb.on_solution_callback()

        payload = json.loads(fake_redis.setex.call_args[0][2])
        assert 15.0 <= payload["progress"] <= 85.0

    def test_stop_search_when_stop_key_exists(self, fake_redis: MagicMock) -> None:
        cb = StopAwareCallback(
            job_id="test-4",
            redis_conn=fake_redis,
            time_limit_seconds=100,
            min_report_interval_seconds=1.0,
            report_every_n_solutions=10,
        )
        fake_redis.exists.return_value = 1

        with patch.object(cb, "StopSearch") as mock_stop:
            cb.on_solution_callback()

        fake_redis.exists.assert_called_once_with("stop_job:test-4")
        mock_stop.assert_called_once()
        assert cb.was_stopped is True

    def test_message_contains_expected_text(self, fake_redis: MagicMock) -> None:
        cb = StopAwareCallback(
            job_id="test-5",
            redis_conn=fake_redis,
            time_limit_seconds=100,
            min_report_interval_seconds=0.0,
            report_every_n_solutions=1,
        )
        fake_redis.exists.return_value = 0

        with patch.object(cb, "StopSearch"):
            cb.on_solution_callback()
            cb.on_solution_callback()

        # Duas chamadas, duas mensagens
        assert fake_redis.setex.call_count == 2
        last_payload = json.loads(fake_redis.setex.call_args_list[-1][0][2])
        assert "Otimizando distribuição" in last_payload["message"]
        assert "Isto pode demorar alguns minutos." in last_payload["message"]
        assert "Soluções encontradas: 2" in last_payload["message"]
