"""Interfaz del plan de producción (página «Планирование» del dashboard): plan del día, planes semanales de Panadería y Decoración,
pestañas «Обучение системы» y «Остатки». La lógica de cálculo vive en plan_propio.py, plan_semanal.py, pronostico.py y aprendizaje_plan.py
(puros, con tests); aquí solo se pinta y se recoge lo que escribe el usuario. Se extrajo de dashboard.py sin cambiar su comportamiento."""

import datetime as dt
from pathlib import Path

import pandas as pd
import streamlit as st

import clima
import tiempo
from db import get_merma, get_sobrantes, set_merma_dia, set_sobrantes

PUNTO_WHATSAPP = "El Molino Ruso"        # el grupo «Ventas El Molino» solo reporta la merma de este punto

CACHE_TTL_SEGUNDOS = 300


@st.cache_data(ttl=CACHE_TTL_SEGUNDOS, show_spinner=False)
def _cache_serie_diaria(_engine, sucursal):
    import plan_propio
    import pronostico
    return pronostico.serie_diaria(_engine, sucursal, excluir=plan_propio.dias_incompletos(_engine, sucursal, tiempo.hoy()))


@st.cache_data(ttl=3 * 3600, show_spinner="Загружаю погоду...")
def _cache_temperaturas(desde, hoy):
    return clima.temperaturas(dt.date.fromisoformat(desde), dt.date.fromisoformat(hoy))


def _temperaturas_para(engine, sucursal, hoy: dt.date) -> dict:
    """Temperaturas del historial y de los próximos días; sin internet {} (y no se recuerda el vacío: la próxima vez se reintenta)."""
    serie = _cache_serie_diaria(engine, sucursal)
    temps = _cache_temperaturas(min(serie).isoformat(), hoy.isoformat()) if serie else {}
    if serie and not temps:
        _cache_temperaturas.clear()
    return temps


@st.cache_data(ttl=CACHE_TTL_SEGUNDOS, show_spinner="Считаю прогноз (история, последние дни, погода, праздники)...")
def cache_pronostico_mejorado(_engine, sucursal, hoy, desde, hasta, con_detalle=False):
    """Mismo formato que _cache_panaderia_real_y_pronostico, pero con el pronóstico de pronostico.py (honesto en los días pasados:
    cada uno se pronostica solo con lo anterior a él). Con `con_detalle` cada fila trae el desglose (base, nivel, temperatura, festivo)."""
    import pronostico
    serie = _cache_serie_diaria(_engine, sucursal)
    temps = _temperaturas_para(_engine, sucursal, dt.date.fromisoformat(hoy))
    filas = pronostico.pronosticar_rango(serie, temps, dt.date.fromisoformat(hoy), dt.date.fromisoformat(desde), dt.date.fromisoformat(hasta))
    if not con_detalle:
        for f in filas:
            f.pop("detalle", None)
    return filas


@st.cache_data(ttl=1800, show_spinner="Считаю план по продажам (история, погода, обучение)...")
def _cache_insumos(_engine, sucursal, hoy, firma_planes, firma_sobras, umbrales, _planes):
    """Todo lo que hace falta para dibujar el plan de cualquier día (plan_propio.preparar). La firma de los planes y de las sobras
    hace que el resultado se rehaga cuando llega un plan nuevo o se guarda un conteo de sobras."""
    import plan_dia
    import plan_propio
    h = dt.date.fromisoformat(hoy)
    sobras: dict = {}
    for f in get_sobrantes(_engine, sucursal, (h - dt.timedelta(days=60)).isoformat(), h.isoformat()):
        if f["sobrante"] is not None:
            sobras.setdefault(dt.date.fromisoformat(f["fecha"]), {})[plan_dia.clave_producto(f["platillo"])] = f["sobrante"]
    return plan_propio.preparar(_engine, sucursal, _planes, h, _temperaturas_para(_engine, sucursal, h), sobras,
                                ruta_cache=Path(__file__).resolve().parent / "data" / "cache_ventas.json", umbrales=umbrales,
                                merma=merma_por_dia(_engine, sucursal, h - dt.timedelta(days=60), h))


def merma_por_dia(engine, sucursal: str, desde: dt.date, hasta: dt.date) -> dict:
    """{fecha: {clave del catálogo: piezas}} de los días CON reporte de merma (un día con reporte y sin productos queda como {})."""
    import plan_dia
    from db import MARCA_DIA_CON_REPORTE

    salida: dict = {}
    for f in get_merma(engine, sucursal, desde.isoformat(), hasta.isoformat()):
        dia = salida.setdefault(dt.date.fromisoformat(f["fecha"]), {})
        if f["platillo"] != MARCA_DIA_CON_REPORTE:
            dia[plan_dia.clave_producto(f["platillo"])] = f["cantidad"]
    return salida


def _carpeta_planes(sucursal: str) -> Path:
    return Path(__file__).resolve().parent / "data" / "planes_produccion" / sucursal


@st.cache_data(ttl=120, show_spinner=False)
def _fuentes(_engine, sucursal: str) -> tuple:
    """(planes, formatos): de la carpeta del computador o, en la nube, de la copia que publica sync_nube.py (ver fuentes_plan.py)."""
    import fuentes_plan
    return fuentes_plan.cargar(_engine, sucursal, _carpeta_planes(sucursal))


def _planes_del_punto(engine, sucursal: str) -> dict:
    return _fuentes(engine, sucursal)[0]


def _formatos_semanales(engine, sucursal: str) -> dict:
    """{"panaderia": Formato, "decoracion": Formato}: las hojas semanales de ejemplo (solo dan el formato)."""
    return _fuentes(engine, sucursal)[1]


SIN_CATALOGO = ("Список позиций (каталог) ещё не загружен. На компьютере он берётся из папки data/planes_produccion/<точка>, а в облако его "
                "передаёт автоматически задача синхронизации (sync_nube) -- положите хотя бы один лист Plan_<день>_<дата>.pdf в эту папку на компьютере, "
                "включённом хотя бы раз.")


def _insumos(engine, sucursal: str, planes: dict, hoy):
    """Insumos del plan por ventas; los planes de papel solo aportan el catálogo (los últimos 8 bastan). Las cifras de las opciones
    1/2/3 (38/42/46) salen de la hoja semanal."""
    formatos = _formatos_semanales(engine, sucursal)
    umbrales = next((formatos[t].umbrales for t in ("panaderia", "decoracion") if t in formatos and formatos[t].umbrales), ())
    firma_planes = tuple((d.isoformat(), planes[d].fuente) for d in sorted(planes)[-8:])
    filas = get_sobrantes(engine, sucursal, (hoy - dt.timedelta(days=60)).isoformat(), hoy.isoformat())
    filas_m = get_merma(engine, sucursal, (hoy - dt.timedelta(days=60)).isoformat(), hoy.isoformat())
    firma_sobras = (len(filas), max((f["registrado_en"] for f in filas), default=""), len(filas_m), max((f["registrado_en"] for f in filas_m), default=""))
    return _cache_insumos(engine, sucursal, hoy.isoformat(), firma_planes, firma_sobras, tuple(umbrales), planes)


@st.cache_data(ttl=120, show_spinner=False)
def _cache_importe_antes_de_13(_engine, sucursal, hoy):
    import plan_propio
    d = dt.date.fromisoformat(hoy)
    return plan_propio.importes_antes_de(_engine, sucursal, d, d + dt.timedelta(days=1), 13).get(d)


@st.cache_data(ttl=120, show_spinner=False)
def _cache_ventas_de_hoy(_engine, sucursal, hoy):
    import pronostico
    return pronostico.ventas_de_hoy(_engine, sucursal, dt.date.fromisoformat(hoy))


