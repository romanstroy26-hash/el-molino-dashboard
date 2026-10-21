"""Página «Витрина» del dashboard: наполняемость витрины по камере (vitrina_nivel.py) рядом с продажами и правилом регламента «полная витрина»."""

from __future__ import annotations

import datetime as dt

import altair as alt
import pandas as pd
import streamlit as st

import metrics
import tiempo
import vitrina_nivel as vn

PUNTO = "El Molino Ruso"            # камера стоит только там

AYUDA_PERIODO = ("Сколько последних дней показывать в нижней части страницы: таблица по дням, тепловая карта «день × час» и средняя наполненность по часам. "
                 "Выбор дня и недели выше от этого фильтра не зависит. Больше дней -- спокойнее картина, меньше -- виднее свежие изменения.")
AYUDA_UMBRAL = ("Наполненность, ниже которой витрину пора пополнять (100% = стол полный в обычный день). Что меняется: красная пунктирная линия на графике дня, "
                "цифра «Ниже порога» (минуты после утренней выкладки и до 21:00, когда витрина была ниже порога), таблица по дням, фразы о периоде и цвета "
                "тепловой карты. На недельный расчёт недополученной выручки НЕ влияет (там всегда считается всё, что ниже 70%).")
AYUDA_SENS = ("Допущение модели: насколько сильно низкая витрина отпугивает покупателей. 1,0 -- ниже 70% продажи падают пропорционально: при 35% наполненности "
              "теряется половина, при 0% -- всё. 0,5 -- вдвое мягче (покупатели берут то, что есть). 1,5 -- жёстче (при 35% теряется три четверти). "
              "Проверить значение по данным нельзя: витрина почти всегда полная. Меняет только «Недополученную выручку» в недельном блоке.")
AYUDA_SEMANA = ("За какой период считать недельный блок: «Последние 7 дней» (без сегодня) или календарная неделя с понедельника по воскресенье. Неполный сегодняшний день "
                "и дни, где нет данных кассы или камеры, в расчёт не входят -- число учтённых дней написано под показателями.")
AYUDA_DIA = ("Какой день показать на графике и в четырёх показателях ниже. Сегодняшний день ещё идёт, поэтому по умолчанию открывается последний закрытый.")
COLOR_NIVEL = "#B07E22"
COLOR_VENTAS = "#9AA5A0"
COLOR_UMBRAL = "#C0392B"


@st.cache_data(ttl=300, show_spinner=False)
def _dias(_engine, desde: str, hasta: str) -> dict:
    return vn.leer(_engine, PUNTO, dt.date.fromisoformat(desde), dt.date.fromisoformat(hasta))


@st.cache_data(ttl=300, show_spinner=False)
def _ventas_por_hora(_engine, fecha: str) -> list:
    return metrics.ventas_por_hora(_engine, fecha, sucursal=PUNTO)["horas"]


@st.cache_data(ttl=300, show_spinner=False)
def _ingresos_por_hora(_engine, desde: str, hasta: str) -> dict:
    """{fecha: {hora: $}} de Panadería + Pastelería (sin bolsas) del punto, solo días completos: lo que se vende de la mesa de pan."""
    from sqlalchemy import text

    import pronostico_horas

    parciales = pronostico_horas.dias_parciales(_engine, PUNTO, tiempo.hoy().isoformat())
    sql = ("SELECT fecha, CAST(substr(hora_cierre, 12, 2) AS INTEGER) AS h, SUM(importe) AS i FROM sales_lines WHERE sucursal = :s "
           "AND tipo_grupo IN ('PANADERIA', 'PASTELERIA')" + metrics.EXCLUIR_BOLSA_SQL + " AND hora_cierre IS NOT NULL AND hora_cierre != '' "
           "AND fecha >= :d AND fecha <= :h GROUP BY fecha, h")
    salida: dict = {}
    with _engine.connect() as conn:
        for r in conn.execute(text(sql), {"s": PUNTO, "d": desde, "h": hasta}).mappings():
            d = dt.date.fromisoformat(str(r["fecha"])[:10])
            if d not in parciales:
                salida.setdefault(d, {})[int(r["h"])] = float(r["i"] or 0.0)
    return salida


