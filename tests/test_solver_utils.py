"""Testes unitários para app.solver.utils."""

import pytest

from app.solver.utils import (
    DAY_MAP,
    build_global_minutes,
    parse_day_to_index,
    parse_time_to_minutes,
)


class TestParseDayToIndex:
    def test_all_valid_days(self) -> None:
        for day, expected in DAY_MAP.items():
            assert parse_day_to_index(day) == expected
            assert parse_day_to_index(day.upper()) == expected
            assert parse_day_to_index(f" {day} ") == expected

    def test_invalid_day(self) -> None:
        with pytest.raises(ValueError, match="Dia inválido"):
            parse_day_to_index("mon")


class TestParseTimeToMinutes:
    def test_midnight(self) -> None:
        assert parse_time_to_minutes("00:00") == 0

    def test_typical_morning(self) -> None:
        assert parse_time_to_minutes("08:00") == 480

    def test_typical_afternoon(self) -> None:
        assert parse_time_to_minutes("13:30") == 810

    def test_end_of_day(self) -> None:
        assert parse_time_to_minutes("23:59") == 1439

    def test_invalid_format(self) -> None:
        with pytest.raises(ValueError, match="Formato de horário inválido"):
            parse_time_to_minutes("8h00")

    def test_non_numeric(self) -> None:
        with pytest.raises(ValueError, match="não numéricos"):
            parse_time_to_minutes("ab:cd")

    def test_out_of_range(self) -> None:
        with pytest.raises(ValueError, match="fora do intervalo"):
            parse_time_to_minutes("25:00")


class TestBuildGlobalMinutes:
    def test_single_timeslot(self) -> None:
        timeslots = [
            {"id": 0, "day": "seg", "start": "08:00", "end": "09:40"},
        ]
        result = build_global_minutes(timeslots)
        # seg = 0 -> 0 * 1440 + 480 = 480
        # end = 0 * 1440 + 580 = 580
        assert result[0] == (480, 580)

    def test_multiple_days(self) -> None:
        timeslots = [
            {"id": 0, "day": "seg", "start": "08:00", "end": "09:40"},
            {"id": 1, "day": "qua", "start": "10:00", "end": "11:40"},
        ]
        result = build_global_minutes(timeslots)
        # qua = 2 -> 2 * 1440 + 600 = 3480
        # end = 2 * 1440 + 700 = 3580
        assert result[0] == (480, 580)
        assert result[1] == (3480, 3580)

    def test_invalid_timeslot_end_before_start(self) -> None:
        timeslots = [
            {"id": 0, "day": "seg", "start": "10:00", "end": "09:00"},
        ]
        with pytest.raises(ValueError, match="end_global .* start_global"):
            build_global_minutes(timeslots)
