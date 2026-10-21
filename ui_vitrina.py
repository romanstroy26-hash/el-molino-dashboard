"""Página «Витрина» del dashboard: наполняемость витрины по камере (vitrina_nivel.py) рядом с продажами и правилом регламента «полная витрина до 20:30»."""

from __future__ import annotations

import datetime as dt

import altair as alt
import pandas as pd
import streamlit as st

import metrics
import tiempo
import vitrina_nivel as vn

PUNTO = "El Molino Ruso"            # камера стоит только там
COLOR_NIVEL = "#B07E22"
COLOR_VENTAS = "#9AA5A0"
COLOR_UMBRAL = "#C0392B"


@st.cache_data(ttl=300, show_spinner=False)
def _dias(_engine, desde: str, hasta: str) -> dict:
    return vn.leer(_engine, PUNTO, dt.date.fromisoformat(desde), dt.date.fromisoformat(hasta))


@st.cache_data(ttl=300, show_spinner=False)
def _ventas_por_hora(_engine, fecha: str) -> list:
    return metrics.ventas_por_hora(_engine, fecha, sucursal=PUNTO)["horas"]


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
    dias_n = st.sidebar.radio("Период", [7, 14, 30], index=1, format_func=lambda n: f"{n} дней", key="vitrina_periodo")
    umbral = st.sidebar.slider("Порог «пора выкладывать», %", 10, 80, int(vn.UMBRAL_BAJO), 5, key="vitrina_umbral")
    datos = _dias(engine, (hoy - dt.timedelta(days=dias_n)).isoformat(), hoy.isoformat())
    if not datos:
        st.info("Данных с камеры в базе пока нет. Программа «Vitrina» работает на компьютере в магазине; данные забирает задача синхронизации "
                "(sync_nube) на главном компьютере -- для этого на нём должен быть включён Tailscale. Первые дни появятся здесь в течение 10 минут после включения.")
        return

    # --- последний день с данными (сегодняшний можно выбрать отдельно)
    fechas = sorted(datos)
    ultimo_completo = max((i for i, d in enumerate(fechas) if d != hoy), default=len(fechas) - 1)
    elegida = st.selectbox("День", fechas, index=ultimo_completo, format_func=lambda d: f"{d:%d.%m} ({'сегодня, ещё идёт' if d == hoy else metrics.DIAS_SEMANA_RU[d.weekday()]})")
    trs = datos[elegida]
    r = vn.resumen_dia(trs, umbral)
    st.subheader(f"{elegida:%d.%m.%Y}")
    c = st.columns(4)
    c[0].metric("Заполнена к", r["llena_en"] or "—", help="Первый момент, когда витрина достигла 70% и выше после утренней выкладки.")
    c[1].metric("Средняя (после выкладки)", _fmt(r["promedio"]), help="Среднее до 20:30, начиная с момента, когда витрина была заполнена.")
    c[2].metric("Вечер 19:00–20:30", _fmt(r["noche_promedio"]),
                delta=(f"{r['noche_llena_pct']:.0%} времени ≥{vn.LLENA:.0f}%" if r["noche_llena_pct"] is not None else None), delta_color="off",
                help="Правило регламента: витрина полная до 20:30.")
    c[3].metric("Ниже порога", f"{r['minutos_bajo']} мин", help=f"Минут с наполненностью ниже {umbral}% после выкладки и до 20:30.")
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
                         columns=["День", "Заполнена к", "Средняя", "Минимум", "Мин. ниже порога", "Вечер 19–20:30", "Вечер ≥70% времени", "На закрытии"])
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