def _semanas(primero: dt.date, hoy: dt.date) -> list:
    """[(etiqueta, desde, hasta)]: los últimos 7 días y las semanas Пн–Вс con datos de la cámara, de la más nueva a la más vieja."""
    opciones = [(f"Последние 7 дней ({hoy - dt.timedelta(days=7):%d.%m}–{hoy - dt.timedelta(days=1):%d.%m})", hoy - dt.timedelta(days=7), hoy - dt.timedelta(days=1))]
    lunes = hoy - dt.timedelta(days=hoy.weekday())
    while lunes + dt.timedelta(days=6) >= primero:
        fin = lunes + dt.timedelta(days=6)
        opciones.append((f"Неделя {lunes:%d.%m}–{fin:%d.%m}" + (" (идёт)" if fin >= hoy else ""), lunes, min(fin, hoy)))
        lunes -= dt.timedelta(days=7)
    return opciones


def _bloque_semana(engine, hoy: dt.date, sensibilidad: float) -> None:
    """Resumen de una semana: % de llenado y qué parte de la venta no se logró por vitrina baja."""
    st.subheader("Неделя: наполненность и недополученная выручка")
    datos = _dias(engine, (hoy - dt.timedelta(days=60)).isoformat(), hoy.isoformat())
    if not datos:
        return
    opciones = _semanas(min(datos), hoy)
    elegida = st.selectbox("Неделя", range(len(opciones)), format_func=lambda i: opciones[i][0], key="vitrina_semana", help=AYUDA_SEMANA)
    _, desde, hasta = opciones[elegida]
    ingresos = _ingresos_por_hora(engine, (hoy - dt.timedelta(days=70)).isoformat(), hoy.isoformat())
    base = vn.base_de_ingresos(ingresos, hoy)
    semana = {d: t for d, t in datos.items() if desde <= d <= hasta}
    r = vn.resumen_semana(semana, ingresos, base, sensibilidad)
    if r is None:
        st.info("За эту неделю нет полных дней с данными камеры и кассы.")
        return
    c = st.columns(4)
    c[0].metric("Заполнение за неделю", f"{r['llenado']:.0f}%", delta=f"{r['tiempo_lleno']:.0%} времени ≥{vn.LLENA:.0f}%", delta_color="off",
                help="Средняя наполненность витрины после утренней выкладки и до 21:00 (100% = стол полный в обычный день). Под цифрой -- какую долю этого времени витрина была полной (70% и выше).")
    c[1].metric("Недополученная выручка", f"{r['perdida_pct']:.1%}", delta=f"≈ {r['perdida']:,.0f} $", delta_color="off",
                help="Какая часть возможной выручки (продано + недополучено) не получена из-за низкой витрины, и сколько это в долларах. Расчёт и допущения -- в блоке «Как считается» ниже.")
    c[2].metric("Продано", f"{r['ingreso']:,.0f} $", delta="Panadería + Pastelería", delta_color="off", help="Выручка кассы по хлебу и кондитерке за эти дни (без пакетов).")
    c[3].metric("Минут ниже 70%", f"{r['minutos_bajo']}", delta=f"вечер 19–21: {r['noche']:.0f}%" if r["noche"] is not None else None, delta_color="off",
                help="Сколько минут за неделю витрина (после выкладки, до 21:00) была ниже 70%. Под цифрой -- средняя наполненность с 19:00 до 21:00.")
    st.caption(f"Учтено дней: {r['dias']} (полные дни, по которым есть и камера, и касса). Считается по Panadería + Pastelería этой точки.")
    razbivka = pd.DataFrame([[nombre, _fmt(r[k]["llenado"]), f"{r[k]['perdida']:,.0f} $", f"{r[k]['pct']:.1%}", r[k]["minutos_bajo"]]
                             for nombre, k in (("До 20:30 (по регламенту витрина полная)", "antes"), ("20:30–21:00 (витрина сворачивается к закрытию)", "cierre"))],
                            columns=["Время", "Заполнение", "Недополучено, $", "Доля выручки", "Минут ниже 70%"])
    st.dataframe(razbivka, hide_index=True, width="stretch")
    st.caption("Разбивка складывается в общий показатель. Потери до 20:30 -- настоящие (витрина должна быть полной); с 20:30 до 21:00 витрина пустеет по плану "
               "(остаток распродаётся), так что там это скорее нормальное сворачивание.")
    with st.expander("Как считается и насколько этому можно верить"):
        st.write(
            f"• За каждые 5 минут, когда витрина (после выкладки и до 21:00) была ниже {vn.LLENA:.0f}%, берётся обычная выручка этого часа (среднее по таким же дням "
            f"недели за 8 недель) и вычитается та часть, которую витрина всё же продаёт: при {vn.LLENA:.0f}% и выше -- всё, при 35% -- половину, при 0% -- ничего "
            f"(чувствительность {sensibilidad:.1f}). Остаток -- недополученная выручка.\n\n"
            "• Это оценка с допущением: данные не позволяют проверить связь «пустая витрина → меньше продаж» -- витрина почти всегда полная, а в диапазоне "
            "70–100% продажи от наполненности не зависят. Чувствительность настраивается слева.\n\n"
            "• Последние полчаса перед закрытием витрина пустеет по плану (остаток распродаётся), но модель считает это тоже потерей -- реальные потери ближе к цифре, "
            "посчитанной до 20:30 (таблица выше показывает обе части отдельно).")
        det = pd.DataFrame([[f"{d:%d.%m}", f"{v['ingreso']:,.0f}", f"{v['perdida']:,.0f}", f"{v['perdida_antes']:,.0f}", f"{v['perdida_cierre']:,.0f}", v["minutos_bajo"]]
                            for d, v in sorted(r["detalle"].items())],
                           columns=["День", "Выручка, $", "Недополучено, $", "из них до 20:30", "из них 20:30–21:00", "Минут ниже 70%"])
        st.dataframe(det, hide_index=True, width="stretch")


