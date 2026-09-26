#!/usr/bin/env python3
"""
correo.py -- забирает отчёты Wansoft из почты и кладёт их в папку data.

Последнее звено автоматизации. Wansoft умеет сам присылать отчёт на
e-mail по расписанию; этот модуль раз в день заходит в почтовый ящик,
находит такие письма, сохраняет вложенные .xlsx в data -- и на этом
ручная работа заканчивается совсем: дальше auto_carga.py грузит их в
базу, а дашборд показывает свежие цифры.

Что нужно настроить один раз (см. README, раздел "Отчёты из почты"):

  1. В самом Wansoft включить отправку отчёта "Detalle de Ventas" на
     почту по расписанию.
  2. Дописать в файл .env несколько строк:

        CORREO_SERVIDOR=imap.gmail.com
        CORREO_USUARIO=твой-ящик@gmail.com
        CORREO_CLAVE=пароль приложения (НЕ обычный пароль от почты)
        CORREO_REMITENTE=wansoft.net
        CORREO_CARPETA=INBOX

     "Пароль приложения" -- отдельный пароль только для программ, его
     выдаёт сама почта (у Gmail: Аккаунт -> Безопасность -> Пароли
     приложений). Обычный пароль от почты вводить не надо и нельзя:
     во-первых, с двухфакторной защитой он всё равно не сработает,
     во-вторых, пароль приложения можно отозвать одной кнопкой, не меняя
     основной.

Письма помечаются прочитанными только после того, как вложение успешно
сохранено -- если что-то сорвалось, в следующий раз письмо возьмётся
снова.

Запуск:
    py correo.py            -- забрать новые письма
    py correo.py --todas    -- перечитать и уже прочитанные письма
"""

import argparse
import email
import imaplib
import os
import sys
from email.message import Message
from pathlib import Path

from dotenv import load_dotenv

import tiempo

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
LOG = DATA_DIR / "carga.log"

load_dotenv(HERE / ".env")

# Отчёт Wansoft "Detalle de Ventas" -- единственный, который умеет читать
# extractors/wansoft.py. Остальные вложения (другие отчёты, картинки,
# подписи) пропускаем.
def es_reporte(nombre: str) -> bool:
    """Похоже ли имя вложения на нужный отчёт Wansoft."""
    if not nombre:
        return False
    n = nombre.lower()
    if not n.endswith((".xlsx", ".xls")):
        return False
    # Wansoft называет файл "ReporteDetalleDeVentas<дата>.xlsx"; допускаем
    # пробелы и подчёркивания на случай, если в рассылке имя оформлено
    # иначе.
    compacto = n.replace(" ", "").replace("_", "").replace("-", "")
    return "detalledeventas" in compacto


def _nombre_libre(destino: Path, nombre: str) -> Path:
    """Не затираем уже лежащий файл с тем же именем: если отчёт за тот же
    день пришлют повторно (например, более полный), пусть лягут оба --
    загрузка по чекам всё равно сведёт их в один правильный результат, а
    старый файл останется как след."""
    p = destino / nombre
    if not p.exists():
        return p
    base, punto, ext = nombre.rpartition(".")
    i = 2
    while True:
        p = destino / f"{base} ({i}).{ext}" if punto else destino / f"{nombre} ({i})"
        if not p.exists():
            return p
        i += 1


def guardar_adjuntos(msg: Message, destino: Path) -> list[Path]:
    """Сохраняет из письма все вложения, похожие на отчёт Wansoft.
    Возвращает список сохранённых файлов."""
    destino.mkdir(exist_ok=True)
    guardados = []
    for parte in msg.walk():
        if parte.get_content_maintype() == "multipart":
            continue
        nombre = parte.get_filename()
        if not es_reporte(nombre or ""):
            continue
        datos = parte.get_payload(decode=True)
        if not datos:
            continue
        ruta = _nombre_libre(destino, nombre)
        ruta.write_bytes(datos)
        guardados.append(ruta)
    return guardados


def _registrar(lineas: list[str]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        for linea in lineas:
            f.write(linea + "\n")


def descargar(todas: bool = False) -> list[Path]:
    """Заходит в почту и забирает вложения. Возвращает сохранённые файлы."""
    servidor = os.getenv("CORREO_SERVIDOR")
    usuario = os.getenv("CORREO_USUARIO")
    clave = os.getenv("CORREO_CLAVE")
    remitente = os.getenv("CORREO_REMITENTE", "wansoft.net")
    carpeta = os.getenv("CORREO_CARPETA", "INBOX")

    faltan = [n for n, v in (("CORREO_SERVIDOR", servidor),
                              ("CORREO_USUARIO", usuario),
                              ("CORREO_CLAVE", clave)) if not v]
    if faltan:
        print("Почта не настроена -- в файле .env не хватает строк: "
              + ", ".join(faltan))
        print("Что именно вписать -- в начале этого файла и в README.")
        return []

    sello = tiempo.sello_de_tiempo()
    print(f"Захожу в почту {usuario} ({servidor})...")

    with imaplib.IMAP4_SSL(servidor) as m:
        m.login(usuario, clave)
        m.select(carpeta)
        criterio = f'(FROM "{remitente}")' if todas else f'(UNSEEN FROM "{remitente}")'
        estado, datos = m.search(None, criterio)
        if estado != "OK":
            print("Не получилось найти письма в этой папке.")
            return []

        ids = datos[0].split()
        if not ids:
            print("Новых писем от Wansoft нет.")
            _registrar([f"{sello}  почта: новых писем нет"])
            return []

        print(f"Писем от Wansoft: {len(ids)}")
        guardados: list[Path] = []
        lineas = [f"{sello}  почта: писем {len(ids)}"]

        for num in ids:
            # BODY.PEEK -- читаем письмо, НЕ помечая прочитанным: отметку
            # ставим сами и только после успешного сохранения вложения.
            estado, datos = m.fetch(num, "(BODY.PEEK[])")
            if estado != "OK" or not datos or not isinstance(datos[0], tuple):
                continue
            msg = email.message_from_bytes(datos[0][1])
            archivos = guardar_adjuntos(msg, DATA_DIR)
            if archivos:
                m.store(num, "+FLAGS", "\\Seen")
                for a in archivos:
                    print(f"  сохранён {a.name}")
                    lineas.append(f"{sello}  почта: сохранён {a.name}")
                guardados.extend(archivos)
            else:
                asunto = msg.get("Subject", "(без темы)")
                print(f"  письмо без нужного вложения: {asunto}")

        _registrar(lineas)
        return guardados


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--todas", action="store_true",
                    help="перечитать и уже прочитанные письма")
    args = ap.parse_args()

    print("=" * 60)
    print("  El Molino -- отчёты из почты")
    print(f"  Время (Сан-Луис-Потоси): {tiempo.etiqueta()}")
    print("=" * 60)

    guardados = descargar(todas=args.todas)
    if guardados:
        print(f"\nСохранено файлов: {len(guardados)} (в папку data)")
        print("Теперь запусти Autoload.bat -- он загрузит их в базу.")
    print()


if __name__ == "__main__":
    try:
        main()
    except imaplib.IMAP4.error as e:
        print(f"\nПочта не пустила: {e}")
        print("Чаще всего это значит, что в CORREO_CLAVE записан обычный "
              "пароль от почты вместо ПАРОЛЯ ПРИЛОЖЕНИЯ.")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nОтменено.")
        sys.exit(0)
