"""Utilitários puros para pré-processamento de tempo do solver."""

MINUTES_PER_DAY = 1440

DAY_MAP = {
    "seg": 0,
    "ter": 1,
    "qua": 2,
    "qui": 3,
    "sex": 4,
    "sab": 5,
    "dom": 6,
}


def parse_day_to_index(day: str) -> int:
    """Converte nome do dia da semana para índice numérico (0=seg, 6=dom)."""
    normalized = day.strip().lower()
    if normalized not in DAY_MAP:
        valid = ", ".join(DAY_MAP.keys())
        raise ValueError(f"Dia inválido: '{day}'. Valores aceitos: {valid}")
    return DAY_MAP[normalized]


def parse_time_to_minutes(time_str: str) -> int:
    """Converte string 'HH:MM' para minutos desde meia-noite."""
    parts = time_str.strip().split(":")
    if len(parts) != 2:
        raise ValueError(
            f"Formato de horário inválido: '{time_str}'. Esperado 'HH:MM'."
        )
    try:
        hours = int(parts[0])
        minutes = int(parts[1])
    except ValueError as exc:
        raise ValueError(
            f"Horário contém valores não numéricos: '{time_str}'."
        ) from exc

    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        raise ValueError(f"Horário fora do intervalo válido: '{time_str}'.")

    return hours * 60 + minutes


def build_global_minutes(
    timeslots: list[dict],
) -> dict[int, tuple[int, int]]:
    """
    Converte uma lista de timeslots em um dict mapeando
    timeslot_id -> (start_global, end_global) em minutos contínuos.

    A fórmula é: (day_index * 1440) + (hora * 60 + minuto).
    """
    result: dict[int, tuple[int, int]] = {}
    for ts in timeslots:
        ts_id = ts["id"]
        day_index = parse_day_to_index(ts["day"])
        start_minute = parse_time_to_minutes(ts["start"])
        end_minute = parse_time_to_minutes(ts["end"])

        start_global = (day_index * MINUTES_PER_DAY) + start_minute
        end_global = (day_index * MINUTES_PER_DAY) + end_minute

        if end_global <= start_global:
            raise ValueError(
                f"Timeslot {ts_id} tem end_global ({end_global}) <= start_global ({start_global})."
            )

        result[ts_id] = (start_global, end_global)

    return result
