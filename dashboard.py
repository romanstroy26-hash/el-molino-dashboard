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
  - "Доля кофе"      -- фильтры (точка, период, диапазон дат) -> графики
    доли кофе в продажах.
  - "Продажи по часам" -- то же самое, что на главной, но с выбором любого
    дня и точки (детальный разбор конкретного дня).
  - "Топ товаров"    -- какие позиции меню и категории приносят больше
    всего выручки за период (полная картина продаж, не только кофе).
  - "Настройки"      -- форма: список слов для распознавания кофе. Изменения
    сохраняются в базу и сразу видны на дашборде (никакого "запусти
    скрипт заново").

Ничего здесь не считает "по-своему" -- вся математика в metrics.py,
дашборд только показывает и собирает ввод пользователя.
"""

import datetime as dt
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from db import DEFAULT_DB_PATH, get_coffee_keywords, get_engine, replace_coffee_keywords
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

# Третий цвет -- для страницы "Доля кофе", где кофе, фраппе и остальные
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
        "fact": "#B07E22", "texto_pico": "#241C10", "fondo": "#FBF8F2",
        "eje_linea": "#D8CFBE", "eje_etiqueta": "#5B5140", "grid": "#EAE4D6",
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
# карточками, а не просто линией по краю, плюс акцентный (золотой) цвет
# у цифр KPI, чтобы они сразу цеплялись взглядом на любой странице).
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
        color: #B07E22;
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
def _cache_top_platillos(_engine, sucursal, desde, hasta, n):
    return metrics.top_platillos(_engine, sucursal=sucursal, desde=desde, hasta=hasta, n=n)


@st.cache_data(ttl=CACHE_TTL_SEGUNDOS, show_spinner=False)
def _cache_ventas_por_categoria(_engine, sucursal, desde, hasta):
    return metrics.ventas_por_categoria(_engine, sucursal=sucursal, desde=desde, hasta=hasta)


@st.cache_data(ttl=CACHE_TTL_SEGUNDOS, show_spinner=False)
def _cache_resumen_dia(_engine, fecha, sucursal):
    return metrics.resumen_dia(_engine, fecha, sucursal=sucursal)


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


def _texto_analisis_dia(a: dict) -> tuple[str, list[str]]:
    """Превращает диагностику из metrics.analizar_desempeno_por_hora в текст
    на русском -- пороги и арифметика (что считать 'сосредоточенным'
    провалом, что списать на трафик, а что на средний чек) там, здесь
    только формулировки."""
    if a["estado"] == "por_encima":
        resumen = (
            f"День отработал **выше прогноза на {a['delta_pct']:+.1f}%** по "
            f"выручке ({a['total_real']:,.0f} $ против {a['total_tipico']:,.0f} $ "
            f"ожидаемых) -- заметных проблем не видно."
        )
        recomendaciones = [
            "Посмотри, что сработало лучше обычного (акция, погода, "
            "мероприятие по соседству) -- если это можно повторить, "
            "попробуй специально в следующий такой же день недели.",
        ]
        return resumen, recomendaciones

    if a["estado"] == "en_linea":
        resumen = (
            f"Выручка примерно на уровне прогноза ({a['delta_pct']:+.1f}%, "
            f"{a['total_real']:,.0f} $ против {a['total_tipico']:,.0f} $) -- "
            f"заметных отклонений, которые стоило бы разбирать, нет."
        )
        return resumen, []

    # por_debajo
    partes = [
        f"Выручка **ниже прогноза на {abs(a['delta_pct']):.1f}%** "
        f"({a['total_real']:,.0f} $ вместо ожидаемых {a['total_tipico']:,.0f} $)."
    ]
    recomendaciones: list[str] = []

    if a["delta_unid_pct"] is not None:
        du = a["delta_unid_pct"]
        if du <= -_UMBRAL_ANALISIS_TRAFICO:
            # Штук тоже заметно меньше плана -- дело в количестве
            # покупателей, а не в том, сколько каждый оставил в кассе.
            partes.append(
                f"Штук продано тоже меньше плана ({du:+.1f}%) -- похоже на "
                f"нехватку покупателей (трафика), а не на снижение среднего "
                f"чека."
            )
            recomendaciones.append(
                "Проверь трафик за день: не было ли перебоев с кассой или "
                "меню, весь ли зал/точка работали по расписанию; попробуй "
                "локальную рекламу или акцию именно на этот день недели."
            )
        elif du >= _UMBRAL_ANALISIS_TRAFICO:
            # Штук ЗАМЕТНО БОЛЬШЕ плана, а денег всё равно меньше -- значит,
            # средний чек просел даже сильнее, чем видно по одной выручке
            # (иначе, с таким приростом продаж, выручка тоже должна была
            # вырасти). Раньше эта ветка ошибочно называла такое "почти по
            # плану", хотя штуки могли быть выше плана хоть на 30% --
            # текст должен явно называть, что штук стало больше, а не
            # "примерно как обычно".
            partes.append(
                f"При этом штук продали БОЛЬШЕ плана ({du:+.1f}%), а денег "
                f"всё равно меньше -- значит, средний чек просел сильнее, "
                f"чем кажется по одной выручке."
            )
            recomendaciones.append(
                "Проверь средний чек: не увеличилось ли число скидок, не "
                "подешевел ли состав заказов (меньше допродаж десерта или "
                "напитка), не сместился ли спрос на более дешёвые позиции "
                "меню, несмотря на рост числа продаж."
            )
        else:
            # Штуки в пределах +-5% от плана -- действительно "как обычно",
            # тогда просевшая выручка объясняется средним чеком.
            partes.append(
                f"При этом штук продано почти по плану ({du:+.1f}%) -- "
                f"значит, просел средний чек, а не число покупателей."
            )
            recomendaciones.append(
                "Проверь средний чек: не увеличилось ли число скидок, не "
                "просели ли допродажи (десерт или напиток к основному "
                "заказу), не сместился ли спрос на более дешёвые позиции "
                "меню."
            )

    if a["horas_criticas"]:
        if a["concentrado"]:
            horas_txt = ", ".join(f"{h['hora']:02d}:00" for h in a["horas_criticas"])
            partes.append(
                f"Провал сосредоточен в основном в {horas_txt} -- на "
                f"остальные часы приходится меньшая часть отставания."
            )
            recomendaciones.append(
                f"Разбери отдельно {horas_txt}: не было ли в это время "
                f"меньше персонала, задержки открытия, дефицита позиций "
                f"меню или очереди, из-за которой уходили клиенты."
            )
        else:
            partes.append(
                "Отставание распределено почти по всему дню, а не в "
                "отдельные часы -- вероятно, дело в общем факторе (погода, "
                "посещаемость района, конкуренты), а не в разовом сбое в "
                "конкретное время."
            )
            recomendaciones.append(
                "Сравни с «Неделя к неделе» на Главной -- если предыдущие "
                "дни тоже ниже прогноза, это похоже на тренд, а не на "
                "случайность одного дня."
            )

    return " ".join(partes), recomendaciones


def _bloque_analisis_dia(df: pd.DataFrame) -> None:
    """Короткая справка внизу страницы (после графика 'Прогноз и факт'):
    насколько день отклонился от прогноза, почему, и что с этим делать.
    Ничего не выводит, если пронозировать было не из чего (см.
    metrics.analizar_desempeno_por_hora)."""
    analisis = metrics.analizar_desempeno_por_hora(df.to_dict("records"))
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

    resumen = _cache_resumen_dia(engine, fecha_elegida, sucursal_filtro)
    comparacion = _cache_comparacion_semanal(engine, fecha_elegida, sucursal_filtro)

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
        fila1[0].metric("Продажи", f"{resumen['num_ordenes']:,}")
        fila1[1].metric("Выручка", f"{resumen['ventas_totales']:,.0f} $")
        fila1[2].metric("Ср. чек", f"{resumen['cheque_promedio']:,.0f} $")

        fila2 = st.columns(len(resumen["categorias"]))
        for col, cat in zip(fila2, resumen["categorias"]):
            # Без "delta" -- это не сравнение с прошлой датой, а просто
            # сумма за эту категорию за тот же день. Раньше сумма стояла
            # третьим параметром st.metric(), а это как раз "дельта" --
            # Streamlit сам рисует стрелочку и красит в зелёный при
            # положительном числе, что выглядело как "рост", хотя
            # сравнивать было не с чем.
            col.metric(cat["categoria"], f"{cat['pct']:.1f}%")
            col.caption(f"{cat['monto']:,.0f} $")

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
    _bloque_analisis_dia(df_hora)

    st.caption(
        "Точка и день -- в фильтрах слева. Более подробный разбор -- на "
        "страницах «Продажи по часам» и «Топ товаров»."
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
        index=3,  # по умолчанию -- месяцы: удобнее всего смотреть динамику
                  # долей за долгий период
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
    desde, hasta = st.sidebar.date_input(
        "Диапазон дат", value=(fecha_min, fecha_max),
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

    st.caption(
        "«Напитки» здесь -- это группы меню CAFETERIA и FRAPPES (кофе, чай, "
        "матча, фраппе...), без учёта выпечки и бутилированных REFRESCOS. "
        "«Кофе», «Фраппе» и «Остальные напитки» НЕ пересекаются -- кофейный "
        "фраппе (например, F. Moka + Espresso) учтён только в «Кофе» -- "
        "поэтому втроём они в точности складываются в «Напитки»."
    )

    # ---- Агрегаты за весь выбранный диапазон (для карточек) ------------------
    # Проценты для карточек считаем заново от СУММ (а не средним самих
    # процентов по периодам) -- иначе долгий диапазон исказился бы средним
    # арифметическим долей вместо честной доли от общей суммы.
    ventas_total = df["ventas_totales"].sum()
    dinero = {c: df[col].sum() for c, col in _MEDIDAS["Выручка, $"]["columnas"].items()}
    shtuki = {c: df[col].sum() for c, col in _MEDIDAS["Штуки, шт"]["columnas"].items()}
    pct_de_ventas = {c: (100 * v / ventas_total if ventas_total else 0.0) for c, v in dinero.items()}

    # ---- KPI: 4 категории рядом, в измерении из фильтра ----------------------
    st.subheader("Напитки в общих продажах")
    tarjetas = st.columns(4)
    for col, cat in zip(tarjetas, _KATEGORII_NAPITKOV):
        if medida_label == "Доля, % от продаж":
            valor_txt = f"{pct_de_ventas[cat]:.1f}%"
        elif medida_label == "Выручка, $":
            valor_txt = f"{dinero[cat]:,.0f} $"
        else:
            valor_txt = f"{shtuki[cat]:,.0f} шт"
        col.metric(cat, valor_txt)
    st.caption(f"Продажи всего (все категории меню, не только напитки): {ventas_total:,.0f} $")

    if dinero["Фраппе"]:
        st.caption(
            f"Кофе : Фраппе = {dinero['Кофе'] / dinero['Фраппе']:.1f} : 1 "
            f"(во сколько раз выручка кофе больше выручки фраппе)."
        )
    else:
        st.caption("За выбранный период фраппе не продавались -- соотношение посчитать не из чего.")

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

    _bloque_analisis_dia(df)


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
page = st.sidebar.radio(
    "Раздел",
    ["Главная", "Доля кофе", "Продажи по часам", "Топ товаров", "Настройки"],
    index=0,
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
elif page == "Доля кофе":
    page_dashboard()
elif page == "Продажи по часам":
    page_por_hora()
elif page == "Топ товаров":
    page_top_productos()
else:
    page_settings()