@st.cache_data(ttl=CACHE_TTL_SEGUNDOS, show_spinner=False)
def _cache_ventas_hasta_hora(_engine, sucursal, corte, desde, hasta):
    import pronostico
    return pronostico.ventas_hasta_hora(_engine, sucursal, corte, dt.date.fromisoformat(desde), dt.date.fromisoformat(hasta))


def hoy_para_el_plan(engine, sucursal: str, hoy: dt.date) -> tuple:
    """(fecha desde la que se mira el plan, estado). Si hoy ya está CERRADO en la base (última venta a las 20:30 o después), el plan de mañana
    se hace como si hoy fuera mañana: el día de hoy entra completo en el pronóstico, en el nivel de los últimos días y en las partes de cada
    producto. Si no, hoy queda fuera (una venta parcial torcería todo). estado = {'cerrado': bool, 'ultima': hora decimal o None}."""
    import pronostico
    ultima = pronostico.hora_ultima_venta(engine, sucursal, hoy)
    cerrado = ultima is not None and ultima >= pronostico.HORA_CIERRE_DIA
    return (hoy + dt.timedelta(days=1) if cerrado else hoy), {"cerrado": cerrado, "ultima": ultima}


def _estado_de_hoy(estado: dict) -> None:
    """Línea de estado sobre el plan de mañana: ¿con qué datos de hoy se hizo?"""
    u = estado["ultima"]
    if estado["cerrado"]:
        st.success(f"✅ Продажи за сегодня загружены полностью (последняя в {int(u):02d}:{int(round((u % 1) * 60)) % 60:02d}) -- "
                   f"план на завтра учитывает сегодняшний день.")
    elif u is None:
        st.warning("⚠️ Продаж за сегодня в базе нет. План на завтра построен по данным до вчерашнего дня. Когда закроете день, загрузите "
                   "выгрузку Wansoft за сегодня (после 20:30) -- план пересчитается и станет точнее.")
    else:
        st.warning(f"⚠️ За сегодня в базе продажи только до {int(u):02d}:{int(round((u % 1) * 60)) % 60:02d} -- день ещё не закрыт. План на завтра "
                   f"построен без сегодняшнего дня. После закрытия (20:30) загрузите свежую выгрузку Wansoft -- план пересчитается и станет точнее.")


def _aviso_de_datos(engine, sucursal: str, hoy) -> None:
    """Advertencia visible si faltan datos a esta hora (mismas reglas que el aviso de las 13:15): sin ventas al día no hay plan fiable."""
    import avisos

    ahora = tiempo.ahora().replace(tzinfo=None)
    hoy_datos = _cache_ventas_de_hoy(engine, sucursal, hoy.isoformat())
    ayer = _cache_ventas_de_hoy(engine, sucursal, (hoy - dt.timedelta(days=1)).isoformat())
    ultima = None
    if hoy_datos:
        h = hoy_datos["corte"] - 1 / 60
        ultima = dt.datetime.combine(hoy, dt.time(int(h), int(round((h % 1) * 60)) % 60))
    msg = avisos.alerta_de_datos(ahora, ultima, bool(ayer))
    if msg:
        st.warning("⚠️ " + msg)
    if avisos.vigilante_vivo() is False:
        st.error("Сторож (vigilar.py) не запущен: файлы Wansoft не загружаются сами. Запустите Vigilante.bat или загрузите файл вручную ниже.")
    with st.expander("Загрузить файл продаж Wansoft вручную (запасной вариант)", expanded=False):
        _carga_manual(engine)


def _carga_manual(engine) -> None:
    """Sube un .xlsx de «Reporte detalle de ventas» y lo carga a la base ya, sin esperar al vigilante."""
    import auto_carga

    subidos = st.file_uploader("Файл ReporteDetalleDeVentas*.xlsx", type=["xlsx"], accept_multiple_files=True, key="carga_manual")
    if subidos and st.button("Загрузить в базу", key="carga_manual_ir"):
        estado = auto_carga._cargar_estado()
        sello = tiempo.sello_de_tiempo()
        for archivo in subidos:
            try:
                ruta = auto_carga.guardar_subido(archivo.name, archivo.getvalue())
            except ValueError as e:
                st.error(f"{archivo.name}: {e}")
                continue
            cargados, lineas = auto_carga.procesar(engine, [ruta], estado, sello, hablar=False)
            (st.success if cargados else st.warning)(f"{archivo.name}: " + ("загружен" if cargados else "не загружен -- " + "; ".join(l.split(': ', 1)[-1] for l in lineas)))
        auto_carga._registrar([f"{sello}  загрузка вручную из дашборда: {len(subidos)} файл(ов)"])
        st.cache_data.clear()


def _bloque_por_ritmo(engine, sucursal: str, hoy, planes: dict, umbrales: tuple = ()) -> None:
    """A media jornada: con lo vendido hoy hasta ahora, el pronóstico del día se afina (ver pronostico.por_ritmo)."""
    import plan_propio
    import pronostico

    hoy_datos = _cache_ventas_de_hoy(engine, sucursal, hoy.isoformat())
    if not hoy_datos or hoy_datos["unidades"] <= 0:
        st.caption("⏱ Прогноз по ходу дня появится, когда в базе будут продажи за сегодня: загрузите файл Wansoft за сегодня в 13:00 "
                   "(по нему выбирается опция 1/2/3; с продажами до 13:00 ошибка прогноза дня падает примерно с 9% до 7%).")
        return
    corte = round(hoy_datos["corte"], 3)
    ultima = f"{int(corte - 1 / 60):02d}:{int(round(((corte - 1 / 60) % 1) * 60)) % 60:02d}"
    if corte < pronostico.CORTE_MIN:
        st.caption(f"⏱ Продажи за сегодня загружены до {ultima}: для прогноза по ходу дня нужны продажи хотя бы до 11:00.")
        return
    serie = _cache_serie_diaria(engine, sucursal)
    desde = min(serie)
    parciales = _cache_ventas_hasta_hora(engine, sucursal, corte, desde.isoformat(), hoy.isoformat())
    filas = cache_pronostico_mejorado(engine, sucursal, hoy.isoformat(), desde.isoformat(), hoy.isoformat(), True)
    mananas = {dt.date.fromisoformat(f["fecha"]): f["detalle"].total for f in filas if f.get("detalle") is not None}
    if hoy not in mananas:
        return
    r = pronostico.por_ritmo(parciales, serie, hoy, hoy_datos["unidades"], corte, mananas[hoy])
    if r is None:
        st.caption("⏱ Для прогноза по ходу дня пока мало истории по таким же дням недели.")
        return
    err = pronostico.error_por_ritmo(parciales, serie, {d: v for d, v in mananas.items() if d < hoy}, hoy)
    st.markdown("##### ⏱ Прогноз по ходу дня")
    st.write(f"К {ultima} продано **{r.vendido:.0f} шт** Panadería -- обычно к этому часу в такой день уже продано {r.parte:.0%} дня. "
             f"По ритму выходит {r.por_ritmo:.0f} шт, утренний прогноз был {r.manana:.0f}. **Прогноз дня сейчас: {r.total:.0f} шт** "
             f"({r.total / r.manana - 1:+.0%} к утреннему).")
    if err:
        st.caption(f"Проверка на истории в этот же час: утренний прогноз ошибался на {err['error_manana']:.1%}, с учётом хода дня -- на "
                   f"{err['error_mezcla']:.1%} ({err['n_dias']} дней).")
    ahora = tiempo.ahora()
    if ahora.date() == hoy and ahora.hour < 21 and ahora.hour + ahora.minute / 60 - (corte - 1 / 60) > 0.75:
        st.caption(f"Данные загружены до {ultima}, а сейчас {ahora:%H:%M}: загрузите свежий файл, и прогноз уточнится.")
    if umbrales and corte >= plan_propio.HORA_OPCIONES:
        importe = _cache_importe_antes_de_13(engine, sucursal, hoy.isoformat())
        if importe:
            miles = importe / 1000
            st.info(f"Продажи кассы до 13:00: {miles:.1f} тыс. $. Ближайшая к цифрам листа ({'/'.join(f'{u:g}' for u in umbrales)}) -- "
                    f"**опция {pronostico.opcion_de_tarde(miles, tuple(umbrales))}** (выходит после 17:00). Это подсказка по цифрам, решаете вы.")


