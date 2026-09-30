"""
test_metrics.py -- pruebas de las funciones PURAS de metrics.py (sin
conexión a base de datos): aritmética de pronóstico, clasificación de
desviaciones, calendario de festivos. No cubre las funciones que hacen
SQL (analisis_abc, ventas_por_hora, etc.) -- esas se verifican a mano
contra la base real antes de cada publicación (ver el flujo de trabajo
del proyecto), porque simularlas con una base de prueba sería una capa
de mantenimiento aparte para un beneficio menor: lo que más se rompe en
silencio es la aritmética, no el SQL.
"""

import datetime as dt

import metrics


# ---- _delta_pct -------------------------------------------------------------

def test_delta_pct_positivo():
    assert metrics._delta_pct(110, 100) == 10.0


def test_delta_pct_negativo():
    assert metrics._delta_pct(90, 100) == -10.0


def test_delta_pct_pasado_cero():
    assert metrics._delta_pct(50, 0) is None


# ---- _percentil --------------------------------------------------------------

def test_percentil_extremos():
    valores = [10, 20, 30, 40]
    assert metrics._percentil(valores, 0.0) == 10
    assert metrics._percentil(valores, 1.0) == 40


def test_percentil_interpolado():
    valores = [10, 20, 30, 40]
    assert metrics._percentil(valores, 0.5) == 25.0


def test_percentil_lista_vacia():
    assert metrics._percentil([], 0.5) == 0.0


# ---- _recortar_atipicos -------------------------------------------------------

def test_recortar_atipicos_pocas_muestras_no_toca_nada():
    valores = [10, 12, 100]
    assert metrics._recortar_atipicos(valores) == [10, 12, 100]


def test_recortar_atipicos_winsoriza_el_extremo():
    valores = [10, 12, 11, 13, 100]
    resultado = metrics._recortar_atipicos(valores)
    # El outlier (100) se recorta al techo (Q3 + 1.5*RIC) en vez de
    # eliminarse -- el día sigue contando, solo que ya no arrastra el
    # promedio hacia arriba.
    assert resultado[-1] == 16.0
    assert resultado[:-1] == [10, 12, 11, 13]


# ---- _redondear_a_multiplo ----------------------------------------------------

def test_redondear_a_multiplo_redondea_hacia_arriba():
    assert metrics._redondear_a_multiplo(10, 6) == 12


def test_redondear_a_multiplo_ya_es_multiplo():
    assert metrics._redondear_a_multiplo(12, 6) == 12


def test_redondear_a_multiplo_valor_no_positivo():
    assert metrics._redondear_a_multiplo(0, 6) == 0
    assert metrics._redondear_a_multiplo(-5, 6) == 0


# ---- delta_color_significativo ------------------------------------------------

def test_delta_color_significativo_none():
    assert metrics.delta_color_significativo(None) == "off"


def test_delta_color_significativo_ruido():
    assert metrics.delta_color_significativo(2.0) == "off"


def test_delta_color_significativo_umbral_exacto():
    assert metrics.delta_color_significativo(metrics._UMBRAL_DESVIACION_PCT) == "normal"


def test_delta_color_significativo_desviacion_grande():
    assert metrics.delta_color_significativo(-12.0) == "normal"


# ---- is_coffee -----------------------------------------------------------------

def test_is_coffee_positivo():
    assert metrics.is_coffee("CAPUCCINO GDE", "CAFETERIA", ["CAPUCCINO"]) is True


def test_is_coffee_grupo_no_valido():
    assert metrics.is_coffee("CAPUCCINO", "PANADERIA", ["CAPUCCINO"]) is False


def test_is_coffee_sin_palabra_clave():
    assert metrics.is_coffee("CHAI LATTE", "CAFETERIA", ["CAPUCCINO", "ESPRESSO"]) is False


# ---- festivo_cercano -------------------------------------------------------------

def test_festivo_cercano_dia_exacto():
    resultado = metrics.festivo_cercano(dt.date(2026, 12, 25))
    assert resultado["nombre"] == "Navidad"
    assert resultado["dias_diferencia"] == 0


def test_festivo_cercano_vispera_cuenta_como_cercano():
    resultado = metrics.festivo_cercano(dt.date(2026, 1, 5), ventana_dias=1)
    assert resultado["nombre"] == "Día de Reyes"
    assert resultado["dias_diferencia"] == 1


def test_festivo_cercano_ninguno_cerca():
    assert metrics.festivo_cercano(dt.date(2026, 3, 10)) is None