def _hora_a_decimal(hora: str) -> float:
    h, m = hora.split(":")
    return int(h) + int(m) / 60.0


def _grafico_dia(trs: list, ventas: list, umbral: float):
    df = pd.DataFrame([{"hora": _hora_a_decimal(t["hora"]), "nivel": t["nivel"], "etiqueta": t["hora"]} for t in trs])
    eje_x = alt.X("hora:Q", title=None, scale=alt.Scale(domain=[6.5, 21.5]),
                  axis=alt.Axis(values=list(range(7, 22)), labelExpr="datum.value + ':00'"))
    linea = alt.Chart(df).mark_line(color=COLOR_NIVEL, strokeWidth=2.5, interpolate="monotone").encode(
        x=eje_x, y=alt.Y("nivel:Q", title="Наполненность, %", scale=alt.Scale(domain=[0, 100])),
        tooltip=[alt.Tooltip("etiqueta:N", title="Время"), alt.Tooltip("nivel:Q", title="Наполненность, %", format=".0f")])
    reglas = alt.Chart(pd.DataFrame({"y": [umbral, vn.LLENA]})).mark_rule(strokeDash=[5, 4], opacity=0.6).encode(
        y="y:Q", color=alt.value(COLOR_UMBRAL))
    capas = [linea, reglas]
    if ventas:
        dv = pd.DataFrame([{"hora": h["hora"] + 0.5, "шт": h["real_unidades"]} for h in ventas if 7 <= h["hora"] <= 21 and h["real_unidades"]])
        if not dv.empty:
            barras = alt.Chart(dv).mark_bar(color=COLOR_VENTAS, opacity=0.35, size=18).encode(
                x=eje_x, y=alt.Y("шт:Q", title="Продано за час, шт", axis=alt.Axis(orient="right")),
                tooltip=[alt.Tooltip("шт:Q", title="Продано, шт", format=".0f")])
            return alt.layer(barras, *capas).resolve_scale(y="independent").properties(height=300)
    return alt.layer(*capas).properties(height=300)