def _bloque_pronostico(detalle, usar: bool) -> None:
    """Qué entra en el pronóstico del día (base, nivel reciente, temperatura, festivo) y el aviso de día especial."""
    import pronostico

    if detalle is None:
        return
    if usar:
        st.caption(f"Прогноз продаж по позициям листа на {detalle.fecha:%d.%m}: **{detalle.total:.0f} шт** = " + "; ".join(pronostico.explicacion(detalle)) + ".")
    else:
        st.caption(f"Прогноз без поправок (только среднее по таким же дням недели): {detalle.base:.0f} шт.")
    if detalle.especial:
        previo = (f" В прошлый раз ({detalle.festivo_previo[0]:%d.%m.%Y}) продали {detalle.festivo_previo[1]:.0f} шт." if detalle.festivo_previo else "")
        st.warning(f"Особый день ({detalle.festivo or 'канун праздника'}): в такие дни прогноз ошибается заметно сильнее обычного "
                   f"(около 20% против 9%).{previo} Проверьте план вручную.")


def _motivo_ajuste(a) -> str:
    if not a.aplica:
        return f"мало данных ({a.n_dias} дн.)" if a.n_dias < 5 else "в норме, доля совпадает с продажами"
    if a.factor < 1:
        return f"продаётся {a.razon:.0%} от доли, которую давал план ({a.n_dias} дн.): долю уменьшаем"
    return f"продаётся {a.razon:.0%} от доли, которую давал план ({a.n_dias} дн.): долю увеличиваем"


def _bloque_aprendizaje(ins, plan, plan_sin) -> None:
    """Debajo del plan: qué cambió el aprendizaje respecto al plan sin él, y por qué."""
    import plan_dia

    cambios = [(f.producto, f0.total, f.total) for f, f0 in zip(plan.filas, plan_sin.filas) if f.total != f0.total]
    partes = []
    if ins.multiplicadores:
        partes.append(f"поправки долей по позициям: {len(ins.multiplicadores)}")
    if ins.colchones:
        partes.append(f"запас по остаткам и списаниям: у {len(ins.colchones)} позиций")
    st.write("🧠 **Обучение:** " + ("; ".join(partes) if partes else "поправок по позициям и остаткам пока нет (прогноз дня уже учитывает последние дни, погоду и праздники)") + ".")
    if cambios:
        with st.expander(f"Что именно изменило обучение ({len(cambios)} позиций)", expanded=False):
            filas_tabla = []
            for nombre, antes, despues in cambios:
                k = plan_dia.clave_producto(nombre)
                motivo = []
                if k in ins.colchones:
                    motivo.append(f"запас {ins.colchones[k] * 100:+.0f} п.п. по остаткам/списаниям")
                a = ins.ajustes.get(k)
                if k in ins.multiplicadores and a is not None:
                    motivo.append(_motivo_ajuste(a))
                filas_tabla.append([nombre, antes, despues, despues - antes, "; ".join(motivo) or "общий итог дня сдвинут (последние дни, погода)"])
            st.dataframe(pd.DataFrame(filas_tabla, columns=["Позиция", "Без обучения", "С обучением", "Разница", "Почему"]), hide_index=True, width="stretch")


def pestana_aprendizaje(engine, sucursal: str, hoy) -> None:
    """Pestaña "Обучение системы": cómo hace el plan el sistema, con pruebas históricas honestas y lo aprendido."""
    import aprendizaje_plan as ap
    import plan_dia
    import plan_propio as pp
    import pronostico

    st.subheader("Как система составляет план и чему учится")
    st.caption("План делается ТОЛЬКО по продажам -- ваши прежние планы в расчётах не участвуют (из PDF берутся лишь список позиций, "
               "размер лотка и формат листа). Итог дня -- прогноз по последним дням, погоде и праздникам; доля каждой позиции -- "
               "по продажам таких же дней недели (последние недели весят больше); к спросу добавляется запас на ошибку прогноза. "
               "Каждый закрытый день система сверяет СВОЙ план с фактом и поправляется; остатки на закрытии (вкладка «📦 Остатки») "
               "дают запас по каждой позиции.")
    if sucursal is None:
        st.info("Выбери конкретную точку в фильтрах слева -- у каждой точки свои продажи.")
        return
    planes = _planes_del_punto(engine, sucursal)
    ins = _insumos(engine, sucursal, planes, hoy) if planes else None
    if ins is None:
        st.info(SIN_CATALOGO if not planes else "Нет продаж по этой точке.")
        return

    st.markdown("##### Проверка на истории (каждый день считается ТОЛЬКО по данным до него)")
    serie_cat = {d: t for d, t in pp.totales_por_dia(ins.ventas).items() if t > 0}
    temps = _temperaturas_para(engine, sucursal, hoy)
    err_total = pronostico.error_historico(serie_cat, temps, hoy) if serie_cat else None
    prueba = ins.prueba_mezcla
    c1, c2 = st.columns(2)
    if err_total:
        c1.metric("Ошибка прогноза итога дня (позиции листа)", f"{err_total['error_completo']:.1%}",
                  delta=f"{(err_total['error_completo'] - err_total['error_base']) * 100:+.1f} п.п. к простому среднему по дню недели",
                  delta_color="inverse",
                  help=f"{err_total['n_dias']} дней. Простое среднее по такому же дню недели ошибается на {err_total['error_base']:.1%}; "
                       "поправки: последние 7 дней, температура, праздники.")
    else:
        c1.metric("Ошибка прогноза итога дня", "—", help="Мало истории.")
    if prueba:
        c2.metric("Расхождение долей позиций с продажами", f"{prueba['error_base']:.0%}",
                  help=f"{prueba['n_dias']} дней. Для каждой позиции |доля в плане - доля в продажах| / продажи, итог дня приравнен. "
                       "Это шум спроса по позициям: часть позиций просто продаётся неровно.")
        if ins.multiplicadores:
            st.write(f"Поправки долей по позициям **применяются**: на истории они снижают расхождение с {prueba['error_base']:.1%} до "
                     f"{prueba['error_corregido']:.1%} (лучше в {prueba['dias_mejoran']:.0%} дней).")
        else:
            st.write(f"Поправки долей по позициям **пока не применяются**: на истории они не дают выигрыша ({prueba['error_base']:.1%} → "
                     f"{prueba['error_corregido']:.1%}) -- система включит их сама, когда тест покажет пользу.")
    else:
        c2.metric("Расхождение долей позиций с продажами", "—", help="Мало закрытых дней.")

    st.markdown("##### Какой запас брать (на последних 8 неделях, план по каждому дню без подглядывания)")
    ev = pp.evaluar_colchones(ins, hoy)
    if any(r["alcanza"] is not None for r in ev):
        st.dataframe(pd.DataFrame([[f"{r['colchon']:.0%}", f"{r['alcanza']:.0%}" if r["alcanza"] is not None else "—",
                                    f"{r['sobra']:.0%}" if r["sobra"] is not None else "—"] for r in ev],
                                  columns=["Запас на ошибку прогноза", "Позиций-дней, где хватило", "Доля произведённого, что останется"]),
                     hide_index=True, width="stretch")
        st.caption("Чем больше запас, тем реже позиция заканчивается и тем больше остаётся. Посчитано по каждой позиции и дню; реальных остатков "
                   "система пока не видит (до вкладки «📦 Остатки» это оценка по продажам). Запас по умолчанию задаёт слайдер в «План на день» "
                   "(15%); когда накопятся остатки, у каждой позиции он подстроится сам.")

    st.markdown("##### Остатки на закрытии: чему научилась система")
    if ins.colchones:
        filas = []
        for it in ins.catalogo.items:
            if it.clave in ins.colchones:
                filas.append([it.producto, f"{ins.colchones[it.clave] * 100:+.0f} п.п."])
        st.dataframe(pd.DataFrame(filas, columns=["Позиция", "Поправка к общему запасу"]), hide_index=True, width="stretch")
    else:
        st.info("Остатков пока недостаточно (нужно хотя бы 5 дней подсчёта по позиции за последние 8 недель). Начните вводить их на вкладке "
                "«📦 Остатки» -- 2-3 минуты в конце дня по основным позициям.")

    st.markdown("##### Распределение по позициям: что выучила система")
    ajustes = ins.ajustes
    if ajustes:
        orden = sorted(ajustes.values(), key=lambda a: (not a.aplica, -abs(a.factor_bruto - 1)))
        tabla = pd.DataFrame([[a.producto, a.n_dias, round(a.plan_medio, 1), round(a.vendido_medio, 1),
                               f"{a.razon:.0%}" if a.razon is not None else "—", f"{a.factor_bruto - 1:+.0%}",
                               "применяется" if (a.clave in ins.multiplicadores) else "не применяется", _motivo_ajuste(a)] for a in orden],
                             columns=["Позиция", "Дней", "Давал план, шт/день", "Продано, шт/день", "Продано от плана", "Расчётная поправка", "Статус", "Вывод"])
        st.dataframe(tabla, hide_index=True, width="stretch", height=420)
    if ins.fuera_del_catalogo:
        st.caption("Продаются, но их нет в листе (план для них не строится; кроме выпечки здесь десерты и печенье): "
                   + ", ".join(ins.fuera_del_catalogo[:12]) + ("..." if len(ins.fuera_del_catalogo) > 12 else "") + ".")
    sin_ventas = [i.producto for i in ins.catalogo.items if not any(i.clave in d for d in list(ins.ventas.values())[-56:])]
    if sin_ventas:
        st.caption("В листе, но за 8 недель продаж не найдено (в плане 0): " + ", ".join(sin_ventas) + ".")
    st.caption("Ограничение: без остатков система не отличает «не купили» от «закончилось», поэтому запас -- ваша настройка, пока не "
               "накопятся остатки. Резерв (холодильник) не рассчитывается -- это ваше решение.")


