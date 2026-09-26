#!/usr/bin/env python3
"""
vigilar.py -- сторож. Работает постоянно в фоне и сам подхватывает новые
выгрузки, как только они появляются в отслеживаемых папках -- без
Start.bat, без Autoload.bat, вообще без единого клика после установки.

Что делает, в бесконечном цикле, пока компьютер включён:
  - каждые 15 секунд смотрит в те же папки, что и auto_carga.py (data,
    "Загрузки", и всё из CARPETAS_EXTRA в .env) -- и грузит всё новое в
    базу;
  - если в .env настроена почта (см. correo.py) -- дополнительно, раз в
    15 минут, заходит и забирает вложения;
  - пишет, что происходило, в data/carga.log -- та же лента, что у
    Autoload.bat, один общий журнал на всё.

Один и тот же результат, что и было раньше, только без человека: файл
положили в папку -- через 15 секунд он уже в базе. Задваивания можно не
бояться -- загрузка идёт по чекам (см. db.insert_lines), поэтому одно и
то же не может лечь в базу дважды, сколько бы раз сторож ни увидел файл.

Как этим пользоваться:

  - Двойной клик по `Vigilante.bat` -- запустить и смотреть вживую (в
    окне видно, что происходит). Остановить -- Ctrl+C в этом окне или
    просто закрыть его.
  - `Schedule.bat` (один раз) -- поставить так, чтобы это запускалось
    само при каждом входе в Windows, без окна, и работало постоянно.
  - `Detener_Vigilante.bat` -- остановить совсем (и не запускать больше
    при входе в Windows, пока не запустишь Schedule.bat заново).

Два запущенных сторожа на одном компьютере не уживутся: второй, увидев,
что первый уже работает (по файлу data/vigilante.pid), сразу завершится
сам, ничего не поломав.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import auto_carga
import correo
import tiempo
from db import DEFAULT_DB_PATH, get_engine

HERE = Path(__file__).resolve().parent
PID_FILE = auto_carga.DATA_DIR / "vigilante.pid"

# Как часто проверять папки -- часто и дёшево: просто список файлов на
# диске, без обращения к сети.
INTERVALO_ARCHIVOS = 15

# Как часто заглядывать в почту -- редко: это поход по сети на другой
# сервер, незачем дёргать его каждые 15 секунд.
INTERVALO_CORREO = 15 * 60

# Если весь цикл целиком упал (сеть легла, база временно недоступна) --
# не долбить её раз в 15 секунд, а подождать подольше и попробовать
# снова. Сторож при этом не останавливается -- см. try/except в bucle().
INTERVALO_TRAS_ERROR = 60


def _pid_vivo(pid: int) -> bool:
    """Работает ли ещё процесс с таким номером (проверка средствами
    самой Windows, без сторонних библиотек)."""
    try:
        salida = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True, timeout=5,
        )
        return str(pid) in salida.stdout
    except OSError:
        # Не смогли спросить -- на всякий случай считаем живым, чтобы не
        # запустить вторую копию по ошибке.
        return True


def _tomar_pid() -> bool:
    """Проверяет, не работает ли уже другой сторож, и если нет --
    записывает в PID_FILE номер ЭТОГО процесса. Возвращает True, если
    другой сторож уже занят (значит, этому запуску надо тихо выйти)."""
    auto_carga.DATA_DIR.mkdir(exist_ok=True)
    if PID_FILE.exists():
        try:
            pid_anterior = int(PID_FILE.read_text().strip())
        except ValueError:
            pid_anterior = None
        if pid_anterior and pid_anterior != os.getpid() and _pid_vivo(pid_anterior):
            return True
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    return False


def _liberar_pid() -> None:
    """Убирает свою запись при выходе -- но только свою: если её уже
    перезаписал следующий запущенный сторож, чужую метку не трогаем."""
    try:
        if PID_FILE.exists() and PID_FILE.read_text().strip() == str(os.getpid()):
            PID_FILE.unlink()
    except OSError:
        pass


def _correo_configurado() -> bool:
    return all(os.getenv(n) for n in ("CORREO_SERVIDOR", "CORREO_USUARIO", "CORREO_CLAVE"))


def bucle() -> None:
    if _tomar_pid():
        print("Сторож уже работает на этом компьютере -- второй запуск не нужен.")
        print("(см. data/vigilante.pid; если уверен, что это ошибка -- удали "
              "этот файл и запусти снова)")
        return

    # Подключение к базе -- С ПОВТОРАМИ, а не один раз: если компьютер
    # только что включился и сеть ещё не поднялась (или облачная база на
    # минуту недоступна), обычный get_engine() упал бы с ошибкой, и весь
    # процесс сторожа умер бы прямо на старте -- НЕЗАМЕЧЕННО, потому что
    # он запущен скрыто и никто не смотрит в окно. Вместо падения --
    # ждём и пробуем снова, пока не получится.
    engine = None
    while engine is None:
        try:
            engine = get_engine(str(HERE / DEFAULT_DB_PATH))
        except Exception as e:  # noqa: BLE001 -- на старте база может быть
            # временно недоступна, это не повод умирать молча.
            print(f"База пока недоступна ({e}), пробую снова через "
                  f"{INTERVALO_TRAS_ERROR} с...")
            time.sleep(INTERVALO_TRAS_ERROR)

    estado = auto_carga._cargar_estado()
    con_correo = _correo_configurado()

    print("=" * 60)
    print("  El Molino -- сторож запущен")
    print(f"  Время (Сан-Луис-Потоси): {tiempo.etiqueta()}")
    print(f"  Проверка папок: каждые {INTERVALO_ARCHIVOS} с")
    if con_correo:
        print(f"  Проверка почты: каждые {INTERVALO_CORREO // 60} мин")
    else:
        print("  Проверка почты: не настроена в .env -- пропускается")
    print("  Остановить: Detener_Vigilante.bat (или Ctrl+C в этом окне)")
    print("=" * 60)
    auto_carga._registrar([f"{tiempo.sello_de_tiempo()}  сторож запущен (PID {os.getpid()})"])

    ultimo_correo = 0.0
    try:
        while True:
            try:
                if con_correo and time.monotonic() - ultimo_correo >= INTERVALO_CORREO:
                    correo.descargar()
                    ultimo_correo = time.monotonic()

                nuevos = auto_carga.archivos_nuevos(estado)
                if nuevos:
                    sello = tiempo.sello_de_tiempo()
                    print(f"\n[{tiempo.etiqueta()}] новых файлов: {len(nuevos)}")
                    cargados, lineas = auto_carga.procesar(engine, nuevos, estado, sello)
                    lineas.insert(0, f"{sello}  сторож увидел новых файлов: {len(nuevos)}")
                    auto_carga._registrar(lineas)
                    print(f"  загружено: {cargados}")
            except Exception as e:  # noqa: BLE001 -- сторож не должен падать НИКОГДА:
                # один сбойный цикл (сеть, временная недоступность базы)
                # не должен останавливать всё наблюдение до утра.
                print(f"[{tiempo.etiqueta()}] сбой цикла: {e}")
                auto_carga._registrar([f"{tiempo.sello_de_tiempo()}  сторож: сбой цикла: {e}"])
                time.sleep(INTERVALO_TRAS_ERROR)
                continue

            time.sleep(INTERVALO_ARCHIVOS)
    finally:
        _liberar_pid()
        auto_carga._registrar([f"{tiempo.sello_de_tiempo()}  сторож остановлен"])


if __name__ == "__main__":
    try:
        bucle()
    except KeyboardInterrupt:
        print("\nОстановлено.")
        sys.exit(0)
