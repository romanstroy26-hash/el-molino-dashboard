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


def temperaturas(desde: dt.date, hoy: dt.date) -> dict:
    """{fecha: temp_max °C} desde `desde` hasta unos 15 días después de `hoy`, para el pronóstico de ventas (pronostico.py).

    Lo viejo viene del archivo histórico; los últimos 21 días reales y los días que vienen, de UNA llamada a la API de
    pronóstico (el archivo se atrasa unos días). Sin internet devuelve lo que haya podido traer, o {}: el pronóstico sigue
    funcionando, solo sin la corrección por temperatura."""
    resultado: dict = {}
    corte = hoy - dt.timedelta(days=22)
    for fila in clima_rango(desde.isoformat(), corte.isoformat()):
        if fila.get("temp_max") is not None:
            resultado[dt.date.fromisoformat(fila["fecha"])] = float(fila["temp_max"])
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={LATITUD}&longitude={LONGITUD}"
        f"&daily=temperature_2m_max&timezone={ZONA_HORARIA}"
        f"&past_days=21&forecast_days={_DIAS_PRONOSTICO_MAX + 1}"
    )
    datos = _pedir(url)
    if datos and "daily" in datos:
        for f, t in zip(datos["daily"].get("time", []), datos["daily"].get("temperature_2m_max", [])):
            if t is not None:
                resultado[dt.date.fromisoformat(f)] = float(t)
    return resultado


def clima_rango(desde: str, hasta: str) -> list[dict]:
    """Igual que clima_dia, pero para un RANGO completo en UNA sola
    llamada HTTP -- necesario para análisis de tendencia (¿se comportan
    distinto los días calurosos EN GENERAL?, no solo "qué tiempo hizo
    hoy"). El archivo histórico de Open-Meteo ya acepta start_date/
    end_date como rango real -- clima_dia simplemente nunca lo
    aprovechaba (pedía un día a la vez).

    Solo sirve para fechas YA PASADAS (API de archivo) -- `hasta` se
    recorta a hoy si viene más adelante; para el pronóstico de días
    futuros se sigue usando clima_dia, uno por uno.

    Devuelve una fila por fecha del rango (mismo formato que clima_dia:
    fecha/temp_max/lluvia_mm) -- lista vacía si el servicio no respondió
    o el rango quedó vacío."""
    hasta = min(hasta, dt.date.today().isoformat())
    if desde > hasta:
        return []

    url = (
        "https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={LATITUD}&longitude={LONGITUD}"
        f"&start_date={desde}&end_date={hasta}"
        f"&daily=temperature_2m_max,precipitation_sum&timezone={ZONA_HORARIA}"
    )
    datos = _pedir(url)
    if not datos or "daily" not in datos:
        return []

    fechas = datos["daily"].get("time", [])
    temps = datos["daily"].get("temperature_2m_max", [])
    lluvias = datos["daily"].get("precipitation_sum", [])
    return [
        {
            "fecha": f,
            "temp_max": temps[i] if i < len(temps) else None,
            "lluvia_mm": lluvias[i] if i < len(lluvias) else None,
        }
        for i, f in enumerate(fechas)
    ]