def _plan_recomendado(ins, fecha) -> dict:
    """{clave: piezas que el sistema recomendaba hornear ese día (hasta las 17:00 + la opción 2)} -- para comparar con lo horneado de verdad."""
    import plan_dia
    import plan_propio as pp

    r = pp.plan_del_dia(ins, fecha)
    if r is None:
        return {}
    return {plan_dia.clave_producto(f.producto): f.total + (f.tandas[1] or 0) for f in r[0].filas}


def _leer_exportacion(archivo) -> str:
    """Texto del chat desde lo que subió el usuario: el zip de «Exportar chat» (trae _chat.txt) o el .txt suelto."""
    import io
    import zipfile

    datos = archivo.getvalue()
    if archivo.name.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(datos)) as z:
            nombre = next((n for n in z.namelist() if n.lower().endswith(".txt")), None)
            if nombre is None:
                raise ValueError("в архиве нет текстового файла чата (_chat.txt)")
            datos = z.read(nombre)
    return datos.decode("utf-8", errors="ignore")


def _importar_whatsapp(engine, sucursal: str, ins) -> None:
    """Carga las listas «merma de hoy» del chat. Por decisión del dueño, todo lo que queda al cierre se tira: la lista ES el sobrante del día. Nada se
    guarda sin que el usuario revise la tabla de emparejamientos (una cifra mal puesta torcería el colchón de esa posición)."""
    import plan_dia
    import whatsapp_merma as wm

    st.caption("В WhatsApp: группа → меню → «Экспорт чата» → «Без медиа», и загрузите файл сюда (zip или _chat.txt). Каждый вечерний список "
               "«merma de hoy» считается остатком дня: то, чего нет в списке, -- 0. «Baguette» без уточнения = Baguette Ch. Перед сохранением "
               "проверьте сопоставление ниже и исправьте спорные строки.")
    archivo = st.file_uploader("Экспорт чата WhatsApp", type=["zip", "txt"], key="wa_archivo")
    if archivo is None:
        return
    try:
        texto = _leer_exportacion(archivo)
    except (ValueError, OSError) as e:
        st.error(f"Не удалось прочитать файл: {e}")
        return
    reportes = sorted((r for r in wm.extraer_reportes(texto) if r.tipo == "merma"), key=lambda r: (r.fecha, r.publicado))
    if not reportes:
        st.info("В файле не найдено ни одного списка «merma de hoy» с цифрами.")
        return
    ya = {f["fecha"] for f in get_merma(engine, sucursal)}
    omitir = "— пропустить —"
    productos = [i.producto for i in ins.catalogo.items]
    nombres = {i.clave: i.producto for i in ins.catalogo.items}
    filas, autores = [], {}
    for r in reportes:
        autores.setdefault(r.fecha, f"whatsapp {r.autor.lstrip('~ ')} {r.publicado:%H:%M}")
        for cantidad, texto_libre in r.items:
            clave, como = wm.emparejar(texto_libre, ins.catalogo.items)
            filas.append({"Дата": r.fecha, "Как написали": texto_libre, "Кол-во": cantidad, "Позиция": nombres.get(clave, omitir),
                          "Сопоставление": como, "Уже в базе": r.fecha.isoformat() in ya})
    fechas = sorted({f["Дата"] for f in filas})
    elegidas = st.multiselect("Какие дни сохранить", fechas, default=[d for d in fechas if d.isoformat() not in ya],
                              format_func=lambda d: f"{d:%d.%m.%Y}" + (" (уже есть, будет заменён)" if d.isoformat() in ya else ""), key="wa_dias")
    tabla = st.data_editor(pd.DataFrame(filas), hide_index=True, width="stretch", key=f"wa_tabla_{archivo.name}_{len(filas)}",
                           column_config={"Дата": st.column_config.DateColumn(disabled=True, format="DD.MM"),
                                          "Как написали": st.column_config.TextColumn(disabled=True),
                                          "Кол-во": st.column_config.NumberColumn(disabled=True),
                                          "Позиция": st.column_config.SelectboxColumn(options=[omitir] + productos, required=True),
                                          "Сопоставление": st.column_config.TextColumn(disabled=True),
                                          "Уже в базе": st.column_config.CheckboxColumn(disabled=True)})
    sin_pos = tabla[(tabla["Позиция"] == omitir) & tabla["Дата"].isin(elegidas)]
    if len(sin_pos):
        st.caption("Не будут сохранены (нет позиции): " + "; ".join(f"{r['Кол-во']} {r['Как написали']}" for _, r in sin_pos.iterrows()) + ".")
    if st.button("💾 Сохранить списания за выбранные дни", key="wa_guardar", disabled=not elegidas):
        sello = tiempo.sello_de_tiempo()
        total = 0
        for d in elegidas:
            dia = tabla[(tabla["Дата"] == d) & (tabla["Позиция"] != omitir)]
            total += set_merma_dia(engine, sucursal, d.isoformat(), [{"platillo": r["Позиция"], "cantidad": r["Кол-во"]} for _, r in dia.iterrows()],
                                   sello, autores[d])
        st.success(f"Сохранено дней: {len(elegidas)}, позиций: {total}. План и вкладка «💰 Деньги» учтут это при следующем пересчёте (до 30 минут).")


