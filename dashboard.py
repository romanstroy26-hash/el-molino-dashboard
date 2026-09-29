#!/usr/bin/env python3
"""
dashboard.py -- Блок 5: интерфейс. ОДИН файл, весь код виден здесь.

Не запускается как обычный скрипт (`py dashboard.py`) -- это Streamlit-
приложение, оно открывается командой:

    py -m streamlit run dashboard.py

...но проще всего просто дважды кликнуть "Dashboard.bat" рядом -- он делает
эту команду сам и открывает страницу в браузере (браузер тут просто
"экран", в интернет ничего не уходит -- если только сама база не в
облаке, см. db.py и .env.example).

Пять страниц (переключатель слева, открывается на первой -- без единого
клика видно, как прошёл последний день):
  - "Главная"        -- открывается сразу: как прошёл день -- количество
    продаж (чеков), выручка, средний чек, доли по категориям (Panadería/
    Pastelería/Café) и график "прогноз и факт по часам". По умолчанию --
    последний загруженный день и все точки
    вместе, но точку и день можно поменять в фильтрах слева.
  - "Доля напитков"  -- фильтры (точка, измерение, период, диапазон дат)
    -> полная аналитика напитков: кофе, фраппе, остальные напитки.
  - "Продажи по часам" -- то же самое, что на главной, но с выбором любого
    дня и точки (детальный разбор конкретного дня).
  - "Топ товаров"    -- какие позиции меню и категории приносят больше
    всего выручки за период (полная картина продаж, не только кофе).
  - "Планирование"   -- только категория Panadería, в штуках: реальные
    продажи, прогноз (по истории того же дня недели) и план производства
    (вводится вручную -- отдельного источника плана пока нет).
  - "Настройки"      -- форма: список слов для распознавания кофе. Изменения
    сохраняются в базу и сразу видны на дашборде (никакого "запусти
    скрипт заново").

Ничего здесь не считает "по-своему" -- вся математика в metrics.py,
дашборд только показывает и собирает ввод пользователя.
"""

import datetime as dt
import io
from pathlib import Path

import altair as alt
import openpyxl
from openpyxl.styles import Font
import pandas as pd
import streamlit as st

from db import (
    DEFAULT_DB_PATH, get_coffee_keywords, get_engine, get_plan_produccion,
    replace_coffee_keywords, set_plan_produccion,
)
import metrics
import tiempo

# Палитра дашборда -- взята из образца (лесная зелень, тёплое золото,
# кремовый текст) и прогнана через валидатор скилла dataviz: пара
# золото/тёмная бирюза проходит ВСЕ проверки (диапазон светлоты, порог
# насыщенности, различимость при дальтонизме, различимость при обычном
# зрении, контраст с фоном) -- причём сразу на ОБОИХ фонах, тёмном и
# светлом, так что один и тот же цвет безопасно работает в обеих темах
# Streamlit. Золото -- "деньги"/общее (было синим), бирюза -- "кофе"/штуки
# (было оранжевым).
COLOR_PRIMARIO = "#B07E22"
COLOR_SECUNDARIO = "#199E70"

# Третий цвет -- для страницы "Доля напитков", где кофе, фраппе и остальные
# напитки показаны одновременно (структура выручки напитков, три
# категории рядом). Фиолетовый выбран специально не из тёплой gold-семьи
# (чтобы не путаться с золотом = "кофе"/деньги) и не из зелёно-бирюзовой
# (чтобы не путаться с бирюзой = "остальные напитки"/штуки в других
# графиках этой же страницы). Проверено ТЕМ ЖЕ методом, что и пара
# золото/бирюза выше -- шестью проверками скилла dataviz (диапазон
# светлоты, порог насыщенности, различимость при дальтонизме и при
# обычном зрении, контраст с фоном), все три цвета разом (не только
# попарно с соседями -- строже: каждый с каждым), на обоих реальных фонах
# графиков этого дашборда (#FBF8F2 светлый / #16211D тёмный). Node.js на
# компьютере нет -- проверка сделана тем же алгоритмом (Machado-Oliveira-
# Fernandes 2009), портированным в Python на время проверки, а не на глаз.
COLOR_FRAPPE = "#7C5CBF"

# Для графиков "прогноз и факт" -- отдельная пара: факт (сегодняшние
# реальные деньги/штуки) -- то же самое золото, самое важное на графике;
# прогноз (взвешенное среднее за прошлые недели, см. metrics.ventas_por_hora
# -- просто фон для сравнения) -- приглушённый тёмный серо-зелёный, чтобы
# взгляд сразу цеплялся за факт, а
# не тонул в двух одинаково ярких линиях. Проверено скриптом
# dataviz-скилла на обоих фонах разом (см. выше) -- отдельная светлая и
# тёмная версия самого золота/серого не нужна, только фон и сетка вокруг
# них меняются по теме.
COLOR_TIPICO = "#5F6E67"
_TEMA_GRAFICO = {
    "light": {
        "fact": "#B07E22", "texto_pico": "#000000", "fondo": "#FBF8F2",
        "eje_linea": "#D8CFBE", "eje_etiqueta": "#000000", "grid": "#EAE4D6",
    },
    "dark": {
        "fact": "#B07E22", "texto_pico": "#F3EAD9", "fondo": "#16211D",
        "eje_linea": "#3A4D45", "eje_etiqueta": "#B7C2BB", "grid": "#243B33",
    },
}


def _tema_grafico() -> dict:
    """Возвращает цвета графика для ТЕКУЩЕЙ темы Streamlit (светлая/тёмная
    -- та, что выбрана в самом приложении у пользователя). Раньше цвета
    были зашиты только под светлую тему -- на тёмном дашборде (как на
    скриншоте с реальными данными) график получался бледным, плохо
    читаемым пятном. Фон графика при этом всегда прозрачный (см. ниже),
    поэтому он аккуратно сливается со страницей в любой теме."""
    try:
        oscuro = st.context.theme.type == "dark"
    except Exception:
        oscuro = False
    return _TEMA_GRAFICO["dark" if oscuro else "light"]

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / DEFAULT_DB_PATH

st.set_page_config(page_title="El Molino -- доля кофе", layout="wide")

