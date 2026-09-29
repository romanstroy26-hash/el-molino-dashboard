"""
alertas.py -- Блок: присылает письмо, когда закрытый день закончился
СИЛЬНО хуже прогноза (сильно -- отдельный, более строгий порог, чем
обычные +-5% "анализа дня"; иначе почта забивалась бы письмами почти
каждый день). Чтобы не открывать дашборд просто ради проверки "всё ли в
порядке".

Использует ТУ ЖЕ почту, что уже настроена для приёма отчётов Wansoft
(CORREO_USUARIO/CORREO_CLAVE в .env, см. correo.py) -- у Gmail (и
большинства почтовых служб) один и тот же пароль приложения годится и
для приёма (IMAP), и для отправки (SMTP).

Чтобы ВКЛЮЧИТЬ рассылку, добавить в .env всего одну строку:

    ALERTA_EMAIL_DESTINO=куда-присылать-письма@например.com

Без этой строки функция просто ничего не делает -- отключать отдельно не
нужно. Если SMTP-сервер отличается от уже настроенного IMAP (не Gmail),
можно уточнить:

    ALERTA_SMTP_SERVIDOR=smtp.gmail.com
    ALERTA_SMTP_PUERTO=465

Вызывается раз в час из vigilar.py, всегда про ПОСЛЕДНИЙ ЗАКРЫТЫЙ день
(вчера), никогда про день, который ещё идёт. Уже отправленные предупреждения
запоминаются в data/alertas_enviadas.json (по паре дата+точка), чтобы не
слать одно и то же дважды.
"""

import datetime as dt
import json
import os
import smtplib
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv

import metrics
import tiempo

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

ESTADO = HERE / "data" / "alertas_enviadas.json"

# Порог ТРЕВОГИ -- строже, чем порог обычного "анализа дня"
# (metrics._UMBRAL_DESVIACION_PCT = 5%): письмо при каждом отклонении в 5%
# завалило бы почту без пользы; интересны только по-настоящему необычные
# дни.
UMBRAL_ALERTA_PCT = 20.0


def _config_lista() -> dict | None:
    destino = os.getenv("ALERTA_EMAIL_DESTINO")
    usuario = os.getenv("CORREO_USUARIO")
    clave = os.getenv("CORREO_CLAVE")
    if not (destino and usuario and clave):
        return None
    return {
        "destino": destino,
        "usuario": usuario,
        "clave": clave,
        "servidor": os.getenv("ALERTA_SMTP_SERVIDOR", "smtp.gmail.com"),
        "puerto": int(os.getenv("ALERTA_SMTP_PUERTO", "465")),
    }


def _cargar_revisadas() -> set:
    if not ESTADO.exists():
        return set()
    try:
        return set(json.loads(ESTADO.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return set()


def _guardar_revisadas(revisadas: set) -> None:
    ESTADO.parent.mkdir(exist_ok=True)
    ESTADO.write_text(json.dumps(sorted(revisadas), ensure_ascii=False, indent=1), encoding="utf-8")


def _enviar_correo(config: dict, asunto: str, cuerpo: str) -> None:
    msg = MIMEText(cuerpo, "plain", "utf-8")
    msg["Subject"] = asunto
    msg["From"] = config["usuario"]
    msg["To"] = config["destino"]
    with smtplib.SMTP_SSL(config["servidor"], config["puerto"]) as s:
        s.login(config["usuario"], config["clave"])
        s.send_message(msg)


def revisar_y_avisar(engine, sucursales: list) -> list:
    """Revisa el último día CERRADO (ayer) de cada sucursal. Si quedó por
    debajo del pronóstico más allá de UMBRAL_ALERTA_PCT y esa
    fecha+sucursal todavía no se revisó, manda un correo. Devuelve la
    lista de avisos mandados en esta pasada (vacía si el correo no está
    configurado o no hubo nada grave que avisar) -- para que vigilar.py lo
    registre en su log."""
    config = _config_lista()
    if config is None:
        return []

    revisadas = _cargar_revisadas()
    enviados = []
    ayer = tiempo.hoy() - dt.timedelta(days=1)

    for sucursal in sucursales:
        clave = f"{ayer.isoformat()}|{sucursal}"
        if clave in revisadas:
            continue

        datos = metrics.ventas_por_hora(engine, ayer.isoformat(), sucursal=sucursal)
        analisis = metrics.analizar_desempeno_por_hora(datos["horas"], fecha=ayer.isoformat())
        if analisis is None or analisis["estado"] != "por_debajo" or abs(analisis["delta_pct"]) < UMBRAL_ALERTA_PCT:
            # Нечего слать -- запоминаем как проверенный день, чтобы не
            # пересчитывать анализ заново каждый час впустую.
            revisadas.add(clave)
            continue

        asunto = (
            f"⚠️ El Molino -- {sucursal}: {ayer.isoformat()} "
            f"ниже прогноза на {abs(analisis['delta_pct']):.0f}%"
        )
        cuerpo = (
            f"Точка: {sucursal}\n"
            f"День: {ayer.isoformat()}\n\n"
            f"Выручка: {analisis['total_real']:,.0f} $ против ожидаемых "
            f"{analisis['total_tipico']:,.0f} $ ({analisis['delta_pct']:+.1f}%).\n\n"
            f"Подробности -- в дашборде, страница «Продажи по часам»."
        )
        try:
            _enviar_correo(config, asunto, cuerpo)
            revisadas.add(clave)  # отправлено -- отмечаем, чтобы не слать повторно
            enviados.append(clave)
        except Exception as e:  # noqa: BLE001 -- сеть/почта временно недоступна
            # НЕ отмечаем как проверенный -- в отличие от случая "нечего
            # слать" выше, здесь письмо было НУЖНО отправить, просто не
            # получилось; следующий цикл (через час) попробует снова, как
            # auto_carga.py делает при временной недоступности базы.
            print(f"  АЛЕРТА: не удалось отправить письмо -- {e}")

    _guardar_revisadas(revisadas)
    return enviados