def pestana_sobrantes(engine, sucursal: str, hoy) -> None:
    """Pestaña "Остатки": el CIERRE DEL DÍA producto por producto (lo horneado, lo que sobró, a qué hora se acabó). Alimenta el colchón de
    plan_propio.py y la pestaña «Деньги»."""
    import plan_dia

    st.subheader("Закрытие дня: остатки")
    st.caption("В конце дня за 2-3 минуты, по основным позициям (они наверху): сколько ОСТАЛОСЬ. **0 = всё раскупили** -- и тогда впишите, "
               "во сколько закончилось (это показывает, сколько продаж потеряно). «Испекли» -- по желанию: так видно, насколько вы следуете плану. "
               "Пустая ячейка = не считали. Через 5+ дней подсчёта система сама подстроит запас по каждой позиции, а вкладка «💰 Деньги» "
               "покажет, во сколько обходится неточность плана и становится ли она меньше.")
    if sucursal is None:
        st.info("Выбери конкретную точку в фильтрах слева.")
        return
    planes = _planes_del_punto(engine, sucursal)
    ins = _insumos(engine, sucursal, planes, hoy) if planes else None
    if ins is None:
        st.info("Нужен хотя бы один лист Plan_<день>_<дата>.pdf (из него берётся список позиций) и продажи.")
        return
    if sucursal == PUNTO_WHATSAPP:
        with st.expander("📥 Импорт списаний из WhatsApp (группа «Ventas El Molino»)", expanded=False):
            _importar_whatsapp(engine, sucursal, ins)
    ahora = tiempo.ahora()
    fecha = st.date_input("За какой день", value=hoy if ahora.hour >= 17 else hoy - dt.timedelta(days=1), max_value=hoy, key="sobr_fecha")
    iso = fecha.isoformat()
    guardado = {plan_dia.clave_producto(f["platillo"]): f for f in get_sobrantes(engine, sucursal, iso, iso)}
    ultimos = list(ins.ventas.items())[-28:]
    volumen = {i.clave: sum(d.get(i.clave, 0.0) for _, d in ultimos) for i in ins.catalogo.items}
    orden = sorted(ins.catalogo.items, key=lambda i: -volumen[i.clave])
    principales, otros = orden[:25], orden[25:]
    vendido_dia = ins.ventas.get(fecha, {})
    plan_dia_sistema = _plan_recomendado(ins, fecha)
    sugerir = st.checkbox("Подставить ожидаемые остатки (план минус продано) -- проверьте и поправьте", value=False, key="sobr_sugerir",
                          disabled=not vendido_dia,
                          help="Только там, где ещё нет вашей записи. Это оценка, а не факт: сверьте с тем, что реально осталось на витрине.")

    def tabla(items):
        def esperado(i):
            if not sugerir or i.clave not in vendido_dia or i.clave not in plan_dia_sistema:
                return None
            return max(0.0, round(plan_dia_sistema[i.clave] - vendido_dia[i.clave]))
        return pd.DataFrame({
            "Позиция": [i.producto for i in items],
            "План системы, шт": [plan_dia_sistema.get(i.clave) for i in items],
            "Продано": [round(vendido_dia[i.clave]) if i.clave in vendido_dia else None for i in items],
            "Испекли, шт": [guardado[i.clave]["horneado"] if i.clave in guardado else None for i in items],
            "Осталось, шт": [guardado[i.clave]["sobrante"] if i.clave in guardado and guardado[i.clave]["sobrante"] is not None else esperado(i) for i in items],
            "Закончилось в (ЧЧ:ММ)": [guardado[i.clave]["agotado_a"] if i.clave in guardado else None for i in items],
        })

    cfg = {"Позиция": st.column_config.TextColumn(disabled=True), "План системы, шт": st.column_config.NumberColumn(disabled=True),
           "Продано": st.column_config.NumberColumn(disabled=True), "Испекли, шт": st.column_config.NumberColumn(min_value=0, step=1),
           "Осталось, шт": st.column_config.NumberColumn(min_value=0, step=1),
           "Закончилось в (ЧЧ:ММ)": st.column_config.TextColumn(max_chars=5, help="Например 17:30. Только если осталось 0.")}
    clave_editor = f"{iso}_{int(sugerir)}"
    st.markdown("**Основные позиции**")
    ed1 = st.data_editor(tabla(principales), hide_index=True, width="stretch", column_config=cfg, key=f"sobr_top_{clave_editor}",
                         height=min(36 * (len(principales) + 1) + 4, 700))
    cero = st.checkbox("Пустые «Осталось» в основных позициях считать нулём (всё раскупили)", value=False, key="sobr_cero",
                       help="Удобно: вписываете только то, что осталось, остальное из основного списка -- 0. Включайте, только если "
                            "действительно пересчитали все основные позиции.")
    ed2 = None
    if otros:
        with st.expander(f"Остальные позиции ({len(otros)})"):
            ed2 = st.data_editor(tabla(otros), hide_index=True, width="stretch", column_config=cfg, key=f"sobr_otros_{clave_editor}")
    if st.button("💾 Сохранить закрытие дня", key=f"sobr_guardar_{iso}"):
        hay_conteo = any(x == x and x is not None for x in ed1["Осталось, шт"])
        filas = []
        for ed, items, vacias_cero in ((ed1, principales, cero), (ed2, otros, False)):
            if ed is None:
                continue
            for it, s, h, a in zip(items, ed["Осталось, шт"], ed["Испекли, шт"], ed["Закончилось в (ЧЧ:ММ)"]):
                if (s is None or s != s) and vacias_cero and hay_conteo:
                    s = 0
                filas.append({"platillo": it.producto, "sobrante": s, "horneado": h, "agotado_a": a})
        n = set_sobrantes(engine, sucursal, iso, filas, tiempo.sello_de_tiempo())
        st.success(f"Сохранено: {n} позиций за {fecha:%d.%m}. План и вкладка «💰 Деньги» учтут это при следующем пересчёте (до 30 минут).")
    previos: dict = {}
    for f in get_sobrantes(engine, sucursal, (hoy - dt.timedelta(days=28)).isoformat(), hoy.isoformat()):
        previos[f["fecha"]] = previos.get(f["fecha"], 0) + 1
    if previos:
        st.caption("Уже записано (дата: позиций): " + ", ".join(f"{dt.date.fromisoformat(d):%d.%m}: {n}" for d, n in sorted(previos.items())[-10:]) + ".")


@st.cache_data(ttl=1800, show_spinner=False)
def _cache_precios(_engine, sucursal, claves, hoy):
    import dinero
    h = dt.date.fromisoformat(hoy)
    return dinero.precios_por_producto(_engine, sucursal, list(claves), h - dt.timedelta(days=60), h)


def _perfiles_por_hora(ins) -> dict:
    """{(clave, es_fin_de_semana): [unidades por hora]} de las últimas semanas, para estimar a qué parte del día equivale una hora de agotado."""
    perfiles: dict = {}
    for d, dia in ins.ventas_hora.items():
        for k, horas in dia.items():
            acum = perfiles.setdefault((k, d.weekday() >= 5), [0.0] * 24)
            for h in range(24):
                acum[h] += horas[h]
    return perfiles