# Лёгкая точечная доводка внешнего вида поверх темы из .streamlit/config.toml
# (сама тема даёт фон/текст/акцент -- этого достаточно для 90% страницы;
# здесь только скругления и тёплая рамка у карточек-контейнеров -- окна
# сравнения на "Главной", раскрывающиеся таблицы -- чтобы они выглядели
# карточками, а не просто линией по краю, плюс чёрный цвет у цифр KPI
# (по умолчанию Streamlit красит их акцентным золотым -- Роман попросил
# чёрным, как весь остальной текст).
st.markdown(
    """
    <style>
    div[data-testid="stVerticalBlockBorderWrapper"] > div[data-testid="stVerticalBlock"] {
        border-radius: 14px;
    }
    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 14px !important;
        border-color: rgba(176, 126, 34, 0.35) !important;
    }
    [data-testid="stMetricValue"] {
        color: #000000;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def _engine():
    return get_engine(str(DB_PATH))


engine = _engine()


def _db_label() -> str:
    url = engine.url
    if url.drivername.startswith("sqlite"):
        return f"{DB_PATH.name} (локальный файл на этом компьютере)"
    return f"облако: {url.drivername}, база «{url.database}» на {url.host}"


# =============================================================================
# Кэш -- чтобы при смене фильтров не ходить в базу заново каждый раз
# =============================================================================
# Каждый клик по фильтру в Streamlit заново выполняет ВЕСЬ файл сверху вниз.
# Без кэша это значит: новый SQL-запрос в базу (для облака -- по сети) и
# новый подсчёт в Python при каждом клике, даже если данные не изменились.
# st.cache_data запоминает результат на CACHE_TTL_SEGUNDOS секунд -- пока
# файлы не перезагружены заново, ответ отдаётся мгновенно, из памяти.
#
# Параметр называется "_engine" (с подчёркиванием) специально -- так
# Streamlit понимает, что его не нужно использовать при сравнении "те же
# ли это аргументы, что в прошлый раз" (сам объект Engine нельзя сравнивать
# для кэша). metrics.py при этом не меняется вообще -- кэш добавлен только
# здесь, в дашборде, а не в самих расчётах.
CACHE_TTL_SEGUNDOS = 300


@st.cache_data(ttl=CACHE_TTL_SEGUNDOS, show_spinner=False)
def _cache_sucursales(_engine):
    return metrics.sucursales_disponibles(_engine)


@st.cache_data(ttl=CACHE_TTL_SEGUNDOS, show_spinner=False)
def _cache_rango_fechas(_engine, sucursal):
    return metrics.rango_fechas(_engine, sucursal)


@st.cache_data(ttl=CACHE_TTL_SEGUNDOS, show_spinner=False)
def _cache_fechas_con_hora(_engine, sucursal):
    return metrics.fechas_con_hora(_engine, sucursal)


@st.cache_data(ttl=CACHE_TTL_SEGUNDOS, show_spinner=False)
def _cache_serie_por_periodo(_engine, granularidad, sucursal, desde, hasta):
    return metrics.serie_por_periodo(_engine, granularidad, sucursal=sucursal, desde=desde, hasta=hasta)


@st.cache_data(ttl=CACHE_TTL_SEGUNDOS, show_spinner=False)
def _cache_ventas_por_hora(_engine, fecha, sucursal):
    return metrics.ventas_por_hora(_engine, fecha, sucursal=sucursal)


@st.cache_data(ttl=CACHE_TTL_SEGUNDOS, show_spinner=False)
def _cache_patron_horario_bebidas(_engine, sucursal, desde, hasta):
    return metrics.patron_horario_bebidas(_engine, sucursal=sucursal, desde=desde, hasta=hasta)


@st.cache_data(ttl=CACHE_TTL_SEGUNDOS, show_spinner=False)
def _cache_panaderia_real_y_pronostico(_engine, desde, hasta, sucursal):
    return metrics.panaderia_real_y_pronostico(_engine, desde=desde, hasta=hasta, sucursal=sucursal)


@st.cache_data(ttl=CACHE_TTL_SEGUNDOS, show_spinner=False)
def _cache_top_platillos_panaderia(_engine, sucursal, desde, hasta, n):
    return metrics.top_platillos_panaderia(_engine, sucursal=sucursal, desde=desde, hasta=hasta, n=n)


@st.cache_data(ttl=CACHE_TTL_SEGUNDOS, show_spinner=False)
def _cache_patron_horario_panaderia(_engine, sucursal, desde, hasta):
    return metrics.patron_horario_panaderia(_engine, sucursal=sucursal, desde=desde, hasta=hasta)


@st.cache_data(ttl=CACHE_TTL_SEGUNDOS, show_spinner=False)
def _cache_carga_por_hora_panaderia(_engine, sucursal, desde, hasta):
    return metrics.carga_por_hora_panaderia(_engine, sucursal=sucursal, desde=desde, hasta=hasta)


@st.cache_data(ttl=CACHE_TTL_SEGUNDOS, show_spinner=False)
def _cache_plan_tarea_dia(_engine, fecha, sucursal, n_productos, multiplo):
    return metrics.plan_tarea_dia(
        _engine, fecha, sucursal=sucursal, n_productos=n_productos, multiplo=multiplo,
    )


def _excel_plan_tarea(tarea: dict, sucursal_label: str) -> bytes:
    """Arma el .xlsx del plan-tarea (tarea = metrics.plan_tarea_dia) --
    tres bloques en una sola hoja: cabecera (fecha/точка/итого/источник),
    reparto por hora, reparto por producto."""
    negrita = Font(bold=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "План-задание"

    ws.append(["План-задание на день", tarea["fecha"]])
    ws["A1"].font = negrita
    ws.append(["Точка", sucursal_label])
    ws.append(["Итого, шт (кратно {})".format(tarea["multiplo"]), tarea["total_dia_redondeado"]])
    ws.append(["Источник итога", tarea["fuente_total"]])
    ws.append(["До округления, шт", tarea["total_dia"]])
    ws.append([])

    ws.append(["По часам"])
    ws[f"A{ws.max_row}"].font = negrita
    ws.append(["Час", "Доля по истории, %", "План, шт"])
    for celda in ws[ws.max_row]:
        celda.font = negrita
    for fila in tarea["por_hora"]:
        ws.append([f"{fila['hora']:02d}:00", fila["pct_historico"], fila["unidades_plan"]])
    ws.append([])

    ws.append(["По позициям меню (топ-{})".format(len(tarea["por_producto"]))])
    ws[f"A{ws.max_row}"].font = negrita
    ws.append(["Позиция", "Доля по истории, %", "План, шт"])
    for celda in ws[ws.max_row]:
        celda.font = negrita
    for fila in tarea["por_producto"]:
        ws.append([fila["platillo"], fila["pct_historico"], fila["unidades_plan"]])

    for col, ancho in zip("ABC", (30, 20, 12)):
        ws.column_dimensions[col].width = ancho

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@st.cache_data(ttl=CACHE_TTL_SEGUNDOS, show_spinner=False)
def _cache_cafe_por_sucursal(_engine, desde, hasta):
    return metrics.cafe_por_sucursal(_engine, desde=desde, hasta=hasta)


@st.cache_data(ttl=CACHE_TTL_SEGUNDOS, show_spinner=False)
def _cache_top_platillos_bebidas(_engine, sucursal, desde, hasta):
    return metrics.top_platillos_bebidas(_engine, sucursal=sucursal, desde=desde, hasta=hasta, n=6)


@st.cache_data(ttl=CACHE_TTL_SEGUNDOS, show_spinner=False)
def _cache_top_platillos(_engine, sucursal, desde, hasta, n):
    return metrics.top_platillos(_engine, sucursal=sucursal, desde=desde, hasta=hasta, n=n)


@st.cache_data(ttl=CACHE_TTL_SEGUNDOS, show_spinner=False)
def _cache_ventas_por_categoria(_engine, sucursal, desde, hasta):
    return metrics.ventas_por_categoria(_engine, sucursal=sucursal, desde=desde, hasta=hasta)


@st.cache_data(ttl=CACHE_TTL_SEGUNDOS, show_spinner=False)
def _cache_resumen_dia(_engine, fecha, sucursal):
    return metrics.resumen_dia(_engine, fecha, sucursal=sucursal)


@st.cache_data(ttl=CACHE_TTL_SEGUNDOS, show_spinner=False)
def _cache_resumen_dia_con_tipico(_engine, fecha, sucursal):
    return metrics.resumen_dia_con_tipico(_engine, fecha, sucursal=sucursal)


@st.cache_data(ttl=CACHE_TTL_SEGUNDOS, show_spinner=False)
def _cache_coffee_keywords(_engine, solo_activas):
    return get_coffee_keywords(_engine, solo_activas=solo_activas)


@st.cache_data(ttl=CACHE_TTL_SEGUNDOS, show_spinner=False)
def _cache_comparacion_semanal(_engine, fecha, sucursal):
    return metrics.comparacion_semanal(_engine, fecha, sucursal=sucursal)


def _recortar_horas_inactivas(horas: list[dict]) -> list[dict]:
    """Quita las horas 'muertas' de las puntas (de madrugada, cuando el
    local ya cerró) -- tanto del día real como del típico -- para que el
    gráfico no arranque ni termine con una fila plana de ceros. No toca
    huecos que caigan EN MEDIO del rango con actividad (una hora floja a
    media mañana sigue siendo horario de trabajo, se queda)."""
    def _hay_algo(h: dict) -> bool:
        return bool(h["real"]) or bool(h["tipico"]) or bool(h["real_unidades"]) or bool(h["tipico_unidades"])

    activas = [i for i, h in enumerate(horas) if _hay_algo(h)]
    if not activas:
        return horas
    return horas[activas[0]: activas[-1] + 1]


def _grafico_metrica_por_hora(df: pd.DataFrame, col_real: str, col_tipico: str,
                               titulo: str, etiqueta_valor: str, sufijo: str,
                               hay_tipico: bool, alto: int) -> None:
    """Один график 'прогноз и факт' (общий код для выручки И для штук) --
    линиями, по образцу, который прислал пользователь: прогноз -- тонкая
    приглушённая линия с лёгкой заливкой-подложкой под ней (взвешенное
    ожидание из истории -- см. metrics.ventas_por_hora, а не простое
    среднее), факт -- жирная насыщенная линия поверх неё, это реальные
    сегодняшние деньги/штуки, самое важное
    на графике. Пиковый час факта отмечен точкой и подписан числом --
    самое важное значение видно сразу, без наведения мышкой. Цвета
    текста/сетки и фон графика подстраиваются под тему Streamlit
    (светлая/тёмная), чтобы график был чётким в обоих случаях. Подписи
    "Прогноз"/"Факт" -- рядом с названием графика, а не легендой поверх
    самого графика (та закрывала собой пиковое значение и часть линий,
    когда пик приходился на правый край)."""
    тема = _tema_grafico()

    if hay_tipico:
        leyenda_html = (
            f'<span style="margin-left:14px;font-weight:400;font-size:0.82em;'
            f'color:{тема["eje_etiqueta"]};white-space:nowrap;">'
            f'<span style="display:inline-block;width:10px;height:2px;'
            f'background:{COLOR_TIPICO};margin-right:5px;vertical-align:middle;"></span>Прогноз'
            f'&nbsp;&nbsp;&nbsp;'
            f'<span style="display:inline-block;width:10px;height:2px;'
            f'background:{тема["fact"]};margin-right:5px;vertical-align:middle;"></span>Факт'
            f'</span>'
        )
    else:
        leyenda_html = ""
    st.markdown(f"**{titulo}**{leyenda_html}", unsafe_allow_html=True)

    # "Прогноз" -- первым в словаре, чтобы после melt() его строки шли
    # раньше строк "Факт": одноимённый слой рисуется в порядке строк, и
    # жирная линия факта должна лечь ПОВЕРХ тонкой линии прогноза, а не под
    # ней.
    columnas = {}
    if hay_tipico:
        columnas[col_tipico] = "Прогноз"
    columnas[col_real] = "Факт"
    largo = (
        df[["час"] + list(columnas)]
        .rename(columns=columnas)
        .melt(id_vars="час", var_name="serie", value_name="valor")
        .dropna(subset=["valor"])
    )

    dominio = ["Прогноз", "Факт"] if hay_tipico else ["Факт"]
    rango = [COLOR_TIPICO, тема["fact"]] if hay_tipico else [тема["fact"]]
    orden_horas = list(df["час"])

    eje_x = alt.X(
        "час:N", title=None, sort=orden_horas,
        axis=alt.Axis(labelAngle=0, grid=False, domainColor=тема["eje_linea"],
                       tickColor=тема["eje_linea"], labelColor=тема["eje_etiqueta"]),
    )
    eje_y = alt.Y(
        "valor:Q", title=None,
        axis=alt.Axis(grid=True, gridColor=тема["grid"], format=",.0f",
                       labelColor=тема["eje_etiqueta"], domain=False, ticks=False),
    )

    capas = []
    if hay_tipico:
        # Лёгкая заливка-подложка ТОЛЬКО под "прогноз" (≈12% непрозрачности
        # -- едва заметная дымка, не сплошной блок), как на референсе.
        tipico_largo = largo[largo["serie"] == "Прогноз"]
        capas.append(
            alt.Chart(tipico_largo).mark_area(interpolate="linear", opacity=0.14, line=False)
            .encode(x=eje_x, y=eje_y, color=alt.value(COLOR_TIPICO))
        )

    lineas = alt.Chart(largo).mark_line(
        interpolate="linear", point=alt.OverlayMarkDef(opacity=0, size=70),
    ).encode(
        x=eje_x, y=eje_y,
        color=alt.Color(
            "serie:N", scale=alt.Scale(domain=dominio, range=rango),
            legend=None,  # подписи серий -- рядом с заголовком (см. leyenda_html выше)
        ),
        strokeWidth=(alt.condition("datum.serie == 'Факт'", alt.value(3), alt.value(2))
                     if hay_tipico else alt.value(3)),
        tooltip=[
            alt.Tooltip("час:N", title="Час"),
            alt.Tooltip("serie:N", title="Ряд"),
            alt.Tooltip("valor:Q", title=etiqueta_valor, format=",.0f"),
        ],
    )
    capas.append(lineas)

    real_vals = largo[largo["serie"] == "Факт"]
    fila_pico = real_vals.loc[[real_vals["valor"].idxmax()]] if not real_vals.empty and real_vals["valor"].max() > 0 else None

    if fila_pico is not None:
        punto_pico = alt.Chart(fila_pico).mark_point(
            filled=True, size=90, color=тема["fact"], stroke=тема["fondo"], strokeWidth=2,
        ).encode(x=eje_x, y=eje_y)
        etiqueta = alt.Chart(fila_pico).mark_text(
            dy=-14, fontWeight="bold", fontSize=13, color=тема["texto_pico"],
        ).encode(x=eje_x, y=eje_y, text=alt.Text("valor:Q", format=",.0f"))
        capas += [punto_pico, etiqueta]

    grafico = (
        alt.layer(*capas)
        .properties(height=alto, background="transparent")
        .configure_view(strokeWidth=0)
    )
    st.altair_chart(grafico, width="stretch", theme=None)

    if not real_vals.empty and real_vals["valor"].sum() > 0:
        total_dia = real_vals["valor"].sum()
        st.caption(f"Всего за день -- **{total_dia:,.0f}{sufijo}**")


def _grafico_por_hora(datos_hora: dict, compacto: bool = False, en_columnas: bool = False) -> pd.DataFrame:
    """Рисует два графика по часам (выручка и штуки, прогноз против факта)
    -- общий код для страниц 'Главная' и 'Продажи по часам'. Линии рядом
    (не друг на друге) -- легче сравнивать факт с прогнозом на глаз, а
    пиковый час каждого графика подписан отдельно -- самое важное значение
    не нужно вычитывать из сетки. Часы без единой продажи ни в факте, ни в
    прогнозе (ночь, раннее утро) обрезаются по краям, чтобы график не
    растягивался на нерабочее время.

    compacto -- уменьшает высоту графиков (для главной страницы, чтобы
    влезло без прокрутки). en_columnas -- рисует оба графика рядом (в две
    колонки), а не один под другим -- тоже ради экономии места по
    вертикали.

    Возвращает DataFrame, чтобы вызывающая страница могла посчитать свои
    итоговые цифры (KPI, таблицу и т.д.)."""
    horas = _recortar_horas_inactivas(datos_hora["horas"])
    df = pd.DataFrame(horas)
    df["час"] = df["hora"].apply(lambda h: f"{h:02d}:00")
    hay_tipico = bool(datos_hora["n_dias_promedio"])
    alto = 220 if compacto else 320

    if en_columnas:
        col_a, col_b = st.columns(2)
        with col_a:
            _grafico_metrica_por_hora(df, "real", "tipico", "Выручка, $", "Выручка", " $", hay_tipico, alto)
        with col_b:
            _grafico_metrica_por_hora(df, "real_unidades", "tipico_unidades", "Продано, шт", "Штук", " шт", hay_tipico, alto)
    else:
        _grafico_metrica_por_hora(df, "real", "tipico", "Выручка, $", "Выручка", " $", hay_tipico, alto)
        _grafico_metrica_por_hora(df, "real_unidades", "tipico_unidades", "Продано, шт", "Штук", " шт", hay_tipico, alto)

    return df


# Порог ТОЛЬКО для формулировок в _texto_analisis_dia (не для самой
# арифметики диагностики -- та в metrics.py): в пределах ±5% штуки
# считаются "на уровне плана"; за пределами -- уже настоящее отклонение
# (вниз -- трафик, вверх -- штук больше, а денег всё равно меньше).
_UMBRAL_ANALISIS_TRAFICO = 5.0


def _texto_festivo(festivo: dict | None) -> str | None:
    """Formulación del festivo mexicano cercano (ver metrics.festivo_cercano)
    -- una posible explicación de CALENDARIO, verificable, no inventada.
    No afirma que el festivo causó la desviación (solo el dato real dice
    si el día quedó arriba o abajo) -- lo presenta como candidato a
    revisar, igual que el resto de "гипотезы" de este bloque."""
    if not festivo:
        return None
    nombre, dif = festivo["nombre"], festivo["dias_diferencia"]
    if dif == 0:
        cuando = f"сегодня -- {nombre}"
    elif dif == 1:
        cuando = f"завтра {nombre}"
    elif dif == -1:
        cuando = f"вчера был(а) {nombre}"
    else:
        cuando = f"через {dif} дн. -- {nombre}" if dif > 0 else f"{abs(dif)} дн. назад был(а) {nombre}"
    return (
        f"Возможный фактор календаря: {cuando} -- в Мексике такие даты "
        f"заметно двигают продажи выпечки/кафе (не всегда в одну сторону), "
        f"стоит держать в уме при сравнении с другими такими же днями "
        f"недели, где праздника не было."
    )


def _texto_analisis_dia(a: dict) -> tuple[str, list[str]]:
    """Превращает диагностику из metrics.analizar_desempeno_por_hora в текст
    на русском -- пороги и арифметика (что считать 'сосредоточенным'
    отклонением, что списать на трафик, а что на средний чек) там, здесь
    только формулировки. "por_encima" разобран так же подробно, как
    "por_debajo" -- аномально ХОРОШИЙ день тоже стоит объяснять (что
    сработало, можно ли повторить), а не просто похвалить одной строкой."""
    festivo_txt = _texto_festivo(a.get("festivo"))

    if a["estado"] == "en_linea":
        resumen = (
            f"Выручка примерно на уровне прогноза ({a['delta_pct']:+.1f}%, "
            f"{a['total_real']:,.0f} $ против {a['total_tipico']:,.0f} $) -- "
            f"заметных отклонений, которые стоило бы разбирать, нет."
        )
        if festivo_txt:
            resumen += " " + festivo_txt
        return resumen, []

    por_encima = a["estado"] == "por_encima"
    signo_txt = "выше" if por_encima else "ниже"
    partes = [
        f"Выручка **{signo_txt} прогноза на {abs(a['delta_pct']):.1f}%** "
        f"({a['total_real']:,.0f} $ против ожидаемых {a['total_tipico']:,.0f} $)."
    ]
    recomendaciones: list[str] = []

    if a["delta_unid_pct"] is not None:
        du = a["delta_unid_pct"]
        # Одно и то же правило в обе стороны: штуки двигаются В ТУ ЖЕ
        # СТОРОНУ, что и выручка, и примерно настолько же -- дело в
        # трафике (числе покупателей); штуки двигаются МЕНЬШЕ или в
        # ПРОТИВОПОЛОЖНУЮ сторону -- дело в среднем чеке.
        if (por_encima and du >= _UMBRAL_ANALISIS_TRAFICO) or (not por_encima and du <= -_UMBRAL_ANALISIS_TRAFICO):
            partes.append(
                f"Штук продано тоже заметно {signo_txt.replace('выше', 'больше').replace('ниже', 'меньше')} "
                f"плана ({du:+.1f}%) -- похоже на изменение количества "
                f"покупателей (трафика), а не среднего чека."
            )
            if por_encima:
                recomendaciones.append(
                    "Посмотри, что привело больше покупателей именно в этот "
                    "день (акция, погода, мероприятие по соседству) -- если "
                    "причину можно повторить, попробуй специально в "
                    "следующий такой же день недели."
                )
            else:
                recomendaciones.append(
                    "Проверь трафик за день: не было ли перебоев с кассой "
                    "или меню, весь ли зал/точка работали по расписанию; "
                    "попробуй локальную рекламу или акцию именно на этот "
                    "день недели."
                )
        elif (por_encima and du <= -_UMBRAL_ANALISIS_TRAFICO) or (not por_encima and du >= _UMBRAL_ANALISIS_TRAFICO):
            partes.append(
                f"При этом штук продано {'МЕНЬШЕ' if por_encima else 'БОЛЬШЕ'} "
                f"плана ({du:+.1f}%), а денег всё равно {signo_txt} -- "
                f"значит, средний чек сдвинулся сильнее, чем кажется по "
                f"одной выручке."
            )
            recomendaciones.append(
                "Проверь средний чек: изменилось ли число скидок, состав "
                "заказов (допродажи десерта/напитка), не сместился ли "
                "спрос на другие по цене позиции меню."
            )
        else:
            partes.append(
                f"При этом штук продано почти по плану ({du:+.1f}%) -- "
                f"значит, сдвинулся средний чек, а не число покупателей."
            )
            recomendaciones.append(
                "Проверь средний чек: изменилось ли число скидок, состав "
                "заказов (допродажи десерта/напитка), не сместился ли "
                "спрос на другие по цене позиции меню."
            )

    if a["horas_criticas"]:
        horas_txt = ", ".join(f"{h['hora']:02d}:00" for h in a["horas_criticas"])
        if a["concentrado"]:
            partes.append(
                (f"Основной вклад в превышение -- {horas_txt}: на эти часы "
                 f"приходится почти весь избыток, остальной день ближе к "
                 f"прогнозу." if por_encima else
                 f"Провал сосредоточен в основном в {horas_txt} -- на "
                 f"остальные часы приходится меньшая часть отставания.")
            )
            if por_encima:
                recomendaciones.append(
                    f"Разбери отдельно {horas_txt}: не было ли там разовой "
                    f"большой группы/заказа, мероприятия по соседству, "
                    f"смены погоды -- если причину можно повторить, "
                    f"попробуй специально в следующий такой же день недели."
                )
            else:
                recomendaciones.append(
                    f"Разбери отдельно {horas_txt}: не было ли в это время "
                    f"меньше персонала, задержки открытия, дефицита позиций "
                    f"меню или очереди, из-за которой уходили клиенты."
                )
        else:
            partes.append(
                (f"Рост распределён почти по всему дню, а не в отдельные "
                 f"часы -- похоже на общий фактор (погода, трафик района, "
                 f"начало тренда), а не на разовое событие в конкретное "
                 f"время." if por_encima else
                 "Отставание распределено почти по всему дню, а не в "
                 "отдельные часы -- вероятно, дело в общем факторе (погода, "
                 "посещаемость района, конкуренты), а не в разовом сбое в "
                 "конкретное время.")
            )
            recomendaciones.append(
                f"Сравни с «Неделя к неделе» на Главной -- если предыдущие "
                f"дни тоже {signo_txt} прогноза, это похоже на тренд, а не "
                f"на случайность одного дня."
            )

    if festivo_txt:
        partes.append(festivo_txt)

    return " ".join(partes), recomendaciones


def _bloque_analisis_dia(df: pd.DataFrame, fecha: str) -> None:
    """Короткая справка внизу страницы (после графика 'Прогноз и факт'):
    насколько день отклонился от прогноза, почему, и что с этим делать.
    Ничего не выводит, если пронозировать было не из чего (см.
    metrics.analizar_desempeno_por_hora). `fecha` -- для проверки
    совпадения с мексиканским праздником (metrics.festivo_cercano)."""
    analisis = metrics.analizar_desempeno_por_hora(df.to_dict("records"), fecha=fecha)
    if analisis is None:
        return

    resumen, recomendaciones = _texto_analisis_dia(analisis)
    icono = {"por_encima": "✅", "en_linea": "➖", "por_debajo": "⚠️"}[analisis["estado"]]

    # st.markdown интерпретирует пары "$...$" как формулу LaTeX -- а в
    # тексте справки почти всегда две суммы в деньгах в одном предложении
    # (факт и прогноз), то есть чётное число "$" на строку. Экранируем
    # знак доллара, иначе часть текста между двумя "$" пропадает,
    # превращаясь в подсвеченную "формулу".
    def _sin_latex(texto: str) -> str:
        return texto.replace("$", r"\$")

    with st.container(border=True):
        st.markdown(f"**{icono} Анализ дня**")
        st.markdown(_sin_latex(resumen))
        if recomendaciones:
            st.markdown("**Рекомендации:**")
            for r in recomendaciones:
                st.markdown(f"- {_sin_latex(r)}")


def _fila_comparacion(ventas_actual, ventas_pasada, ventas_delta,
                       unidades_actual, unidades_pasada, unidades_delta) -> None:
    """Выручка и штуки -- каждая своим st.metric() на всю ширину окна, друг
    под другом. Каждая со своей подсвеченной стрелкой (Streamlit сам
    красит: зелёная вверх / красная вниз), плюс подпись с прошлым
    значением, чтобы было видно и сегодняшнее, и прошлое число."""
    st.metric(
        "Выручка", f"{ventas_actual:,.0f} $",
        delta=f"{ventas_delta:+.1f}%" if ventas_delta is not None else None,
    )
    st.caption(f"было: {ventas_pasada:,.0f} $")
    st.metric(
        "Продано, шт", f"{unidades_actual:,.0f}",
        delta=f"{unidades_delta:+.1f}%" if unidades_delta is not None else None,
    )
    st.caption(f"было: {unidades_pasada:,.0f} шт")


def _panel_dia_vs_semana_pasada(datos: dict) -> None:
    """Окно 'день недели к дню недели': ПОСЛЕДНИЙ ЗАКРЫТЫЙ день против
    ТОГО ЖЕ дня недели ровно неделю назад (не среднее по многим неделям --
    это уже есть в графике по часам ниже, а здесь -- конкретно прошлая
    неделя). Если на странице выбран сегодняшний (ещё не закрытый) день,
    окно всё равно показывает последний закрытый -- например пятницу,
    если сегодня суббота -- и явно это подписывает."""
    fecha_usada = datos.get("fecha_usada")

    # height="stretch" -- растягивает окно на всю высоту своей колонки
    # (а обе колонки в st.columns() и так всегда одной высоты, по самой
    # высокой). Без этого высота считалась только по своему содержимому,
    # и из-за одной лишней строки (см. "Показан последний закрытый день"
    # ниже) или короткого текста "нет данных" это окно и окно
    # "Неделя к неделе" могли получаться разной высоты при смене даты.
    with st.container(border=True, height="stretch"):
        st.markdown("**День к дню**")
        if not datos["disponible"]:
            if datos.get("motivo") == "sin_datos_actuales":
                st.caption(f"Нет данных за {fecha_usada} -- сравнить не с чем.")
            else:
                st.caption(
                    f"Нет данных за {datos['fecha_pasada']} (прошлая "
                    f"неделя) -- сравнить не с чем."
                )
            return
        if datos.get("uso_dia_cerrado_distinto"):
            st.caption(f"Показан последний закрытый день -- {fecha_usada}.")
        _fila_comparacion(
            datos["ventas_actual"], datos["ventas_pasada"], datos["ventas_delta_pct"],
            datos["unidades_actual"], datos["unidades_pasada"], datos["unidades_delta_pct"],
        )


def _panel_semana_vs_semana_pasada(datos: dict) -> None:
    """Окно 'последние 7 дней к предыдущим 7 дням' (НЕ календарная неделя):
    считая назад от последнего ЗАКРЫТОГО дня, сумма за последние 7 дней
    против суммы за 7 дней прямо перед ними -- без общих дат."""
    with st.container(border=True, height="stretch"):
        st.markdown("**Неделя к неделе**")
        if not datos["disponible"]:
            st.caption(
                "На этой неделе ещё нет ни одного закрытого дня -- "
                "сравнивать пока не с чем."
            )
            return
        _fila_comparacion(
            datos["ventas_actual"], datos["ventas_pasada"], datos["ventas_delta_pct"],
            datos["unidades_actual"], datos["unidades_pasada"], datos["unidades_delta_pct"],
        )


def _sparkline(df: pd.DataFrame, campo: str, color: str) -> alt.Chart:
    """Mini-tendencia sin ejes ni etiquetas -- solo la FORMA de los
    últimos días (ver resumen_dia_con_tipico -- serie_reciente), para que
    un número suelto en una tarjeta ("54.5%") se pueda leer también como
    "¿viene subiendo o bajando?" de un vistazo, sin abrir otra página."""
    return alt.Chart(df).mark_line(color=color, strokeWidth=2, point=False).encode(
        x=alt.X("fecha:T", axis=None),
        y=alt.Y(f"{campo}:Q", axis=None, scale=alt.Scale(zero=False)),
        tooltip=[alt.Tooltip("fecha:T", title="Дата"), alt.Tooltip(f"{campo}:Q", title="Значение")],
    ).properties(height=40)


def _ir_a_horas_callback(sucursal_valor: str, fecha_valor: str) -> None:
    """on_click кнопки "Разобрать этот день по часам" на Главной --
    выставляет фильтры страницы "Продажи по часам" и переключает раздел.
    ДОЛЖНО быть колбэком (on_click), не прямой записью в session_state
    после отрисовки кнопки -- см. комментарий у самой кнопки."""
    st.session_state["hora_sucursal"] = sucursal_valor
    st.session_state["hora_fecha"] = fecha_valor
    st.session_state["_pagina_actual"] = "Продажи по часам"


# =============================================================================
# Страница "Главная" -- как прошёл последний день, без единого клика
# =============================================================================
def page_home():
    sucursales = _cache_sucursales(engine)
    if not sucursales:
        st.title("🏠 Todos El Molino")
        st.warning(
            "В базе пока нет данных. Запусти Start.bat и сначала загрузи "
            "файлы Wansoft, потом обнови эту страницу."
        )
        st.stop()

    st.sidebar.header("Фильтры")
    opcion_sucursal = st.sidebar.selectbox(
        "Точка", ["Все точки"] + sucursales, index=0, key="home_sucursal"
    )
    sucursal_filtro = None if opcion_sucursal == "Все точки" else opcion_sucursal
    nombre_punto = sucursal_filtro if sucursal_filtro else "Todos El Molino"

    fechas = _cache_fechas_con_hora(engine, sucursal_filtro)
    if not fechas:
        st.title(f"🏠 {nombre_punto}")
        st.info(
            "Пока нет ни одного дня с полной информацией (время и номер "
            "чека) для этой точки. Перезагрузи те же файлы Wansoft через "
            "Start.bat -> пункт 1 (это не создаст дублей) -- тогда здесь "
            "появится сводка."
        )
        st.stop()

    fecha_elegida = st.sidebar.selectbox(
        "День", fechas, index=len(fechas) - 1, key="home_fecha"
    )

    resumen = _cache_resumen_dia_con_tipico(engine, fecha_elegida, sucursal_filtro)
    comparacion = _cache_comparacion_semanal(engine, fecha_elegida, sucursal_filtro)

    # Сравнение с "типичным {день недели}" честно только для ЗАКРЫТОГО
    # дня -- для открытого это была бы выручка за ПОЛДНЯ против типичной
    # выручки за ПОЛНЫЙ день (то есть всегда "-80%", даже в отличный
    # день). Та же ловушка, что уже решена для окон "День к дню"/"Неделя
    # к неделе" справа -- здесь просто гасим цифры сравнения тем же
    # способом, а не повторяем проверку в каждом месте по отдельности.
    if not resumen["dia_cerrado"]:
        resumen["ventas_vs_tipico_pct"] = None
        resumen["ordenes_vs_tipico_pct"] = None
        resumen["cheque_vs_tipico_pct"] = None
        for cat in resumen["categorias"]:
            cat["tipico_pct"] = None
            cat["dif_pt"] = None

    # Заголовок -- ОДНОЙ строкой: точка (или "Todos El Molino", если все
    # точки вместе) - дата без года - день недели. Без отдельной строки
    # с датой и без подписи про базу данных под ней.
    dd_mm = dt.date.fromisoformat(resumen["fecha"]).strftime("%d.%m")
    st.title(f"🏠 {nombre_punto} - {dd_mm} - {resumen['dia_semana']}")

    # Неподписанный незакрытый день -- главная ловушка этой страницы: она
    # открывается на ПОСЛЕДНЕМ загруженном дне, а он запросто может
    # оказаться сегодняшним, выгруженным в середине дня. Цифры тогда
    # честные, но это цифры за ПОЛДНЯ -- без подписи они читаются как
    # обвал продаж вдвое.
    if not resumen["dia_cerrado"]:
        st.caption(
            f"⏳ Этот день ещё НЕ ЗАКРЫТ -- в Сан-Луис-Потоси сейчас "
            f"{tiempo.etiqueta()}, магазин ещё торгует, и в выгрузке "
            f"только часть дня. Цифры ниже -- неполные. Окна сравнения "
            f"справа это учитывают: они считают по последнему ЗАКРЫТОМУ "
            f"дню."
        )

    # Слева -- все цифры за день (в две строки: сначала общие цифры, потом
    # доли по категориям), справа -- два окна сравнения с прошлой неделей.
    # Всё в одну линию, впритык, без лишних промежутков.
    datos_col, cmp1_col, cmp2_col = st.columns([4, 2, 2])

    with datos_col:
        fila1 = st.columns(3)

        # "Типично для {день недели}" -- взвешенное среднее по тем же дням
        # недели за последние 90 дней (metrics.resumen_dia_con_tipico),
        # тот же метод, что и остальные прогнозы в этом файле. Без этого
        # цифра дня читается сама по себе -- непонятно, много это или мало
        # ИМЕННО для {день недели}, а не в среднем по всем дням сразу.
        # delta_color="off" (серый, без стрелки) при отклонении меньше
        # metrics._UMBRAL_DESVIACION_PCT (5%) -- иначе даже разница в 1-2%
        # красится в зелёный/красный, хотя это обычный шум дня, а не
        # тенденция; тот же порог, что уже используется в "Анализ дня".
        fila1[0].metric(
            "Продажи", f"{resumen['num_ordenes']:,}",
            delta=(f"{resumen['ordenes_vs_tipico_pct']:+.1f}% к типичному {resumen['dia_semana']}"
                   if resumen.get("ordenes_vs_tipico_pct") is not None else None),
            delta_color=metrics.delta_color_significativo(resumen.get("ordenes_vs_tipico_pct")),
        )
        if resumen.get("tipico_num_ordenes") is not None:
            fila1[0].caption(f"обычно ~{resumen['tipico_num_ordenes']:,.0f}")

        fila1[1].metric(
            "Выручка", f"{resumen['ventas_totales']:,.0f} $",
            delta=(f"{resumen['ventas_vs_tipico_pct']:+.1f}% к типичному {resumen['dia_semana']}"
                   if resumen.get("ventas_vs_tipico_pct") is not None else None),
            delta_color=metrics.delta_color_significativo(resumen.get("ventas_vs_tipico_pct")),
        )
        if resumen.get("tipico_ventas_totales") is not None:
            fila1[1].caption(f"обычно ~{resumen['tipico_ventas_totales']:,.0f} $")

        fila1[2].metric(
            "Ср. чек", f"{resumen['cheque_promedio']:,.0f} $",
            delta=(f"{resumen['cheque_vs_tipico_pct']:+.1f}% к типичному {resumen['dia_semana']}"
                   if resumen.get("cheque_vs_tipico_pct") is not None else None),
            delta_color=metrics.delta_color_significativo(resumen.get("cheque_vs_tipico_pct")),
        )
        if resumen.get("tipico_cheque_promedio") is not None:
            fila1[2].caption(f"обычно ~{resumen['tipico_cheque_promedio']:,.0f} $")

        serie_reciente = resumen.get("serie_reciente") or []
        if len(serie_reciente) >= 3:
            df_spark = pd.DataFrame(serie_reciente)
            fila1[0].altair_chart(
                _sparkline(df_spark, "num_ordenes", COLOR_TIPICO),
                width="stretch", key="spark_ordenes",
            )
            fila1[1].altair_chart(
                _sparkline(df_spark, "ventas_totales", COLOR_PRIMARIO),
                width="stretch", key="spark_ventas",
            )
            fila1[2].altair_chart(
                _sparkline(df_spark, "cheque_promedio", COLOR_SECUNDARIO),
                width="stretch", key="spark_cheque",
            )
            fila1[0].caption("последние 14 дней")
            fila1[1].caption("последние 14 дней")
            fila1[2].caption("последние 14 дней")

        fila2 = st.columns(len(resumen["categorias"]))
        for col, cat in zip(fila2, resumen["categorias"]):
            # Без "delta" именно здесь -- у категории нет "хорошо/плохо":
            # больше Panadería не значит лучше или хуже, просто другой
            # состав продаж. Streamlit красит delta зелёным/красным по
            # знаку, что выглядело бы как оценка, поэтому "типично" -- в
            # обычном тексте, без цвета и стрелки (тот же выбор, что и
            # раньше для этих карточек, теперь просто с добавленным
            # ориентиром).
            col.metric(cat["categoria"], f"{cat['pct']:.1f}%")
            tipico_txt = (
                f", обычно {cat['tipico_pct']:.1f}% ({cat['dif_pt']:+.1f} пт)"
                if cat.get("tipico_pct") is not None else ""
            )
            col.caption(f"{cat['monto']:,.0f} $" + tipico_txt)
            if len(serie_reciente) >= 3:
                campo = {
                    "Panadería": "panaderia_pct", "Pastelería": "pasteleria_pct",
                    "Café": "cafe_pct", "Остальное": "otras_pct",
                }.get(cat["categoria"])
                if campo:
                    col.altair_chart(
                        _sparkline(df_spark, campo, COLOR_TIPICO),
                        width="stretch", key=f"spark_{cat['categoria']}",
                    )

        # Какая категория сдвинулась заметнее остальных против типичного
        # дня -- один короткий вывод вместо того, чтобы сверять четыре
        # "(+N.N пт)" в подписях глазами. Ничего не выводит, если ни одна
        # категория не сдвинулась достаточно (см. metrics._UMBRAL_DIF_CATEGORIA_PT).
        mezcla = metrics.analizar_mezcla_categorias(resumen)
        if mezcla:
            direccion_cat = "выше" if mezcla["dif_pt"] > 0 else "ниже"
            texto_mezcla = (
                f"📊 Доля «{mezcla['categoria']}» сегодня заметно {direccion_cat} "
                f"обычного: {mezcla['pct']:.1f}% против типичных "
                f"{mezcla['tipico_pct']:.1f}% ({mezcla['dif_pt']:+.1f} п.т.)."
            )
            festivo_txt_cat = _texto_festivo(mezcla.get("festivo"))
            if festivo_txt_cat:
                texto_mezcla += " " + festivo_txt_cat
            st.caption(texto_mezcla)

    with cmp1_col:
        _panel_dia_vs_semana_pasada(comparacion["dia_vs_semana_pasada"])

    with cmp2_col:
        _panel_semana_vs_semana_pasada(comparacion["semana_vs_semana_pasada"])

    st.markdown("**Прогноз и факт по часам**")
    datos_hora = _cache_ventas_por_hora(engine, fecha_elegida, sucursal_filtro)
    if datos_hora["n_dias_promedio"]:
        st.caption(
            f"«Прогноз» -- по {datos_hora['n_dias_promedio']} прошлым дням "
            f"с тем же днём недели ({datos_hora['dia_semana']}): недавние "
            f"недели учтены сильнее старых, редкие всплески/провалы "
            f"сглажены."
        )
    df_hora = _grafico_por_hora(datos_hora, compacto=True, en_columnas=True)
    _bloque_analisis_dia(df_hora, fecha_elegida)

    # Кнопка вместо просто текста "иди туда руками" -- сама выставляет
    # точку и день на странице "Продажи по часам" (там подробнее: таблица
    # по часам, штуки отдельно) и переключает раздел. Запись в
    # session_state -- ТОЛЬКО через on_click-колбэк: виджет с key
    # "_pagina_actual" (боковой radio) уже создан в ЭТОМ прогоне к
    # моменту, когда рисуется эта кнопка -- прямая запись в
    # st.session_state здесь же упала бы с
    # StreamlitWidgetAlreadyInstantiatedError. on_click выполняется ДО
    # начала следующего прогона, когда виджеты ещё не созданы -- обычный
    # способ Streamlit для программной навигации.
    st.button(
        "🔍 Разобрать этот день по часам подробнее", key="btn_ir_a_horas",
        on_click=_ir_a_horas_callback, args=(opcion_sucursal, fecha_elegida),
    )

    st.caption(
        "Точка и день -- в фильтрах слева. Более подробный разбор -- на "
        "страницах «Продажи по часам» и «Топ товаров»."
    )

    # ---- Сравнение точек сегодня -------------------------------------------
    # Всегда ВСЕ точки сразу, вне зависимости от фильтра "Точка" выше --
    # тот же принцип, что и "Кофе по точкам" на странице "Доля напитков":
    # остальная страница акотает до одной точки (или суммирует все), а
    # здесь наоборот нужно видеть их рядом.
    if len(sucursales) > 1:
        st.subheader("Точки сегодня")
        por_sucursal = metrics.resumen_dia_por_sucursal(engine, fecha_elegida)
        if por_sucursal:
            st.dataframe(
                pd.DataFrame(por_sucursal).rename(columns={
                    "sucursal": "Точка", "num_ordenes": "Продажи",
                    "ventas_totales": "Выручка, $", "cheque_promedio": "Ср. чек, $",
                }),
                width="stretch", hide_index=True,
                column_config={
                    "Выручка, $": st.column_config.NumberColumn(format="%.0f $"),
                    "Ср. чек, $": st.column_config.NumberColumn(format="%.0f $"),
                },
            )


# =============================================================================
# Страница "Настройки" -- форма для ручного редактирования данных
# =============================================================================
def page_settings():
    st.title("⚙️ Настройки")
    st.caption(f"База данных: {_db_label()}")

    st.subheader("Слова для распознавания кофе")
    st.write(
        "Позиция считается «кофе», если её название содержит одно из этих "
        "слов И она лежит в группе меню CAFETERIA или FRAPPES. Добавь сюда "
        "новый напиток, как только он появится в меню -- ничего "
        "перезагружать не надо, дашборд пересчитает всё сразу же."
    )

    filas = _cache_coffee_keywords(engine, False)
    df = pd.DataFrame(filas)[["palabra"]].rename(columns={"palabra": "Слово"})

    edited = st.data_editor(
        df, num_rows="dynamic", width="stretch", key="coffee_keywords_editor",
    )

    if st.button("💾 Сохранить список", type="primary"):
        palabras = [str(v).strip() for v in edited["Слово"].tolist() if str(v).strip()]
        if not palabras:
            st.error("Список не может быть пустым.")
        else:
            replace_coffee_keywords(engine, palabras)
            # Список слов влияет на "это кофе или нет" везде -- сбрасываем
            # весь кэш, чтобы изменение было видно сразу, а не через 5 минут.
            st.cache_data.clear()
            st.success(f"Сохранено: {len(palabras)} слов(а). Открой «Дашборд» -- изменения уже там.")


# =============================================================================
# Страница "Дашборд"
# =============================================================================
# Четыре категории -- ВЕЗДЕ в этом фиксированном порядке (карточки,
# график, таблица, цвета): "Напитки" -- приглушённый серо-зелёный
# COLOR_TIPICO, та же роль, что и на странице "Продажи по часам" (общий
# фон/итог-конверт, на который накладываются цветные составляющие), цвет
# переиспользован, а не придуман новый. Кофе/Фраппе/Остальные напитки --
# три уже проверенных цвета (см. COLOR_FRAPPE выше по файлу).
_KATEGORII_NAPITKOV = ["Напитки", "Кофе", "Фраппе", "Остальные напитки"]
_COLOR_KATEGORII = {
    "Напитки": COLOR_TIPICO, "Кофе": COLOR_PRIMARIO,
    "Фраппе": COLOR_FRAPPE, "Остальные напитки": COLOR_SECUNDARIO,
}

# Три измерения одних и тех же четырёх категорий -- переключатель в
# фильтрах меняет ТОЛЬКО то, какие колонки df превращаются в "valor" для
# общего графика; сами категории и их цвета не меняются, поэтому глазами
# удобно сравнивать один и тот же график в разных измерениях.
_MEDIDAS = {
    "Доля, % от продаж": {
        "columnas": {"Напитки": "bebidas_pct", "Кофе": "cafe_pct",
                     "Фраппе": "frappe_pct", "Остальные напитки": "otras_bebidas_pct"},
        "formato": ".1f", "titulo_eje": "%",
    },
    "Выручка, $": {
        "columnas": {"Напитки": "bebidas_total", "Кофе": "cafe_total",
                     "Фраппе": "frappe_total", "Остальные напитки": "otras_bebidas_total"},
        "formato": ",.0f", "titulo_eje": "$",
    },
    "Штуки, шт": {
        "columnas": {"Напитки": "unidades_bebidas", "Кофе": "unidades_cafe",
                     "Фраппе": "unidades_frappe",
                     "Остальные напитки": "unidades_otras_bebidas"},
        "formato": ",.0f", "titulo_eje": "шт",
    },
}


def page_dashboard():
    st.title("🥤 Доля напитков: кофе, фраппе и остальное")
    st.caption(f"База данных: {_db_label()}")

    sucursales = _cache_sucursales(engine)
    if not sucursales:
        st.warning(
            "В базе пока нет данных. Запусти menu.py (или Start.bat) и "
            "сначала загрузи файлы Wansoft, потом обнови эту страницу."
        )
        st.stop()

    # ---- Боковая панель: фильтры -------------------------------------------
    st.sidebar.header("Фильтры")

    opcion_sucursal = st.sidebar.selectbox("Точка", ["Все точки"] + sucursales, index=0)
    sucursal_filtro = None if opcion_sucursal == "Все точки" else opcion_sucursal

    medida_label = st.sidebar.radio("Что показывать", list(_MEDIDAS.keys()), index=0)
    medida = _MEDIDAS[medida_label]

    granularidad_label = st.sidebar.radio(
        "Разбивка по периодам",
        ["По дням", "По декадам (10 дней)", "По кинсенам (15 дней)", "По месяцам"],
        index=0,  # по умолчанию -- дни: диапазон дат тоже по умолчанию
                  # короткий (последние 30 дней), там дни -- самая полезная
                  # разбивка
    )
    granularidad = {
        "По дням": "dia",
        "По декадам (10 дней)": "decada",
        "По кинсенам (15 дней)": "quincena",
        "По месяцам": "mes",
    }[granularidad_label]

    rango = _cache_rango_fechas(engine, sucursal_filtro)
    fecha_min = dt.date.fromisoformat(rango[0])
    fecha_max = dt.date.fromisoformat(rango[1])
    # По умолчанию -- последние 30 дней (не вся история): так при открытии
    # сразу видна свежая динамика, а не усреднённая картина за годы.
    fecha_default_desde = max(fecha_min, fecha_max - dt.timedelta(days=29))
    desde, hasta = st.sidebar.date_input(
        "Диапазон дат", value=(fecha_default_desde, fecha_max),
        min_value=fecha_min, max_value=fecha_max,
    )
    st.sidebar.caption(f"Данные есть с {fecha_min} по {fecha_max}")

    # ---- Данные -------------------------------------------------------------
    filas = _cache_serie_por_periodo(
        engine, granularidad, sucursal_filtro, desde.isoformat(), hasta.isoformat(),
    )
    if not filas:
        st.info("За этот диапазон дат нет данных.")
        st.stop()

    df = pd.DataFrame(filas)
    df["период"] = df["etiqueta"] + " " + df["anio"].astype(str).str[2:]

    # ---- Агрегаты за весь выбранный диапазон (для карточек) ------------------
    # Проценты для карточек считаем заново от СУММ (а не средним самих
    # процентов по периодам) -- иначе долгий диапазон исказился бы средним
    # арифметическим долей вместо честной доли от общей суммы.
    ventas_total = df["ventas_totales"].sum()
    dinero = {c: df[col].sum() for c, col in _MEDIDAS["Выручка, $"]["columnas"].items()}
    shtuki = {c: df[col].sum() for c, col in _MEDIDAS["Штуки, шт"]["columnas"].items()}
    pct_de_ventas = {c: (100 * v / ventas_total if ventas_total else 0.0) for c, v in dinero.items()}

    # ---- То же самое за ПРЕДЫДУЩИЙ период такой же длины -- чтобы у карточек
    # ниже была стрелка "выросло/упало", а не голая цифра без контекста.
    # Гранулярность здесь всегда "день" -- только чтобы точно просуммировать
    # произвольный диапазон; на график ниже это не влияет.
    dney_diapazon = (hasta - desde).days + 1
    prev_hasta = desde - dt.timedelta(days=1)
    prev_desde = prev_hasta - dt.timedelta(days=dney_diapazon - 1)
    filas_prev = _cache_serie_por_periodo(
        engine, "dia", sucursal_filtro, prev_desde.isoformat(), prev_hasta.isoformat(),
    )
    if filas_prev:
        df_prev = pd.DataFrame(filas_prev)
        ventas_prev = df_prev["ventas_totales"].sum()
        dinero_prev = {c: df_prev[col].sum() for c, col in _MEDIDAS["Выручка, $"]["columnas"].items()}
        shtuki_prev = {c: df_prev[col].sum() for c, col in _MEDIDAS["Штуки, шт"]["columnas"].items()}
        pct_prev = {c: (100 * v / ventas_prev if ventas_prev else 0.0) for c, v in dinero_prev.items()}
    else:
        dinero_prev = shtuki_prev = pct_prev = None

    # ---- KPI: 4 категории рядом, в измерении из фильтра, со стрелкой ---------
    st.subheader("Напитки в общих продажах")
    tarjetas = st.columns(4)
    for col, cat in zip(tarjetas, _KATEGORII_NAPITKOV):
        delta_txt = None
        if medida_label == "Доля, % от продаж":
            valor_txt = f"{pct_de_ventas[cat]:.1f}%"
            if pct_prev is not None:
                delta_txt = f"{pct_de_ventas[cat] - pct_prev[cat]:+.1f} пт"
        elif medida_label == "Выручка, $":
            valor_txt = f"{dinero[cat]:,.0f} $"
            if dinero_prev is not None and dinero_prev[cat]:
                delta_txt = f"{100 * (dinero[cat] - dinero_prev[cat]) / dinero_prev[cat]:+.1f}%"
        else:
            valor_txt = f"{shtuki[cat]:,.0f} шт"
            if shtuki_prev is not None and shtuki_prev[cat]:
                delta_txt = f"{100 * (shtuki[cat] - shtuki_prev[cat]) / shtuki_prev[cat]:+.1f}%"
        col.metric(cat, valor_txt, delta=delta_txt)
        if medida_label != "Выручка, $":
            col.caption(f"{dinero[cat]:,.0f} $")

    if filas_prev:
        st.caption(
            f"Продажи всего (все категории меню, не только напитки): "
            f"{ventas_total:,.0f} $. Стрелка -- сравнение с таким же по длине "
            f"периодом непосредственно перед выбранным "
            f"({prev_desde} -- {prev_hasta}, {dney_diapazon} дн.)."
        )
    else:
        st.caption(
            f"Продажи всего (все категории меню, не только напитки): "
            f"{ventas_total:,.0f} $. Для стрелки-сравнения нет данных за "
            f"предыдущий период такой же длины."
        )

    # ---- ОБЩИЙ график: 4 категории, измерение -- из фильтра слева -----------
    st.subheader(f"Динамика: {medida_label.lower()}")
    largo = df.melt(
        id_vars=["период", "periodo_inicio"],
        value_vars=list(medida["columnas"].values()),
        var_name="_col", value_name="valor",
    )
    col_a_cat = {v: k for k, v in medida["columnas"].items()}
    largo["categoria"] = largo["_col"].map(col_a_cat)

    grafico = alt.Chart(largo).mark_line(point=True, strokeWidth=2.5).encode(
        x=alt.X("periodo_inicio:T", title=None,
                axis=alt.Axis(labelExpr="timeFormat(datum.value, '%b %y')")),
        y=alt.Y("valor:Q", title=medida["titulo_eje"]),
        color=alt.Color(
            "categoria:N",
            scale=alt.Scale(domain=_KATEGORII_NAPITKOV,
                             range=[_COLOR_KATEGORII[c] for c in _KATEGORII_NAPITKOV]),
            legend=alt.Legend(title=None, orient="bottom"),
        ),
        strokeDash=alt.condition(
            alt.datum.categoria == "Напитки", alt.value([5, 4]), alt.value([1, 0]),
        ),
        tooltip=[
            alt.Tooltip("период:N", title="Период"),
            alt.Tooltip("categoria:N", title="Категория"),
            alt.Tooltip("valor:Q", title=medida_label, format=medida["formato"]),
        ],
    ).properties(height=380)
    st.altair_chart(grafico, width="stretch")
    st.caption(
        "«Напитки» (пунктирная линия) -- это ровно сумма трёх остальных: "
        "кофе + фраппе + остальные напитки, в любом измерении слева."
    )

    # ---- Когда именно продаются напитки: по часам дня -----------------------
    # Отвечает не на "сколько", а на "в какое время" -- та же идея, что
    # температура в присланном примере (жара -> тянет на холодное), только
    # без внешних данных: час чека уже есть в базе. Три категории, не
    # четыре -- "Напитки" здесь не нужна отдельной линией, это и так вся
    # высота столбика (кофе+фраппе+остальные).
    patron_horas = _cache_patron_horario_bebidas(
        engine, sucursal_filtro, desde.isoformat(), hasta.isoformat(),
    )
    if any(h["cafe_total"] or h["frappe_total"] or h["otras_bebidas_total"] for h in patron_horas):
        st.subheader("Когда продаются напитки, по часам дня")
        df_horas = pd.DataFrame(patron_horas)
        # Часы вне работы точек (ночь) всегда пустые -- обрезаем их, чтобы
        # график не тянулся от 0 до 23, а показывал только рабочий день.
        _HORA_DESDE, _HORA_HASTA = 6, 22
        df_horas = df_horas[
            (df_horas["hora"] >= _HORA_DESDE) & (df_horas["hora"] <= _HORA_HASTA)
        ]

        _KAT_HORAS = ["Кофе", "Фраппе", "Остальные напитки"]
        _COL_HORAS_PCT = {"Кофе": "cafe_total", "Фраппе": "frappe_total",
                           "Остальные напитки": "otras_bebidas_total"}
        if medida_label == "Штуки, шт":
            columnas_h = {"Кофе": "unidades_cafe", "Фраппе": "unidades_frappe",
                          "Остальные напитки": "unidades_otras_bebidas"}
            apilado, titulo_h, formato_h = "zero", "шт", ",.0f"
        elif medida_label == "Выручка, $":
            columnas_h = _COL_HORAS_PCT
            apilado, titulo_h, formato_h = "zero", "$", ",.0f"
        else:
            # "Доля, % от продаж" здесь считается иначе, чем на карточках
            # выше (там -- % от ВСЕХ продаж точки): по часам честнее
            # показать % от напитков ИМЕННО ЭТОГО часа -- так видно, как
            # МЕНЯЕТСЯ состав в течение дня, а не только когда людно.
            # stack="normalize" в Altair сам считает эту долю из сырых $.
            columnas_h = _COL_HORAS_PCT
            apilado, titulo_h, formato_h = "normalize", "% от напитков этого часа", ".1f"

        largo_horas = df_horas.melt(
            id_vars=["hora"], value_vars=list(columnas_h.values()),
            var_name="_col", value_name="valor",
        )
        col_a_cat_h = {v: k for k, v in columnas_h.items()}
        largo_horas["categoria"] = largo_horas["_col"].map(col_a_cat_h)
        orden_h = {"Кофе": 0, "Фраппе": 1, "Остальные напитки": 2}
        largo_horas["orden"] = largo_horas["categoria"].map(orden_h)

        grafico_horas = alt.Chart(largo_horas).mark_bar().encode(
            x=alt.X(
                "hora:O", title="Час", axis=alt.Axis(labelAngle=0),
                scale=alt.Scale(domain=list(range(_HORA_DESDE, _HORA_HASTA + 1))),
            ),
            y=alt.Y("valor:Q", stack=apilado, title=titulo_h),
            color=alt.Color(
                "categoria:N",
                scale=alt.Scale(domain=_KAT_HORAS,
                                 range=[_COLOR_KATEGORII[c] for c in _KAT_HORAS]),
                legend=alt.Legend(title=None, orient="bottom"),
            ),
            order=alt.Order("orden:Q"),
            tooltip=[
                alt.Tooltip("hora:O", title="Час"),
                alt.Tooltip("categoria:N", title="Категория"),
                alt.Tooltip("valor:Q", title=titulo_h, format=formato_h),
            ],
        ).properties(height=280)
        st.altair_chart(grafico_horas, width="stretch")

        if medida_label == "Доля, % от продаж":
            st.caption(
                "Здесь -- доля от выручки напитков В ЭТОТ КОНКРЕТНЫЙ час (не "
                "от общих продаж, как на карточках выше). Так видно, что "
                "состав меняется в течение дня -- например, если доля "
                "фраппе днём заметно выше, чем в вечерний час пик, значит "
                "фраппе берут не только потому, что людно, а именно в жару."
            )
        else:
            st.caption(
                "Столбики показывают, когда за день набегает выручка/штуки "
                "каждой категории -- не только сколько всего, но и в какие "
                "часы. Диапазон дат и точка -- из фильтров слева."
            )
    else:
        st.info(
            "Для этого диапазона нет строк с временем чека (hora_cierre) -- "
            "почасовой разбор недоступен. Перезагрузи те же файлы Wansoft "
            "через Start.bat -> пункт 1, это дозаполнит время без дублей."
        )

    # ---- Что именно продаётся внутри каждой категории ------------------------
    # Динамика и почасовой разбор выше отвечают "сколько" и "когда", но не
    # "ЧТО именно" -- если Фраппе выросло на 2 пт, это тянет один новый вкус
    # или рост равномерный по всему меню? Без этого ответа "выросло" --
    # наполовину бесполезная новость: непонятно, что закреплять в меню, а
    # что убирать.
    st.subheader("Что именно продаётся внутри каждой категории")
    top_por_categoria = _cache_top_platillos_bebidas(
        engine, sucursal_filtro, desde.isoformat(), hasta.isoformat(),
    )
    columnas_top = st.columns(3)
    _KAT_TOP = ["Кофе", "Фраппе", "Остальные напитки"]
    for col, cat in zip(columnas_top, _KAT_TOP):
        filas_cat = top_por_categoria[cat]
        with col:
            st.markdown(f"**{cat}**")
            if not filas_cat:
                st.caption("Нет продаж за этот диапазон.")
                continue
            df_top = pd.DataFrame(filas_cat)
            if medida_label == "Штуки, шт":
                col_valor, formato_top, titulo_top = "unidades", ",.0f", "шт"
            elif medida_label == "Доля, % от продаж":
                col_valor, formato_top, titulo_top = "pct_categoria", ".1f", f"% от «{cat}»"
            else:
                col_valor, formato_top, titulo_top = "ventas", ",.0f", "$"
            grafico_top = alt.Chart(df_top).mark_bar(
                color=_COLOR_KATEGORII[cat], cornerRadiusTopRight=3, cornerRadiusBottomRight=3,
            ).encode(
                x=alt.X(f"{col_valor}:Q", title=titulo_top),
                y=alt.Y("platillo:N", sort="-x", title=None),
                tooltip=[
                    alt.Tooltip("platillo:N", title="Позиция"),
                    alt.Tooltip("ventas:Q", title="Выручка, $", format=",.0f"),
                    alt.Tooltip("unidades:Q", title="Штук", format=",.0f"),
                    alt.Tooltip("pct_categoria:Q", title=f"% от «{cat}»", format=".1f"),
                ],
            ).properties(height=26 * len(df_top) + 20)
            st.altair_chart(grafico_top, width="stretch")
    st.caption(
        "Топ-6 позиций меню по выручке внутри каждой категории -- та же "
        "точка и диапазон дат, что и везде на странице. Помогает увидеть, "
        "тянет ли рост категории один продукт или он распределён по всему "
        "меню."
    )

    # ---- Таблица ---------------------------------------------------------------
    with st.expander("Таблица (данные графика выше, все измерения сразу)"):
        st.dataframe(
            df[["период", "ventas_totales",
                "bebidas_total", "bebidas_pct", "unidades_bebidas",
                "cafe_total", "cafe_pct", "cafe_pct_bebidas", "unidades_cafe",
                "frappe_total", "frappe_pct", "frappe_pct_bebidas", "unidades_frappe",
                "otras_bebidas_total", "otras_bebidas_pct", "otras_bebidas_pct_bebidas",
                "unidades_otras_bebidas"]]
            .rename(columns={
                "ventas_totales": "Продажи всего, $",
                "bebidas_total": "Напитки, $", "bebidas_pct": "Напитки, % от продаж",
                "unidades_bebidas": "Напитки, шт",
                "cafe_total": "Кофе, $", "cafe_pct": "Кофе, % от продаж",
                "cafe_pct_bebidas": "Кофе, % от напитков", "unidades_cafe": "Кофе, шт",
                "frappe_total": "Фраппе, $", "frappe_pct": "Фраппе, % от продаж",
                "frappe_pct_bebidas": "Фраппе, % от напитков", "unidades_frappe": "Фраппе, шт",
                "otras_bebidas_total": "Остальные напитки, $",
                "otras_bebidas_pct": "Остальные напитки, % от продаж",
                "otras_bebidas_pct_bebidas": "Остальные напитки, % от напитков",
                "unidades_otras_bebidas": "Остальные напитки, шт",
            }),
            width="stretch",
        )

    st.caption(
        "Источник: Wansoft 'Reporte Detalle De Ventas'. Список слов для "
        "распознавания кофе -- на странице «Настройки» слева. Фраппе "
        "определяется по группе меню FRAPPES, а не по ключевым словам."
    )

    # ---- Сравнение точек по кофе ---------------------------------------------
    # Единственный блок на странице, который НЕ подчиняется фильтру "Точка"
    # слева -- специально: остальная страница акотает до одной точки (или
    # суммирует все), а здесь наоборот нужно видеть точки РЯДОМ, чтобы
    # сравнить их между собой. Внизу страницы -- это сравнение читают
    # реже и после того, как посмотрели общую картину выше.
    if len(sucursales) > 1:
        st.subheader("Кофе по точкам")
        cafe_suc = _cache_cafe_por_sucursal(engine, desde.isoformat(), hasta.isoformat())
        if cafe_suc:
            df_suc = pd.DataFrame(cafe_suc)
            grafico_suc = alt.Chart(df_suc).mark_bar().encode(
                x=alt.X("cafe_pct_ventas:Q", title="Доля кофе в продажах точки, %"),
                y=alt.Y("sucursal:N", title=None, sort="-x"),
                color=alt.value(_COLOR_KATEGORII["Кофе"]),
                tooltip=[
                    alt.Tooltip("sucursal:N", title="Точка"),
                    alt.Tooltip("cafe_pct_ventas:Q", title="Доля кофе, %", format=".1f"),
                    alt.Tooltip("cafe_total:Q", title="Выручка кофе, $", format=",.0f"),
                    alt.Tooltip("unidades_cafe:Q", title="Кофе, шт", format=",.0f"),
                    alt.Tooltip("ventas_totales:Q", title="Продажи точки всего, $", format=",.0f"),
                ],
            ).properties(height=32 * len(df_suc) + 40)
            st.altair_chart(grafico_suc, width="stretch")

            st.dataframe(
                df_suc.rename(columns={
                    "sucursal": "Точка",
                    "cafe_pct_ventas": "Доля кофе, %",
                    "cafe_total": "Выручка кофе, $",
                    "unidades_cafe": "Кофе, шт",
                    "ventas_totales": "Продажи точки всего, $",
                }),
                width="stretch", hide_index=True,
                column_config={
                    "Доля кофе, %": st.column_config.NumberColumn(format="%.1f%%"),
                    "Выручка кофе, $": st.column_config.NumberColumn(format="%.0f $"),
                    "Кофе, шт": st.column_config.NumberColumn(format="%.0f"),
                    "Продажи точки всего, $": st.column_config.NumberColumn(format="%.0f $"),
                },
            )

            fila_pct_max = df_suc.loc[df_suc["cafe_pct_ventas"].idxmax()]
            fila_pct_min = df_suc.loc[df_suc["cafe_pct_ventas"].idxmin()]
            fila_unid_max = df_suc.loc[df_suc["unidades_cafe"].idxmax()]
            fila_unid_min = df_suc.loc[df_suc["unidades_cafe"].idxmin()]

            partes = []
            if fila_pct_max["sucursal"] != fila_pct_min["sucursal"]:
                partes.append(
                    f"по доле кофе в продажах {fila_pct_max['sucursal']} впереди на "
                    f"{fila_pct_max['cafe_pct_ventas'] - fila_pct_min['cafe_pct_ventas']:.1f} пт "
                    f"({fila_pct_max['cafe_pct_ventas']:.1f}% против "
                    f"{fila_pct_min['cafe_pct_ventas']:.1f}%)"
                )
            if fila_unid_max["sucursal"] != fila_unid_min["sucursal"]:
                partes.append(
                    f"по штукам {fila_unid_max['sucursal']} продал на "
                    f"{fila_unid_max['unidades_cafe'] - fila_unid_min['unidades_cafe']:,.0f} шт "
                    f"больше кофе, чем {fila_unid_min['sucursal']}"
                )
            if partes:
                st.caption("Итоговая разница: " + "; ".join(partes) + ".")

            st.caption(
                "Доля кофе -- от ВСЕХ продаж точки (не только напитков), чтобы "
                "сравнение не зависело от размера точки в деньгах. Диапазон "
                "дат -- из фильтра слева, но сама точка -- нет: здесь всегда "
                "все точки сразу, вне зависимости от выбора «Точка» выше."
            )


# =============================================================================
# Страница "Продажи по часам" -- прогноз против факта
# =============================================================================
def page_por_hora():
    st.title("🕐 Продажи по часам")
    st.caption(f"База данных: {_db_label()}")

    sucursales = _cache_sucursales(engine)
    if not sucursales:
        st.warning(
            "В базе пока нет данных. Запусти Start.bat и сначала загрузи "
            "файлы Wansoft, потом обнови эту страницу."
        )
        st.stop()

    st.sidebar.header("Фильтры")
    opcion_sucursal = st.sidebar.selectbox(
        "Точка", ["Все точки"] + sucursales, index=0, key="hora_sucursal"
    )
    sucursal_filtro = None if opcion_sucursal == "Все точки" else opcion_sucursal

    fechas = _cache_fechas_con_hora(engine, sucursal_filtro)
    if not fechas:
        st.info(
            "Для этой точки ещё нет данных с временем чека. Время "
            "чека программа стала сохранять недавно -- перезагрузи те же "
            "файлы Wansoft через Start.bat -> пункт 1 (это не создаст "
            "дублей, просто дозаполнит час у уже загруженных строк)."
        )
        st.stop()

    fecha_elegida = st.sidebar.selectbox(
        "День", fechas, index=len(fechas) - 1, key="hora_fecha",
    )

    datos = _cache_ventas_por_hora(engine, fecha_elegida, sucursal_filtro)

    st.subheader(f"{fecha_elegida} -- {datos['dia_semana']}")
    if datos["n_dias_promedio"]:
        st.caption(
            f"«Прогноз» -- по {datos['n_dias_promedio']} прошлым дням с "
            f"тем же днём недели ({datos['dia_semana']}), для которых есть "
            f"время чека: недавние недели учтены сильнее старых, редкие "
            f"всплески/провалы сглажены."
        )
    else:
        st.caption(
            "Прошлых дней с тем же днём недели и временем чека пока нет -- "
            "показан только факт."
        )

    df = _grafico_por_hora(datos)

    total_real = df["real"].sum()
    total_tipico = df["tipico"].sum() if datos["n_dias_promedio"] else None
    unid_real = df["real_unidades"].sum()
    unid_tipico = df["tipico_unidades"].sum() if datos["n_dias_promedio"] else None

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Выручка за день", f"{total_real:,.0f} $")
    if total_tipico:
        raznica = 100 * (total_real - total_tipico) / total_tipico
        c2.metric(
            "Прогноз выручки", f"{total_tipico:,.0f} $",
            delta=f"{raznica:+.1f}%",
        )
    c3.metric("Продано, шт", f"{unid_real:,.0f}")
    if unid_tipico:
        raznica_u = 100 * (unid_real - unid_tipico) / unid_tipico
        c4.metric(
            "Прогноз, шт", f"{unid_tipico:,.0f}",
            delta=f"{raznica_u:+.1f}%",
        )

    with st.expander("Таблица по часам"):
        st.dataframe(
            df[["час", "real", "tipico", "real_unidades", "tipico_unidades"]].rename(
                columns={
                    "real": "Факт, $", "tipico": "Прогноз, $",
                    "real_unidades": "Факт, шт", "tipico_unidades": "Прогноз, шт",
                }
            ),
            width="stretch",
        )

    _bloque_analisis_dia(df, fecha_elegida)


# =============================================================================
# Страница "Топ товаров" -- полная картина продаж, не только кофе
# =============================================================================
def page_top_productos():
    st.title("🏆 Топ товаров")
    st.caption(f"База данных: {_db_label()}")

    sucursales = _cache_sucursales(engine)
    if not sucursales:
        st.warning(
            "В базе пока нет данных. Запусти Start.bat и сначала загрузи "
            "файлы Wansoft, потом обнови эту страницу."
        )
        st.stop()

    st.sidebar.header("Фильтры")
    opcion_sucursal = st.sidebar.selectbox(
        "Точка", ["Все точки"] + sucursales, index=0, key="top_sucursal"
    )
    sucursal_filtro = None if opcion_sucursal == "Все точки" else opcion_sucursal

    rango = _cache_rango_fechas(engine, sucursal_filtro)
    fecha_min = dt.date.fromisoformat(rango[0])
    fecha_max = dt.date.fromisoformat(rango[1])
    desde, hasta = st.sidebar.date_input(
        "Диапазон дат", value=(fecha_min, fecha_max),
        min_value=fecha_min, max_value=fecha_max, key="top_rango",
    )

    # ---- Категории меню -------------------------------------------------
    st.subheader("Выручка по категориям меню")
    categorias = _cache_ventas_por_categoria(
        engine, sucursal_filtro, desde.isoformat(), hasta.isoformat(),
    )
    df_cat = pd.DataFrame(categorias)
    if not df_cat.empty:
        st.bar_chart(
            df_cat.set_index("categoria")[["ventas"]].rename(columns={"ventas": "Выручка, $"}),
            color=COLOR_PRIMARIO,
        )

    # ---- Топ позиций ------------------------------------------------------
    st.subheader("Топ-15 позиций по выручке")
    top = _cache_top_platillos(
        engine, sucursal_filtro, desde.isoformat(), hasta.isoformat(), 15,
    )
    df_top = pd.DataFrame(top)
    if df_top.empty:
        st.info("За этот диапазон дат нет данных.")
        st.stop()

    st.bar_chart(
        df_top.set_index("platillo")[["ventas"]].rename(columns={"ventas": "Выручка, $"}),
        color=COLOR_SECUNDARIO,
    )

    with st.expander("Таблица (топ-15)"):
        st.dataframe(
            df_top.rename(columns={
                "platillo": "Позиция", "grupo": "Категория",
                "ventas": "Выручка, $", "unidades": "Штук",
            }),
            width="stretch",
        )

    with st.expander("Таблица по всем категориям"):
        st.dataframe(
            df_cat.rename(columns={
                "categoria": "Категория", "ventas": "Выручка, $", "unidades": "Штук",
            }),
            width="stretch",
        )


# =============================================================================
# Страница "Планирование" -- Panadería: реальные продажи, прогноз и план
# производства (штуки). План пока не приходит ниоткуда автоматически --
# вводится вручную ниже и хранится в таблице plan_produccion (db.py).
# =============================================================================
def page_planificacion():
    st.title("📋 Планирование")
    st.caption(f"База данных: {_db_label()}")
    st.caption(
        "Только категория «Panadería» (выпечка), в штуках. Три ряда: "
        "реальные продажи (закрытые дни), прогноз (по истории того же дня "
        "недели -- тот же метод, что и на «Продажи по часам») и план "
        "производства (вводится вручную в таблице ниже -- отдельного "
        "источника плана пока нет)."
    )

    sucursales = _cache_sucursales(engine)
    if not sucursales:
        st.info(
            "Данных ещё нет -- сначала загрузи файлы Wansoft, потом обнови "
            "эту страницу."
        )
        st.stop()

    st.sidebar.header("Фильтры")
    opcion_sucursal = st.sidebar.selectbox(
        "Точка", ["Все точки"] + sucursales, index=0, key="plan_sucursal"
    )
    sucursal_filtro = None if opcion_sucursal == "Все точки" else opcion_sucursal

    # Диапазон дат этой ТОЧКИ, не всей базы -- у новых точек (например,
    # Concha & Cafe) история короче, и без min_value можно выбрать дни, для
    # которых у этой точки заведомо нет продаж (не баг -- точка тогда
    # ещё не работала или не продавала Panadería), но выглядит как дырка
    # в данных, если не подписано явно.
    rango = _cache_rango_fechas(engine, sucursal_filtro)
    fecha_min = dt.date.fromisoformat(rango[0])
    fecha_max = dt.date.fromisoformat(rango[1])
    # 20 дней факта + 7 дней прогноза -- по просьбе Романа: этого хватает
    # увидеть недавний тренд и спланировать ближайшую неделю, не перегружая
    # график лишней историей.
    hoy = tiempo.hoy()
    desde, hasta = st.sidebar.date_input(
        "Диапазон дат",
        value=(max(fecha_min, hoy - dt.timedelta(days=20)), hoy + dt.timedelta(days=7)),
        min_value=fecha_min,
        key="plan_rango",
    )
    st.sidebar.caption(f"Данные для этой точки есть с {fecha_min} по {fecha_max}")

    # ---- Загрузка производства -- плитка наверху, как в Dodo IS ------------
    # Додо IS выносит именно такую метрику (штук/чел-час) наверх экрана
    # плиткой с иконкой, а не прячет её в график ниже -- здесь так же:
    # одно число, которое сразу видно, не листая страницу. Пиковый час --
    # не среднее: для решения "хватает ли текущих 5/6 человек" важнее
    # самый нагруженный момент периода, а не размытое по всему дню
    # среднее.
    carga_horas_top = _cache_carga_por_hora_panaderia(
        engine, sucursal_filtro, desde.isoformat(), hasta.isoformat(),
    )
    df_carga_top = pd.DataFrame(carga_horas_top)
    df_carga_top = df_carga_top[df_carga_top["unidades"] > 0]

    # "Текущая" -- ЗА СЕГОДНЯ, за час, который идёт прямо сейчас (может
    # быть неполным -- час ещё не закрылся). "Идеальная" -- среднее по
    # всем рабочим часам за выбранный период: ориентир "обычной" нагрузки,
    # чтобы было с чем сравнить и пиковую, и текущую цифры, а не просто
    # смотреть на голое число без контекста.
    hora_actual = tiempo.ahora().hour
    carga_hoy = _cache_carga_por_hora_panaderia(
        engine, sucursal_filtro, hoy.isoformat(), hoy.isoformat(),
    )
    fila_actual = next((h for h in carga_hoy if h["hora"] == hora_actual), None)
    ideal = df_carga_top["unidades_por_persona"].mean() if not df_carga_top.empty else None

    col_pico, col_actual, col_ideal = st.columns(3)
    if not df_carga_top.empty:
        fila_pico = df_carga_top.loc[df_carga_top["unidades_por_persona"].idxmax()]
        col_pico.metric(
            "🏭 Пиковая загрузка, шт/чел-час",
            f"{fila_pico['unidades_por_persona']:.1f}",
            help=(
                f"Самый нагруженный час за выбранный период -- "
                f"{int(fila_pico['hora']):02d}:00 ({fila_pico['unidades']:,.0f} шт "
                f"Panadería, поделено на персонал этого дня недели). "
                f"Подробный разбор по всем часам -- ниже, в разделе "
                f"«Штук на человека в час»."
            ),
        )
    if fila_actual is not None and fila_actual["unidades"] > 0:
        col_actual.metric(
            "⚡ Текущая загрузка, шт/чел-час",
            f"{fila_actual['unidades_por_persona']:.1f}",
            help=(
                f"Штук Panadería за {hora_actual:02d}:00 сегодня, поделено на "
                f"персонал сегодняшнего дня недели -- час ещё может быть не "
                f"закрыт, цифра может вырасти."
            ),
        )
    else:
        col_actual.metric("⚡ Текущая загрузка, шт/чел-час", "—",
                           help="За текущий час пока нет продаж Panadería.")
    if ideal is not None:
        col_ideal.metric(
            "🎯 Идеальная загрузка, шт/чел-час",
            f"{ideal:.1f}",
            help=(
                "Среднее по всем рабочим часам за выбранный период -- "
                "ориентир 'обычной' нагрузки (не пиковой), чтобы было с чем "
                "сравнить текущую и пиковую цифры слева."
            ),
        )

    datos = _cache_panaderia_real_y_pronostico(
        engine, desde.isoformat(), hasta.isoformat(), sucursal_filtro,
    )
    df = pd.DataFrame(datos)
    for col in ("real_unidades", "pronostico_unidades"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    plan_filas = get_plan_produccion(engine, desde.isoformat(), hasta.isoformat())
    plan_por_fecha = {f["fecha"]: f["unidades_plan"] for f in plan_filas}
    # to_numeric, no solo .map(): con el dict de plan vacío (nada guardado
    # todavía), .map() a secas deja la columna en dtype "object" con NaN
    # sueltos -- y el editor de Streamlit los pinta como el texto "None"
    # en vez de una celda vacía. Forzar float64 corrige eso.
    df["unidades_plan"] = pd.to_numeric(df["fecha"].map(plan_por_fecha), errors="coerce")

    # ---- График: три ряда -----------------------------------------------
    st.subheader("Реальные продажи, прогноз и план")
    _NOMBRES_SERIE = {
        "real_unidades": "Факт",
        "pronostico_unidades": "Прогноз",
        "unidades_plan": "План",
    }
    largo = df.melt(
        id_vars=["fecha"], value_vars=list(_NOMBRES_SERIE),
        var_name="_col", value_name="valor",
    ).dropna(subset=["valor"])
    largo["serie"] = largo["_col"].map(_NOMBRES_SERIE)

    grafico = alt.Chart(largo).mark_line(
        interpolate="linear", point=alt.OverlayMarkDef(opacity=0.6, size=50),
    ).encode(
        x=alt.X("fecha:T", title="Дата"),
        y=alt.Y("valor:Q", title="Штук"),
        color=alt.Color(
            "serie:N",
            scale=alt.Scale(domain=["Факт", "Прогноз", "План"],
                             range=[COLOR_PRIMARIO, COLOR_TIPICO, COLOR_SECUNDARIO]),
            legend=alt.Legend(title=None, orient="bottom"),
        ),
        strokeDash=alt.StrokeDash(
            "serie:N",
            scale=alt.Scale(domain=["Факт", "Прогноз", "План"],
                             range=[[1, 0], [5, 4], [2, 2]]),
            legend=None,
        ),
        strokeWidth=alt.condition(alt.datum.serie == "Факт", alt.value(3), alt.value(2)),
        tooltip=[
            alt.Tooltip("fecha:T", title="Дата"),
            alt.Tooltip("serie:N", title="Ряд"),
            alt.Tooltip("valor:Q", title="Штук", format=",.0f"),
        ],
    ).properties(height=340)
    st.altair_chart(grafico, width="stretch")

    st.caption(
        "Прогноз -- взвешенное среднее по тем же дням недели за всю "
        "историю (недавние недели весят больше, резкие всплески/провалы "
        "сглажены -- тот же метод, что на «Продажи по часам»). Для будущих "
        "дней реальных продаж ещё нет -- видны только прогноз и план."
    )

    # ---- Таблица с вводом плана -------------------------------------------
    st.subheader("План производства -- ввод вручную")
    st.caption(
        "Впиши штуки на нужный день в столбец «План, шт» и нажми «Сохранить "
        "план». Пустая ячейка значит «плана ещё нет», а не «план -- ноль»."
    )
    df_editor = df[["fecha", "real_unidades", "pronostico_unidades", "unidades_plan"]].rename(
        columns={
            "fecha": "Дата", "real_unidades": "Факт, шт",
            "pronostico_unidades": "Прогноз, шт", "unidades_plan": "План, шт",
        }
    )
    edited = st.data_editor(
        df_editor,
        width="stretch", hide_index=True, key="plan_editor",
        disabled=["Дата", "Факт, шт", "Прогноз, шт"],
        column_config={
            "План, шт": st.column_config.NumberColumn(min_value=0, step=1),
        },
    )

    if st.button("💾 Сохранить план", type="primary"):
        filas = [
            {"fecha": row["Дата"], "unidades_plan": row["План, шт"]}
            for _, row in edited.iterrows()
        ]
        set_plan_produccion(engine, filas)
        st.cache_data.clear()
        st.success("План сохранён.")
        st.rerun()

    # ---- План-задание на день -- скачать -----------------------------------
    st.subheader("План-задание на день -- скачать")
    if sucursal_filtro is None:
        st.info(
            "Выбери конкретную точку в фильтрах слева -- план-задание "
            "составляется для ОДНОЙ точки (там своя кухня и своё "
            "производство), а не для «Все точки» сразу."
        )
    else:
        st.caption(
            "Готовое задание на смену: сколько штук печь всего, по часам и "
            "по позициям меню -- каждое число округлено ВВЕРХ до кратного "
            "6 (партия/лоток выпечки, а не поштучно -- лучше немного "
            "лишнего, чем недопечь целый лоток). Разбивка по часам и "
            "позициям -- из фактического распределения за 90 дней ДО "
            "выбранной даты; итог за день -- из ручного плана (см. таблицу "
            "выше), а если его нет -- из прогноза."
        )
        fecha_tarea = st.date_input(
            "На какое число план-задание", value=hoy + dt.timedelta(days=1),
            min_value=fecha_min, key="plan_tarea_fecha",
        )
        tarea = _cache_plan_tarea_dia(engine, fecha_tarea.isoformat(), sucursal_filtro, 10, 6)
        if tarea["total_dia"] is None:
            st.info("Для этой даты нет ни плана, ни прогноза -- задание составить не из чего.")
        else:
            st.write(
                f"Итого на {fecha_tarea.isoformat()}: **{tarea['total_dia_redondeado']} шт** "
                f"(кратно 6; источник -- {tarea['fuente_total']}; до округления -- "
                f"{tarea['total_dia']:.0f} шт)."
            )
            excel_bytes = _excel_plan_tarea(tarea, opcion_sucursal)
            st.download_button(
                "⬇️ Скачать план-задание (.xlsx)",
                data=excel_bytes,
                file_name=f"plan_tarea_{opcion_sucursal}_{fecha_tarea.isoformat()}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

    # ---- Разбивка по позициям ---------------------------------------------
    # Штуки, не выручка -- для персонала важно, сколько ШТУК нужно
    # сделать, а не сколько это стоит: конка и круассан с начинкой весят
    # разное время на изготовление даже при одинаковой выручке.
    st.subheader("Разбивка по позициям (топ-10 по штукам)")
    top_items = _cache_top_platillos_panaderia(
        engine, sucursal_filtro, desde.isoformat(), hasta.isoformat(), 10,
    )
    df_top = pd.DataFrame(top_items)
    if df_top.empty:
        st.info("За этот диапазон дат нет данных по Panadería.")
    else:
        grafico_top = alt.Chart(df_top).mark_bar().encode(
            x=alt.X("unidades:Q", title="Штук"),
            y=alt.Y("platillo:N", title=None, sort="-x"),
            color=alt.value(COLOR_PRIMARIO),
            tooltip=[
                alt.Tooltip("platillo:N", title="Позиция"),
                alt.Tooltip("unidades:Q", title="Штук", format=",.0f"),
                alt.Tooltip("pct_unidades:Q", title="Доля от штук Panadería, %", format=".1f"),
                alt.Tooltip("ventas:Q", title="Выручка, $", format=",.0f"),
            ],
        ).properties(height=32 * len(df_top) + 40)
        st.altair_chart(grafico_top, width="stretch")
        st.caption(
            "Топ-10 позиций Panadería по штукам за выбранный диапазон дат и "
            "точку. Разные позиции требуют разного времени на "
            "изготовление -- это тоже влияет на нужное количество людей, "
            "не только общая сумма штук."
        )

    # ---- Штуки по часам -----------------------------------------------------
    st.subheader("Продажи по часам")
    patron_horas = _cache_patron_horario_panaderia(
        engine, sucursal_filtro, desde.isoformat(), hasta.isoformat(),
    )
    df_horas = pd.DataFrame(patron_horas)
    df_horas = df_horas[df_horas["unidades"] > 0]
    if df_horas.empty:
        st.info(
            "Для этого диапазона нет строк с временем чека (hora_cierre) -- "
            "почасовой разбор недоступен."
        )
    else:
        grafico_horas = alt.Chart(df_horas).mark_bar().encode(
            x=alt.X("hora:O", title="Час", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("unidades:Q", title="Штук"),
            color=alt.value(COLOR_SECUNDARIO),
            tooltip=[
                alt.Tooltip("hora:O", title="Час"),
                alt.Tooltip("unidades:Q", title="Штук", format=",.0f"),
                alt.Tooltip("ventas:Q", title="Выручка, $", format=",.0f"),
            ],
        ).properties(height=280)
        st.altair_chart(grafico_horas, width="stretch")
        st.caption(
            "Сумма штук Panadería по часу закрытия чека за ВЕСЬ выбранный "
            "диапазон дат (не один день) -- показывает, в какие часы "
            "нужно больше людей на кассе/выкладке, отдельно от того, "
            "сколько продаётся за день целиком."
        )

    # ---- Штук на человека в час (загрузка производства) --------------------
    # Те же данные, что и в плитке "Пиковая загрузка" наверху страницы --
    # здесь подробный разбор по всем часам, там -- одно самое важное число.
    st.subheader("Штук на человека в час")
    df_carga = df_carga_top
    if df_carga.empty:
        st.info("Для этого диапазона нет данных, чтобы посчитать нагрузку на человека.")
    else:
        grafico_carga = alt.Chart(df_carga).mark_bar().encode(
            x=alt.X("hora:O", title="Час", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("unidades_por_persona:Q", title="Штук на человека"),
            color=alt.value(COLOR_PRIMARIO),
            tooltip=[
                alt.Tooltip("hora:O", title="Час"),
                alt.Tooltip("unidades_por_persona:Q", title="Штук на человека", format=".1f"),
                alt.Tooltip("unidades:Q", title="Всего штук в этот час", format=",.0f"),
            ],
        ).properties(height=280)
        st.altair_chart(grafico_carga, width="stretch")

        dias_norm = dias_dom = 0
        d = desde
        while d <= hasta:
            if d.weekday() == 6:
                dias_dom += 1
            else:
                dias_norm += 1
            d += dt.timedelta(days=1)
        personal_total = dias_norm * metrics.PERSONAL_ENTRE_SEMANA + dias_dom * metrics.PERSONAL_DOMINGO
        st.caption(
            f"Персонал считается фиксированным (пока нет графика смен в "
            f"базе): {metrics.PERSONAL_ENTRE_SEMANA} чел. в будни и "
            f"субботу, {metrics.PERSONAL_DOMINGO} чел. по воскресеньям, "
            f"одинаково на все часы дня. За выбранный период это "
            f"{dias_norm} будне-субботних + {dias_dom} воскресных дней = "
            f"{personal_total} человеко-дней. Столбик -- сколько штук в "
            f"среднем пришлось на одного человека в этот час за весь "
            f"период. Если реальная численность изменится -- поправь "
            f"PERSONAL_ENTRE_SEMANA / PERSONAL_DOMINGO в metrics.py."
        )

    # ---- Почему прогноз расходится с фактом ----------------------------------
    # Арифметика, не рассказ про причины бизнеса (см. docstring
    # analizar_desviacion_produccion) -- тренд (все дни сместились
    # одинаково) отличим от единичного дня (один день тянет среднее).
    st.subheader("Почему прогноз расходится с фактом")
    dias_para_analisis = df.astype(object).where(df.notna(), None).to_dict("records")
    analisis = metrics.analizar_desviacion_produccion(dias_para_analisis, "pronostico_unidades")
    if analisis is None:
        st.info("Пока недостаточно закрытых дней с прогнозом, чтобы сравнить.")
    else:
        direccion = "выше" if analisis["desviacion_pct"] > 0 else "ниже"
        st.write(
            f"За {analisis['n_dias']} закрытых дней реальные продажи "
            f"({analisis['total_real']:,.0f} шт) оказались на "
            f"{abs(analisis['desviacion_pct']):.1f}% {direccion} прогноза "
            f"({analisis['total_comparado']:,.0f} шт)."
        )
        if abs(analisis["tendencia_pct"]) >= 10:
            rost_padenie = "выросли" if analisis["tendencia_pct"] > 0 else "упали"
            st.write(
                f"Основная причина -- тренд: во второй половине диапазона "
                f"продажи {rost_padenie} в среднем на "
                f"{abs(analisis['tendencia_pct']):.1f}% по сравнению с "
                f"первой половиной. Прогноз строится по недавним неделям, "
                f"но смотрит назад -- при таком темпе он систематически "
                f"отстаёт (или опережает)."
            )
        else:
            st.write(
                f"Тренд по диапазону небольшой -- расхождение не общее, а "
                f"сконцентрировано в отдельных днях. Сильнее всего "
                f"разошлось {analisis['peor_dia']}: факт "
                f"{analisis['peor_dia_real']:,.0f} шт против прогноза "
                f"{analisis['peor_dia_comparado']:,.0f} шт."
            )
            festivo_txt = _texto_festivo(analisis.get("festivo_peor_dia"))
            if festivo_txt:
                st.write(festivo_txt)

        analisis_plan = metrics.analizar_desviacion_produccion(dias_para_analisis, "unidades_plan")
        if analisis_plan is not None:
            direccion_plan = "выше" if analisis_plan["desviacion_pct"] > 0 else "ниже"
            st.write(
                f"Относительно ВРУЧНУЮ введённого плана: факт на "
                f"{abs(analisis_plan['desviacion_pct']):.1f}% {direccion_plan} "
                f"плана ({analisis_plan['total_comparado']:,.0f} шт)."
            )

        st.caption(
            "Это разбор тех же цифр, что и на графике выше -- статистика "
            "(тренд/единичный день) плюс проверка по календарю мексиканских "
            "праздников (см. выше, если совпало); другие причины -- акция, "
            "погода, локальное событие -- в данных не видны."
        )


# =============================================================================
page = st.sidebar.radio(
    "Раздел",
    ["Главная", "Доля напитков", "Продажи по часам", "Топ товаров",
     "Планирование", "Настройки"],
    index=0,
    # key, а не просто index -- чтобы кнопка "Разобрать этот день по
    # часам" на Главной (см. page_home) могла переключить раздел
    # программно: она пишет в session_state["_pagina_actual"] ПЕРЕД
    # st.rerun(), и при следующем прогоне этот виджет читает значение
    # оттуда (обычный способ Streamlit -- виджет с key игнорирует index,
    # если в session_state уже что-то есть).
    key="_pagina_actual",
)
st.sidebar.divider()

# Данные обновляются сами каждые 5 минут (см. CACHE_TTL_SEGUNDOS выше), но
# если файлы только что перезагрузили через Start.bat, а этот дашборд уже
# был открыт -- эта кнопка обновляет сразу, не дожидаясь 5 минут и не
# перезапуская сам Dashboard.bat.
if st.sidebar.button("🔄 Обновить данные"):
    st.cache_data.clear()
    st.rerun()

# Какую базу читает ИМЕННО ЭТА вкладка. На "Главной" подписи про базу
# специально нет (заголовок там держим в одну строку), из-за чего легко
# решить, будто открытый на компьютере дашборд и открытый в телефоне
# смотрят в разные базы, хотя оба читают одно и то же облако. Здесь, в
# боковой панели, эта строка видна на ЛЮБОЙ странице и никому не мешает.
st.sidebar.caption(
    ("💾 Данные: локальный файл на этом компьютере"
     if engine.url.drivername.startswith("sqlite")
     else f"☁️ Данные: облако ({engine.url.host.split('.')[0]})")
)

# Часы пекарен -- видны на КАЖДОЙ странице. Весь дашборд считает "сегодня"
# и "закрыт ли день" только по этому времени (см. tiempo.py), поэтому оно
# должно быть на виду: открыв страницу из Москвы в три часа ночи, сразу
# видно, что в Сан-Луис-Потоси ещё вечер вчерашнего дня, и никакого
# противоречия в цифрах нет.
st.sidebar.caption(f"🕐 Сан-Луис-Потоси: {tiempo.etiqueta()}")

if page == "Главная":
    page_home()
elif page == "Доля напитков":
    page_dashboard()
elif page == "Продажи по часам":
    page_por_hora()
elif page == "Топ товаров":
    page_top_productos()
elif page == "Планирование":
    page_planificacion()
else:
    page_settings()