def test_festivo_cercano_semana_santa_movil():
    resultado = metrics.festivo_cercano(dt.date(2026, 4, 2))
    assert resultado["nombre"] == "Jueves Santo"


# ---- _franja_de_hora --------------------------------------------------------------

def test_franja_de_hora_cubre_todo_el_horario():
    assert metrics._franja_de_hora(7) == "Утро (6-9)"
    assert metrics._franja_de_hora(12) == "Обед (10-14)"
    assert metrics._franja_de_hora(16) == "Полдник (15-17)"
    assert metrics._franja_de_hora(20) == "Вечер (18-22)"


def test_franja_de_hora_fuera_de_horario():
    assert metrics._franja_de_hora(3) is None


# ---- analizar_desempeno_por_hora -----------------------------------------------------

def _hora(h, real, tipico, real_unidades=None, tipico_unidades=None):
    return {
        "hora": h, "real": real, "tipico": tipico,
        "real_unidades": real if real_unidades is None else real_unidades,
        "tipico_unidades": tipico if tipico_unidades is None else tipico_unidades,
    }


def test_analizar_desempeno_por_hora_sin_pronostico_es_none():
    horas = [_hora(h, 100, None) for h in range(8, 12)]
    assert metrics.analizar_desempeno_por_hora(horas) is None


def test_analizar_desempeno_por_hora_distribuido():
    # Las mismas -20% en TODAS las horas -- el déficit no se concentra
    # en ninguna hora puntual.
    horas = [_hora(h, 80, 100) for h in range(8, 14)]
    resultado = metrics.analizar_desempeno_por_hora(horas)
    assert resultado["estado"] == "por_debajo"
    assert resultado["concentrado"] is False


def test_analizar_desempeno_por_hora_concentrado():
    # 10 horas normales, una sola muy floja -- el déficit se concentra
    # en esa hora, el resto del día se comportó como siempre.
    horas = [_hora(h, 100, 100) for h in range(8, 18)]
    horas[0]["real"] = 20
    horas[0]["real_unidades"] = 20
    resultado = metrics.analizar_desempeno_por_hora(horas)
    assert resultado["estado"] == "por_debajo"
    assert resultado["concentrado"] is True
    assert resultado["horas_criticas"][0]["hora"] == 8


def test_analizar_desempeno_por_hora_por_encima():
    horas = [_hora(h, 120, 100) for h in range(8, 14)]
    resultado = metrics.analizar_desempeno_por_hora(horas)
    assert resultado["estado"] == "por_encima"


# ---- analizar_desviacion_produccion --------------------------------------------------

def test_analizar_desviacion_produccion_detecta_tendencia():
    dias = [
        {"fecha": "2026-01-01", "real_unidades": 100, "pronostico_unidades": 100},
        {"fecha": "2026-01-02", "real_unidades": 100, "pronostico_unidades": 100},
        {"fecha": "2026-01-03", "real_unidades": 200, "pronostico_unidades": 100},
        {"fecha": "2026-01-04", "real_unidades": 200, "pronostico_unidades": 100},
    ]
    resultado = metrics.analizar_desviacion_produccion(dias, "pronostico_unidades")
    assert resultado["n_dias"] == 4
    assert resultado["tendencia_pct"] == 100.0


def test_analizar_desviacion_produccion_insuficientes_dias():
    dias = [{"fecha": "2026-01-01", "real_unidades": 100, "pronostico_unidades": None}]
    assert metrics.analizar_desviacion_produccion(dias, "pronostico_unidades") is None


# ---- precision_pronostico ------------------------------------------------------------

def test_precision_pronostico_calcula_mape_y_signo():
    dias = [
        {"fecha": "2026-01-01", "real_unidades": 110, "pronostico_unidades": 100},
        {"fecha": "2026-01-02", "real_unidades": 90, "pronostico_unidades": 100},
    ]
    resultado = metrics.precision_pronostico(dias)
    assert resultado["n_dias"] == 2
    assert resultado["mape"] == 10.0
    assert resultado["serie"][0]["error_pct"] == 10.0
    assert resultado["serie"][1]["error_pct"] == -10.0


def test_precision_pronostico_sin_datos():
    assert metrics.precision_pronostico([]) is None


def test_precision_pronostico_ignora_dias_sin_pronostico():
    dias = [{"fecha": "2026-01-01", "real_unidades": 100, "pronostico_unidades": None}]
    assert metrics.precision_pronostico(dias) is None


# ---- _racha_desviacion -----------------------------------------------------------------