def pestana_dinero(engine, sucursal: str, hoy) -> None:
    """Pestaña "Деньги": la prueba de que el sistema sirve -- cuánto cuesta la imprecisión del plan cada semana (merma + ventas perdidas)."""
    import dinero
    import plan_dia

    st.subheader("Деньги: сколько стоит неточность плана")
    st.caption("Две потери: **остатки/списания** (всё, что осталось к закрытию, идёт в списание; по себестоимости) и **потерянные продажи** "
               "(позиция закончилась раньше закрытия; считается, только если вы записали время). Их сумма -- «стоимость неточности» -- и есть "
               "главный показатель: если система работает, она должна падать неделя за неделей. Данные берутся из вкладки «📦 Остатки» "
               "(ручной ввод и импорт списаний из WhatsApp).")
    if sucursal is None:
        st.info("Выбери конкретную точку в фильтрах слева.")
        return
    planes = _planes_del_punto(engine, sucursal)
    ins = _insumos(engine, sucursal, planes, hoy) if planes else None
    if ins is None:
        st.info(SIN_CATALOGO if not planes else "Нет продаж по этой точке.")
        return
    costo = st.slider("Себестоимость, % от цены продажи (предположение -- поставьте свою)", 10, 80, int(dinero.COSTO_DEFECTO * 100), 5, key="dinero_costo") / 100
    desde = hoy - dt.timedelta(days=150)
    filas = get_sobrantes(engine, sucursal, desde.isoformat(), hoy.isoformat())
    merma = merma_por_dia(engine, sucursal, desde, hoy)
    if not filas and not merma:
        st.info("Пока нет ни одного закрытия дня. Начните вводить остатки на вкладке «📦 Остатки» (или загрузите списания из WhatsApp там же): "
                "через неделю здесь появится первая строка, через 3-4 недели -- динамика.")
        return
    precios = _cache_precios(engine, sucursal, tuple(ins.catalogo.claves), hoy.isoformat())
    recomendado: dict = {}
    lineas = []
    for f in filas:
        fecha = dt.date.fromisoformat(f["fecha"])
        k = plan_dia.clave_producto(f["platillo"])
        if fecha not in recomendado:
            recomendado[fecha] = _plan_recomendado(ins, fecha)
        lineas.append(dinero.Linea(fecha, k, f["platillo"], ins.ventas.get(fecha, {}).get(k, 0.0), f["sobrante"], f["horneado"], f["agotado_a"],
                                   recomendado[fecha].get(k) or None, precios.get(k)))
    for fecha in merma:
        if fecha not in recomendado:
            recomendado[fecha] = _plan_recomendado(ins, fecha)
    ruta_manual = {ln.fecha for ln in lineas if ln.sobrante is not None}           # esos días ya tienen conteo manual: no se cuentan dos veces
    lineas += dinero.lineas_de_merma(merma, ins.ventas, ins.catalogo.claves, {i.clave: i.producto for i in ins.catalogo.items}, precios, recomendado,
                                     excluir=ruta_manual)
    resumen = dinero.resumen_semanal(lineas, _perfiles_por_hora(ins), costo)
    serie = {d: sum(v.values()) for d, v in ins.ventas.items()}
    for r in resumen:
        r["error"] = dinero.error_de_pronostico(serie, ins.pronosticos, r["lunes"], r["lunes"] + dt.timedelta(days=6))
    con_datos = [r for r in resumen if r["imprecision"] is not None]
    if not con_datos:
        st.info("Записей пока слишком мало: день считается, если внесено хотя бы 5 позиций.")
        return
    ultima = con_datos[-1]
    anterior = con_datos[-2] if len(con_datos) > 1 else None
    c1, c2, c3 = st.columns(3)
    cambio = dinero.comparar(anterior, ultima, "imprecision")
    c1.metric(f"Стоимость неточности, неделя с {ultima['lunes']:%d.%m}", f"{ultima['imprecision']:,.0f} $",
              delta=(f"{cambio:+.0%} к прошлой неделе" if cambio is not None else None), delta_color="inverse",
              help="Остатки по себестоимости + маржа потерянных продаж (оценка). Чем меньше, тем точнее план.")
    c2.metric("Позиций закончилось раньше закрытия", f"{ultima['pct_agotado']:.0%}" if ultima["pct_agotado"] is not None else "—",
              help="Доля посчитанных позиций, где осталось 0.")
    c3.metric("Выполнение плана системы", f"{ultima['adherencia']:.0%}" if ultima["adherencia"] is not None else "—",
              help="Испекли / рекомендовано системой, по позициям, где вы записали «Испекли». Если сильно меньше 100%, выводы по остаткам относятся не только к системе.")
    tabla = pd.DataFrame([[f"{r['lunes']:%d.%m}", r["dias_contados"], r["posiciones"],
                           f"{r['pct_agotado']:.0%}" if r["pct_agotado"] is not None else "—",
                           round(r["merma_unid"]) if r["merma_unid"] is not None else None,
                           round(r["merma_costo"]) if r["merma_costo"] is not None else None,
                           round(r["perdidas_unid"]) if r["perdidas_unid"] is not None else None,
                           round(r["perdidas_margen"]) if r["perdidas_margen"] is not None else None,
                           round(r["imprecision"]) if r["imprecision"] is not None else None,
                           f"{r['adherencia']:.0%}" if r["adherencia"] is not None else "—",
                           f"{r['error']:.1%}" if r["error"] is not None else "—"] for r in resumen],
                         columns=["Неделя с", "Дней", "Позиций", "Закончилось", "Остаток, шт", "Остаток (себест.), $", "Потеряно, шт (оценка)",
                                  "Маржа потерь, $", "Стоимость неточности, $", "Выполнение плана", "Ошибка прогноза дня"])
    st.dataframe(tabla, hide_index=True, width="stretch")
    st.caption("Потерянные продажи считаются только для позиций, где вы указали время, когда закончилось; без времени они равны 0 (осторожная оценка). "
               "Цены -- средние по продажам за 60 дней; себестоимость -- ваше предположение выше. Улучшением считайте падение «стоимости неточности» "
               "хотя бы 3-4 недели подряд при сопоставимых продажах.")


def _claves_reserva_reglamento(ins) -> list:
    """Los productos de reserva del reglamento, con la clave que tienen en el catálogo (la clave ordena y normaliza las palabras)."""
    import plan_dia
    import regla_vitrina as rv
    objetivo = {plan_dia.clave_producto(n) for n in rv.RESERVA_DEL_REGLAMENTO}
    return [k for k in ins.catalogo.claves if k in objetivo]


def _reserva_para(ins, fecha: dt.date, hoy_plan, claves_reserva=None, margen: float = 0.15) -> dict:
    """{clave: piezas de reserva} para el día `fecha`: venta de 18:00 a 20:30 del mismo tipo de día (+ margen). Por defecto, los productos del
    reglamento que estén en el catálogo. Sale de la tanda de la tarde: no suma producción."""
    import regla_vitrina as rv
    if claves_reserva is None:
        claves_reserva = _claves_reserva_reglamento(ins)
    noche = rv.ventas_de_noche(ins.ventas_hora, hoy_plan, rv.tipo_de_dia(fecha))
    return rv.reserva(noche, list(claves_reserva), margen)


