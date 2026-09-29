"""
clima.py -- Блок: погода в Сан-Луис-Потоси (макс. температура,
осадки) через Open-Meteo -- публичный бесплатный API, без ключа и
регистрации. Нужен, чтобы обогатить "Анализ дня" (Главная, Продажи по
часам, Планирование) ещё одной ПРОВЕРЯЕМОЙ гипотезой: жаркий день обычно
двигает спрос в сторону фраппе/холодных напитков, дождливый может снизить
общий трафик -- не выдуманная причина, а факт погоды в этот конкретный
день, который дашборд просто показывает рядом с цифрами.

Ничего не решает сам -- как и festivo_cercano в metrics.py, только
предлагает возможный фактор, направление эффекта уже видно по самим
продажам (выше прогноза или ниже).

Никаких секретов в .env для этого не нужно -- Open-Meteo открыт.
"""

import datetime as dt
import json
import urllib.error
import urllib.request

# Координаты Сан-Луис-Потоси (город, где обе точки) -- если бизнес
# когда-нибудь откроется в другом городе, поменять здесь.
LATITUD = 22.1565
LONGITUD = -100.9855
ZONA_HORARIA = "America/Mexico_City"

# Open-Meteo прогнозирует вперёд не бесконечно -- за этой границей вместо
# ошибки просто возвращаем None (не считать это поломкой дашборда).
_DIAS_PRONOSTICO_MAX = 15


def _pedir(url: str) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        # Без интернета, сервис недоступен, странный ответ -- дашборд не
        # должен падать из-за необязательного дополнения к анализу.
        return None


def clima_dia(fecha: str) -> dict | None:
    """Макс. температура (°C) и осадки (мм) за один день в Сан-Луис-Потоси
    -- прошлый (архив) или ближайшее будущее (прогноз), смотря что за
    дата. None если сервис не ответил или дата вне досягаемости прогноза
    -- в любом случае не ошибка, просто "погоды не будет в этом анализе"."""
    target = dt.date.fromisoformat(fecha)
    hoy = dt.date.today()

    if target <= hoy:
        url = (
            "https://archive-api.open-meteo.com/v1/archive"
            f"?latitude={LATITUD}&longitude={LONGITUD}"
            f"&start_date={fecha}&end_date={fecha}"
            f"&daily=temperature_2m_max,precipitation_sum&timezone={ZONA_HORARIA}"
        )
    else:
        if (target - hoy).days > _DIAS_PRONOSTICO_MAX:
            return None
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={LATITUD}&longitude={LONGITUD}"
            f"&daily=temperature_2m_max,precipitation_sum&timezone={ZONA_HORARIA}"
            f"&forecast_days={_DIAS_PRONOSTICO_MAX + 1}"
        )

    datos = _pedir(url)
    if not datos or "daily" not in datos:
        return None

    fechas = datos["daily"].get("time", [])
    temps = datos["daily"].get("temperature_2m_max", [])
    lluvias = datos["daily"].get("precipitation_sum", [])
    if fecha not in fechas:
        return None
    idx = fechas.index(fecha)

    return {
        "fecha": fecha,
        "temp_max": temps[idx] if idx < len(temps) else None,
        "lluvia_mm": lluvias[idx] if idx < len(lluvias) else None,
    }