def test_racha_desviacion_detecta_racha_consistente():
    target = dt.date(2026, 3, 16)  # lunes, fecha arbitraria
    valores: dict[dt.date, float] = {}
    # 10 semanas de historia, TODOS los días de la semana, en 100 parejo
    # -- así "lo típico" de cualquier día de esa ventana es exactamente
    # 100, sin importar el peso por recencia (todos los valores son
    # iguales).
    for semanas_atras in range(1, 11):
        for offset_dia in range(7):
            fecha = target - dt.timedelta(days=7 * semanas_atras - offset_dia)
            valores[fecha] = 100.0
    # Los últimos 3 días (terminando en target) quedan bien por debajo,
    # de forma consistente -- una racha real, no ruido de un solo día.
    for dias_atras in range(3):
        valores[target - dt.timedelta(days=dias_atras)] = 60.0

    racha = metrics._racha_desviacion(valores, target)
    assert racha is not None
    assert racha["dias"] == 3
    assert racha["direccion"] == "por_debajo"


def test_racha_desviacion_un_solo_dia_no_cuenta():
    target = dt.date(2026, 3, 16)
    valores: dict[dt.date, float] = {}
    for semanas_atras in range(1, 11):
        for offset_dia in range(7):
            fecha = target - dt.timedelta(days=7 * semanas_atras - offset_dia)
            valores[fecha] = 100.0
    valores[target] = 60.0  # solo el día target se desvía

    assert metrics._racha_desviacion(valores, target) is None


# ---- _banda_de_temp / ventas_por_banda_temperatura ------------------------------------

def test_banda_de_temp_cubre_todos_los_rangos():
    assert metrics._banda_de_temp(15) == "< 20°C"
    assert metrics._banda_de_temp(20) == "20-25°C"
    assert metrics._banda_de_temp(24.9) == "20-25°C"
    assert metrics._banda_de_temp(25) == "25-30°C"
    assert metrics._banda_de_temp(30) == "> 30°C"
    assert metrics._banda_de_temp(35) == "> 30°C"


def test_banda_de_temp_none():
    assert metrics._banda_de_temp(None) is None


def test_ventas_por_banda_temperatura_promedia_por_banda():
    dias = [
        {"fecha": "2026-01-01", "frappe_pct": 2.0},
        {"fecha": "2026-01-02", "frappe_pct": 4.0},
        {"fecha": "2026-01-03", "frappe_pct": 6.0},
        {"fecha": "2026-01-04", "frappe_pct": 10.0},
        {"fecha": "2026-01-05", "frappe_pct": 12.0},
        {"fecha": "2026-01-06", "frappe_pct": 14.0},
    ]
    clima = [
        {"fecha": "2026-01-01", "temp_max": 15.0},
        {"fecha": "2026-01-02", "temp_max": 16.0},
        {"fecha": "2026-01-03", "temp_max": 17.0},
        {"fecha": "2026-01-04", "temp_max": 32.0},
        {"fecha": "2026-01-05", "temp_max": 33.0},
        {"fecha": "2026-01-06", "temp_max": 34.0},
    ]
    resultado = metrics.ventas_por_banda_temperatura(dias, clima, "frappe_pct")
    assert resultado == [
        {"banda": "< 20°C", "n_dias": 3, "promedio": 4.0},
        {"banda": "> 30°C", "n_dias": 3, "promedio": 12.0},
    ]


def test_ventas_por_banda_temperatura_omite_bandas_con_pocos_dias():
    # Solo 2 días con clima conocido -- menos que _MIN_DIAS_BANDA_TEMPERATURA.
    dias = [
        {"fecha": "2026-01-01", "ventas_totales": 100.0},
        {"fecha": "2026-01-02", "ventas_totales": 200.0},
    ]
    clima = [
        {"fecha": "2026-01-01", "temp_max": 22.0},
        {"fecha": "2026-01-02", "temp_max": 23.0},
    ]
    assert metrics.ventas_por_banda_temperatura(dias, clima, "ventas_totales") is None


def test_ventas_por_banda_temperatura_ignora_dias_sin_clima():
    dias = [{"fecha": "2026-01-01", "ventas_totales": 100.0}]
    clima: list[dict] = []
    assert metrics.ventas_por_banda_temperatura(dias, clima, "ventas_totales") is None


# ---- _normaliza_nombre -------------------------------------------------------------

def test_normaliza_nombre_acentos_y_mayusculas():
    assert metrics._normaliza_nombre("Croissant Frambuesa") == "CROISSANT FRAMBUESA"


def test_normaliza_nombre_punto_final():
    assert metrics._normaliza_nombre("MACARONS.") == "MACARONS"