def pestana_regla(engine, sucursal: str, hoy) -> None:
    """Pestaña «Регламент»: ABC y reserva del reglamento del dueño, calculados con las ventas (por tipo de día) y el indicador «vitrina llena»."""
    import plan_dia
    import regla_vitrina as rv

    st.subheader("Регламент витрины -- по данным продаж")
    st.caption("Правила регламента (ABC, резерв, полная витрина до 20:30), но цифры берутся из продаж, а не из таблицы: пересчитываются сами. "
               "Будни (Пн–Чт), пятница и выходные (Сб–Вс) считаются отдельно -- последние 8 недель.")
    if sucursal is None:
        st.info("Выбери конкретную точку в фильтрах слева.")
        return
    planes = _planes_del_punto(engine, sucursal)
    if not planes:
        st.info(SIN_CATALOGO)
        return
    hoy_plan, _ = hoy_para_el_plan(engine, sucursal, hoy)
    ins = _insumos(engine, sucursal, planes, hoy_plan)
    if ins is None:
        st.info("Нет продаж по этой точке.")
        return
    nombres = {i.clave: i.producto for i in ins.catalogo.items}
    manana = hoy + dt.timedelta(days=1)
    tipos = list(rv.TIPOS)
    tipo = st.radio("Тип дня", tipos, index=tipos.index(rv.tipo_de_dia(manana)), format_func=lambda t: rv.ETIQUETAS[t], horizontal=True,
                    key="regla_tipo")

    r = rv.abc(ins.ventas, hoy_plan, tipo)
    st.markdown(f"**Классификация ABC** -- {rv.ETIQUETAS[tipo]}, учтено дней: {r['dias']}")
    if r["dias"] < 3:
        st.info("Для этого типа дня пока мало дней (нужно хотя бы 3).")
    else:
        res = rv.resumen_abc(r["filas"])
        c = st.columns(3)
        for col, clase in zip(c, "ABC"):
            n, parte = res[clase]
            col.metric(f"Группа {clase}", f"{n} поз.", delta=f"{parte:.0%} объёма", delta_color="off")
        st.caption("В регламенте: A -- 24 позиции (79% объёма), B -- 14 (15%), C -- 14 (5%). Здесь границы те же (79% и 94% накопленного объёма), "
                   "а позиции и их число определяются продажами.")
        tabla = pd.DataFrame([[nombres.get(f["clave"], f["clave"]), f["clase"], round(f["por_dia"], 1), f"{f['parte']:.1%}", f"{f['acumulado']:.0%}"]
                              for f in r["filas"]], columns=["Позиция", "Группа", "шт/день", "Доля", "Накоплено"])
        with st.expander(f"Таблица ABC ({len(tabla)} позиций)", expanded=False):
            st.dataframe(tabla, hide_index=True, width="stretch", height=420)

    st.markdown("**Резерв на вечер (18:00–20:30)**")
    noche = rv.ventas_de_noche(ins.ventas_hora, hoy_plan, tipo)
    if not noche:
        st.info("Нет данных по часам для этого типа дня.")
    else:
        margen = st.slider("Запас к вечерним продажам, %", 0, 40, int(rv.MARGEN_RESERVA * 100), 5, key="regla_margen") / 100
        por_defecto = _claves_reserva_reglamento(ins)
        elegidos = st.multiselect("Позиции в резерве", ins.catalogo.claves, default=por_defecto, format_func=lambda k: nombres.get(k, k), key="regla_reserva")
        total_noche = sum(noche.values())
        filas = rv.reserva(noche, elegidos, margen)
        if elegidos:
            tabla_r = pd.DataFrame([[nombres.get(k, k), round(noche.get(k, 0.0), 1), filas[k]] for k in elegidos],
                                   columns=["Позиция", "Вечером продаётся, шт/день", "Резерв, шт"])
            st.dataframe(tabla_r, hide_index=True, width="stretch")
            parte = sum(noche.get(k, 0.0) for k in elegidos) / total_noche if total_noche else 0
            st.caption(f"Выбранные позиции дают {parte:.0%} вечерних продаж (весь каталог за 18:00–20:30: {total_noche:.0f} шт/день). Резерв выделяется из "
                       f"вечерней выпечки, а не добавляется к ней.")
        cand = rv.candidatos(noche, 10)
        if cand:
            st.write("Что больше всего продаётся вечером (кандидаты в резерв, если товар держится до утра):")
            st.dataframe(pd.DataFrame([[nombres.get(k, k), round(v, 1), f"{p:.0%}", "в резерве" if k in elegidos else ""] for k, v, p in cand],
                                      columns=["Позиция", "шт/день вечером", "Доля вечера", ""]), hide_index=True, width="stretch")

    st.markdown("**Показатель регламента: полная витрина до 20:30**")
    claves_a = {f["clave"] for f in rv.abc(ins.ventas, hoy_plan, tipo)["filas"] if f["clase"] == "A"}
    filas_sobras = get_sobrantes(engine, sucursal, (hoy - dt.timedelta(days=60)).isoformat(), hoy.isoformat())
    kpi = rv.vitrina_llena(filas_sobras, claves_a, plan_dia.clave_producto)
    if kpi["registros"] == 0:
        st.info("Пока нет записей «закончилось в ...» по позициям группы A. Вносите время на вкладке «📦 Остатки»: цель регламента -- чтобы позиции группы A "
                "не заканчивались до 20:30.")
    else:
        st.metric("Позиции группы A, закончившиеся до 20:30", f"{kpi['pct']:.0%}", delta=f"{kpi['agotados']} из {kpi['registros']} записей",
                  delta_color="off", help="Цель регламента -- около 0% по группе A.")


def _tabla_semana(sp) -> pd.DataFrame:
    """Vista en pantalla de un plan semanal (PlanSemana): una fila por posición, Mat/Vesp de cada día, opciones y reserva."""
    dias = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
    con_reserva = sp.formato.reserva is not None
    cols = ["Позиция"] + [f"{d} {t}" for d in dias for t in ("Mat", "Vesp")] + ["Опц.1", "Опц.2", "Опц.3"] + (["Резерв"] if con_reserva else [])
    filas = []
    for f in sp.filas:
        if f.grupo:
            filas.append([f"— {f.nombre} —"] + [None] * (len(cols) - 1))
            continue
        fila = [f.nombre]
        for i in range(7):
            fila += [f.mat[i] or None, f.vesp[i] or None]
        fila += [o or None for o in f.opciones] + ([f.reserva or None] if con_reserva else [])
        filas.append(fila)
    return pd.DataFrame(filas, columns=cols)