def _fmt(v, sufijo="%", cifras=0):
    return "—" if v is None else f"{v:.{cifras}f}{sufijo}"


def pagina(engine, sucursal) -> None:
    st.title("🥐 Витрина: наполненность по камере")
    if sucursal not in (None, PUNTO):
        st.info(f"Камера стоит на точке «{PUNTO}». Выберите её (или «Все точки») в фильтре слева.")
        return
    hoy = tiempo.hoy()
    st.sidebar.header("Фильтры")
    dias_n = st.sidebar.radio("Период", [7, 14, 30], index=1, format_func=lambda n: f"{n} дней", key="vitrina_periodo", help=AYUDA_PERIODO)
    umbral = st.sidebar.slider("Порог «пора выкладывать», %", 10, 80, int(vn.UMBRAL_BAJO), 5, key="vitrina_umbral", help=AYUDA_UMBRAL)
    sensibilidad = st.sidebar.slider("Как сильно пустая витрина снижает продажи", 0.5, 1.5, vn.SENSIBILIDAD, 0.1, key="vitrina_sens", help=AYUDA_SENS)
    with st.sidebar.expander("Что означают эти фильтры"):
        st.markdown(f"**Период.** {AYUDA_PERIODO}\n\n**Порог.** {AYUDA_UMBRAL}\n\n**Как сильно пустая витрина снижает продажи.** {AYUDA_SENS}\n\n"
                    f"**Неделя** (вверху страницы). {AYUDA_SEMANA}\n\n**День.** {AYUDA_DIA}")
    datos = _dias(engine, (hoy - dt.timedelta(days=dias_n)).isoformat(), hoy.isoformat())
    if not datos:
        st.info("Данных с камеры в базе пока нет. Программа «Vitrina» работает на компьютере в магазине; данные забирает задача синхронизации "
                "(sync_nube) на главном компьютере -- для этого на нём должен быть включён Tailscale. Первые дни появятся здесь в течение 10 минут после включения.")
        return

    _bloque_semana(engine, hoy, sensibilidad)
    st.divider()

    # --- последний день с данными (сегодняшний можно выбрать отдельно)
    fechas = sorted(datos)
    ultimo_completo = max((i for i, d in enumerate(fechas) if d != hoy), default=len(fechas) - 1)
    elegida = st.selectbox("День", fechas, index=ultimo_completo, help=AYUDA_DIA, format_func=lambda d: f"{d:%d.%m} ({'сегодня, ещё идёт' if d == hoy else metrics.DIAS_SEMANA_RU[d.weekday()]})")
    trs = datos[elegida]
    r = vn.resumen_dia(trs, umbral)
    st.subheader(f"{elegida:%d.%m.%Y}")
    c = st.columns(4)
    c[0].metric("Заполнена к", r["llena_en"] or "—", help="Первый момент, когда витрина достигла 70% и выше после утренней выкладки.")
    c[1].metric("Средняя (после выкладки)", _fmt(r["promedio"]), help="Среднее до 21:00, начиная с момента, когда витрина была заполнена.")
    c[2].metric("Вечер 19:00–21:00", _fmt(r["noche_promedio"]),
                delta=(f"{r['noche_llena_pct']:.0%} времени ≥{vn.LLENA:.0f}%" if r["noche_llena_pct"] is not None else None), delta_color="off",
                help="Правило регламента: витрина полная до закрытия.")
    c[3].metric("Ниже порога", f"{r['minutos_bajo']} мин", help=f"Минут с наполненностью ниже {umbral}% после выкладки и до 21:00.")
    st.altair_chart(_grafico_dia(trs, _ventas_por_hora(engine, elegida.isoformat()), umbral), width="stretch")
    st.caption(f"Линия -- наполненность витрины (100% = стол полный в обычный день), красные пунктиры -- порог {umbral}% и «полная» {vn.LLENA:.0f}%; серые столбики -- "
               f"продано за час (касса). На закрытии ({r['cierre_hora']}) оставалось {r['cierre']:.0f}%.")

    # --- период
    st.subheader(f"Последние {dias_n} дней")
    completos = {d: t for d, t in datos.items() if d != hoy}
    if not completos:
        st.info("Пока только сегодняшний день -- сравнение появится завтра.")
        return
    resumenes = {d: vn.resumen_dia(t, umbral) for d, t in completos.items()}
    for frase in vn.frases_del_periodo(resumenes, umbral):
        st.write("• " + frase)
    tabla = pd.DataFrame([[f"{d:%d.%m}", r2["llena_en"] or "—", _fmt(r2["promedio"]), _fmt(r2["minimo"]), r2["minutos_bajo"],
                           _fmt(r2["noche_promedio"]), f"{r2['noche_llena_pct']:.0%}" if r2["noche_llena_pct"] is not None else "—",
                           f"{r2['cierre']:.0f}% ({r2['cierre_hora']})"] for d, r2 in sorted(resumenes.items(), reverse=True) if r2],
                         columns=["День", "Заполнена к", "Средняя", "Минимум", "Мин. ниже порога", "Вечер 19–21", "Вечер ≥70% времени", "На закрытии"])
    st.dataframe(tabla, hide_index=True, width="stretch")

    calor = vn.mapa_calor(completos)
    dc = pd.DataFrame([{"День": f"{d:%d.%m}", "Час": h, "Наполненность, %": v} for d, horas in calor.items() for h, v in horas.items() if 7 <= h <= 21])
    if not dc.empty:
        orden = [f"{d:%d.%m}" for d in sorted(calor)]
        mapa = alt.Chart(dc).mark_rect().encode(
            x=alt.X("Час:O", title="Час", axis=alt.Axis(labelAngle=0)), y=alt.Y("День:O", sort=orden, title=None),
            color=alt.Color("Наполненность, %:Q", scale=alt.Scale(domain=[0, umbral, vn.LLENA, 100], range=["#C0392B", "#E6A23C", "#F3E3A8", "#4C9F70"]),
                            legend=alt.Legend(orient="bottom")),
            tooltip=["День", "Час", alt.Tooltip("Наполненность, %:Q", format=".0f")]).properties(height=max(120, 22 * len(orden)))
        st.altair_chart(mapa, width="stretch")
        st.caption("Каждая клетка -- средняя наполненность витрины в этот час этого дня. Красное/оранжевое -- пора выкладывать, зелёное -- полная.")

    ph = vn.por_hora(completos)
    if ph:
        dph = pd.DataFrame([{"Час": h, "Среднее, %": v} for h, v in ph.items() if 7 <= h <= 21])
        st.altair_chart(alt.Chart(dph).mark_bar(color=COLOR_NIVEL).encode(
            x=alt.X("Час:O", axis=alt.Axis(labelAngle=0)), y=alt.Y("Среднее, %:Q", scale=alt.Scale(domain=[0, 100])),
            tooltip=["Час", alt.Tooltip("Среднее, %:Q", format=".0f")]).properties(height=200), width="stretch")
        st.caption("Средняя наполненность по часам за период (после утренней выкладки). Провал в каком-то часе -- время, когда выкладка не успевает за продажами.")