def test_normaliza_nombre_espacios_dobles():
    assert metrics._normaliza_nombre("Concha  Chocolate.") == "CONCHA CHOCOLATE"


# ---- estacionalidad_semana / texto_estacionalidad -----------------------------

def _serie_semanas(valores_por_dia_semana: dict[int, float], n_semanas: int = 4) -> list[dict]:
    """Genera una serie diaria de `n_semanas` semanas completas, repitiendo
    el mismo patrón por día de semana cada semana -- para tests de
    estacionalidad_semana, que necesita al menos 2 muestras por día."""
    base = dt.date(2026, 1, 5)  # lunes
    filas = []
    for semana in range(n_semanas):
        for dia in range(7):
            fecha = base + dt.timedelta(days=semana * 7 + dia)
            filas.append({"fecha": fecha.isoformat(), "ventas_totales": valores_por_dia_semana[dia]})
    return filas


def test_estacionalidad_semana_indice_100_dia_promedio():
    # Todos los días iguales -> índice 100 en todos.
    serie = _serie_semanas({i: 1000.0 for i in range(7)})
    indices = metrics.estacionalidad_semana(serie)
    assert len(indices) == 7
    assert all(d["indice"] == 100.0 for d in indices)


def test_estacionalidad_semana_dia_flojo_y_fuerte():
    valores = {i: 1000.0 for i in range(7)}
    valores[5] = 1500.0  # sábado fuerte
    valores[1] = 500.0   # martes flojo
    serie = _serie_semanas(valores)
    indices = {d["dia_semana"]: d["indice"] for d in metrics.estacionalidad_semana(serie)}
    assert indices["суббота"] > 100
    assert indices["вторник"] < 100


def test_estacionalidad_semana_pocas_muestras_se_omite():
    # Solo 1 semana -- no hay 2 muestras por día, no debe devolver nada.
    serie = _serie_semanas({i: 1000.0 for i in range(7)}, n_semanas=1)
    assert metrics.estacionalidad_semana(serie) == []


def test_estacionalidad_semana_lista_vacia():
    assert metrics.estacionalidad_semana([]) == []


def test_texto_estacionalidad_sin_desviacion_es_none():
    indices = [{"dia_semana": "lunes", "indice": 101.0, "n_dias": 4}]
    assert metrics.texto_estacionalidad(indices) is None


def test_texto_estacionalidad_con_desviacion():
    indices = [
        {"dia_semana": "суббота", "indice": 130.0, "n_dias": 4},
        {"dia_semana": "вторник", "indice": 80.0, "n_dias": 4},
    ]
    texto = metrics.texto_estacionalidad(indices)
    assert "суббота" in texto
    assert "вторник" in texto


# ---- generar_digest_dia -------------------------------------------------------

def test_generar_digest_dia_sin_senales_es_lista_vacia():
    resumen = {"dia_cerrado": True, "dia_semana": "понедельник", "ventas_vs_tipico_pct": 1.0, "racha": None}
    comparacion = {"dia_vs_semana_pasada": {"disponible": False}, "semana_vs_semana_pasada": {}}
    assert metrics.generar_digest_dia(resumen, comparacion, None) == []


def test_generar_digest_dia_racha_y_mezcla():
    resumen = {
        "dia_cerrado": True, "dia_semana": "понедельник",
        "ventas_vs_tipico_pct": 2.0,
        "racha": {"dias": 4, "direccion": "por_encima"},
    }
    comparacion = {"dia_vs_semana_pasada": {"disponible": False}, "semana_vs_semana_pasada": {}}
    mezcla = {"categoria": "Café", "pct": 30.0, "tipico_pct": 20.0, "dif_pt": 10.0, "festivo": None}
    digest = metrics.generar_digest_dia(resumen, comparacion, mezcla)
    assert any("день подряд" in t for t in digest)
    assert any("Café" in t for t in digest)


def test_generar_digest_dia_ordena_por_magnitud():
    resumen = {"dia_cerrado": False, "dia_semana": "понедельник", "racha": None}
    comparacion = {
        "dia_vs_semana_pasada": {"disponible": False},
        "semana_vs_semana_pasada": {"ventas_actual": 50.0, "ventas_pasada": 100.0},
    }
    mezcla = {"categoria": "Panadería", "pct": 55.0, "tipico_pct": 50.0, "dif_pt": 5.0, "festivo": None}
    digest = metrics.generar_digest_dia(resumen, comparacion, mezcla)
    # La caída semanal (-50%) es mucho más grande que el desvío de mezcla
    # (5 пт) -- debe aparecer primero.
    assert "7 дней" in digest[0]