def _seccion_plan_semana(engine, sucursal: str, hoy, ins, usar: bool, colchon: float) -> None:
    """Los dos planes semanales (Panadería por base y Decoración por sabor) hechos por el sistema con las cifras de los planes diarios."""
    import plan_semanal as ps

    st.subheader("📅 План недели: пекарня и декорации")
    formatos = _formatos_semanales(engine, sucursal)
    faltan = [n for t, n in (("panaderia", "Plan_Panaderia_Semana_<понедельник>.pdf"), ("decoracion", "Plan_Decoracion_Semana_<понедельник>.pdf"))
              if t not in formatos]
    if faltan:
        st.info(f"Нет образца: {', '.join(faltan)}. Из образца берётся только формат (строки, порядок, "
                "подписи) -- все цифры считает система по продажам.")
    if not formatos:
        return
    st.caption("Оба плана -- из одних и тех же цифр системы («те же количества, что у пекарни, разбитые по вкусам»): Mat -- выпечка с 7 до 12, "
               "Vesp -- с 13 до 17; опции выходят после 17:00. Резерв (холодильник) вписывается вручную.")
    elegido = st.date_input("Неделя (любой день недели)", value=hoy + dt.timedelta(days=7 - hoy.weekday()), key="plan_sem_fecha")
    lunes = elegido - dt.timedelta(days=elegido.weekday())
    reserva = {}
    if formatos.get("panaderia") is not None and formatos["panaderia"].reserva:
        r = st.number_input("Резерв Croissant в холодильнике, шт/день (вписывается вручную, система его не считает)", min_value=0, max_value=2000,
                            value=0, step=12, key="plan_sem_reserva")
        if r:
            reserva["Croissant"] = int(r)
    planes_dias = ps.planes_de_la_semana(ins, lunes, colchon, usar)
    tipos = [t for t in ("panaderia", "decoracion") if t in formatos]
    nombres_tab = {"panaderia": "🥐 Пекарня (по базам)", "decoracion": "🎂 Декорации (по вкусам)"}
    for tipo, tab in zip(tipos, st.tabs([nombres_tab[t] for t in tipos])):
        with tab:
            sp = ps.construir(formatos[tipo], ins, planes_dias, lunes, colchon, reserva if tipo == "panaderia" else None)
            if sp.faltan_dias:
                st.warning("Для этих дней пока мало истории или нет прогноза, столбцы пустые: " + ", ".join(f"{d:%d.%m}" for d in sp.faltan_dias) + ".")
            st.dataframe(_tabla_semana(sp), hide_index=True, width="stretch", height=460)
            col_pdf, col_xlsx = st.columns(2)
            try:
                col_pdf.download_button("⬇️ Скачать PDF", data=ps.plan_a_pdf(sp), file_name=ps.nombre_archivo(sp, "pdf"), mime="application/pdf",
                                        key=f"plan_sem_pdf_{tipo}")
            except ImportError:
                col_pdf.warning("Для PDF нужен пакет pymupdf: «py -m pip install pymupdf».")
            col_xlsx.download_button("⬇️ Скачать .xlsx (можно править)", data=ps.plan_a_xlsx(sp), file_name=ps.nombre_archivo(sp, "xlsx"),
                                     mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"plan_sem_xlsx_{tipo}")
            if sp.sin_producto:
                st.caption("Строки листа, для которых в продажах не нашлось позиции (пусто): " + ", ".join(sp.sin_producto) + ".")
            if tipo == "decoracion" and sp.sin_fila:
                st.caption("Не входят в лист декораций (солёное и т.п.): " + ", ".join(sp.sin_fila[:14]) + ("..." if len(sp.sin_fila) > 14 else "") + ".")
            if tipo == "panaderia":
                st.caption("«Pan de Muerto Negro» система считает по вкусу «шоколад» (допущение; если это другой вкус, скажите).")


def seccion_plan_del_dia(engine, sucursal: str, fecha_default, fecha_min, hoy) -> None:
    """Plan del día en el formato de la hoja de producción (PDF y .xlsx), hecho solo con las ventas: ver plan_propio.py."""
    import plan_dia
    import plan_propio as pp

    planes = _planes_del_punto(engine, sucursal)
    if not planes:
        st.info(SIN_CATALOGO + " Из листа берётся только список позиций, размер лотка и формат (цифры из него в расчёт не идут).")
        return
    hoy_plan, estado_hoy = hoy_para_el_plan(engine, sucursal, hoy)
    ins = _insumos(engine, sucursal, planes, hoy_plan)
    if ins is None:
        st.info("Нет продаж по этой точке -- плану не из чего считаться.")
        return
    _estado_de_hoy(estado_hoy)
    _aviso_de_datos(engine, sucursal, hoy)
    _bloque_por_ritmo(engine, sucursal, hoy, planes, ins.umbrales)
    fecha = st.date_input("На какое число план", value=fecha_default, min_value=fecha_min, key="plan_dia_fecha")
    col_a, col_b = st.columns(2)
    usar = col_a.toggle("🧠 Учитывать обучение системы (последние дни, погода, праздники, остатки)", value=True, key="plan_dia_aprender",
                        help="Прогноз дня поправляется по последним дням, погоде и праздникам, запас по позициям -- по остаткам на закрытии, "
                             "доли позиций -- по тому, что система выучила. Выключите, чтобы увидеть план без поправок.")
    colchon = col_b.slider("Запас на ошибку прогноза, %", 0, 40, int(pp.COLCHON_DEFECTO * 100), 5, key="plan_colchon",
                           help="Сколько печь сверх ожидаемых продаж. Больше запас -- реже заканчивается, но больше остаётся. На вкладке "
                                "«🧠 Обучение системы» есть таблица: какой запас что даёт. Когда накопятся остатки, у каждой позиции он подстроится сам.") / 100
    p_dia = ins.pronosticos.get(fecha)
    base_dia = p_dia.base if p_dia is not None else None
    res = pp.plan_del_dia(ins, fecha, colchon, usar, None if usar else base_dia)
    if res is None:
        st.info("Для этой даты пока мало истории по таким же дням недели (нужно хотя бы 4) -- плану не из чего считаться.")
        return
    plan, det = res
    calcular_reserva = st.toggle("📦 Рассчитать резерв (круассаны по регламенту)", value=True, key="plan_dia_reserva",
                                 help="Вечерние продажи 18:00–20:30 такого же типа дня (будни / пятница / выходные) + 15%. Резерв выделяется из вечерней "
                                      "выпечки -- общий объём плана не меняется. Список позиций и запас -- на вкладке «📐 Регламент».")
    if calcular_reserva:
        claves_r = st.session_state.get("regla_reserva")
        for clave, n in _reserva_para(ins, fecha, hoy_plan, claves_r, st.session_state.get("regla_margen", 15) / 100).items():
            for f in plan.filas:
                if plan_dia.clave_producto(f.producto) == clave and n:
                    f.reserva = n
    plan_sin = pp.plan_del_dia(ins, fecha, colchon, False, base_dia)[0] if usar else None
    st.write(f"**Источник:** только продажи (ваши прежние планы в расчёте не участвуют, из них взяты лишь список позиций, размер лотка и формат листа). "
             f"Итог дня -- прогноз {det['total']:.0f} шт по позициям листа; доля каждой позиции -- по продажам таких же дней недели; "
             f"запас на ошибку прогноза {colchon:.0%}; часы выпечки -- по тому, когда позиция продаётся (печём за ~3 часа до продажи).")
    _bloque_pronostico(p_dia, usar)
    if plan_sin is not None:
        _bloque_aprendizaje(ins, plan, plan_sin)
    t = plan_dia.totales(plan)
    st.write(f"Итого до 17:00: **{t['total']} шт**; вечерние опции 1/2/3 (выбираются в 13:00 по продажам, выходят после 17:00):"
             f"{t['tandas'][0]} / {t['tandas'][1]} / {t['tandas'][2]} шт; резерв: {t['reserva']} шт (выделяется из вечерней выпечки).")

    cols = ["Продукт"] + [("13 (1PM)" if h == 13 else str(h)) for h in plan_dia.HORAS] + ["ИТОГО 5PM", "1", "2", "3", "Резерв"]
    tabla = pd.DataFrame([[f.producto] + [f.horas.get(h) for h in plan_dia.HORAS] + [f.total] + list(f.tandas) + [f.reserva] for f in plan.filas], columns=cols)
    with st.expander(f"Показать план на экране ({len(plan.filas)} позиций)", expanded=False):
        st.dataframe(tabla, hide_index=True, width="stretch", height=420)

    col_pdf, col_xlsx = st.columns(2)
    try:
        col_pdf.download_button("⬇️ Скачать PDF (как лист на бумаге)", data=plan_dia.plan_a_pdf(plan),
                                file_name=plan_dia.nombre_archivo(plan, "pdf"), mime="application/pdf", key="plan_dia_pdf")
    except ImportError:
        col_pdf.warning("Для PDF нужен пакет pymupdf: «py -m pip install pymupdf». Пока можно скачать .xlsx.")
    col_xlsx.download_button("⬇️ Скачать .xlsx (можно править)", data=plan_dia.plan_a_xlsx(plan),
                             file_name=plan_dia.nombre_archivo(plan, "xlsx"),
                             mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="plan_dia_xlsx")
    if ins.fuera_del_catalogo:
        st.caption("Продаются, но в листе их нет (план не строится): " + ", ".join(ins.fuera_del_catalogo[:8]) + ".")
    st.divider()
    _seccion_plan_semana(engine, sucursal, hoy, ins, usar, colchon)
