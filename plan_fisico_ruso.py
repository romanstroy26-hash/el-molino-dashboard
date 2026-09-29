"""
plan_fisico_ruso.py -- Bloque: plan de produccion FISICO (papel, foto/PDF)
de "El Molino Ruso", 22 ago -- 28 sep 2026 -- importado UNA VEZ desde la
carpeta de Google Drive "El Molino Ruso - Planes de Produccion" (a pedido de
Roman, 2026-09-29). NO es un pipeline automatico -- estos datos no se
actualizan solos; si aparecen mas fotos de planes, hay que repetir la
extraccion a mano (pdfplumber, columna "TOTAL" de la tabla de cada PDF).

PLAN_POR_DIA -- total de piezas planeadas ese dia (Panaderia + Pasteleria
juntas, tal como se produce y se plane en papel) -- clave: fecha ISO.

PLAN_POR_PRODUCTO -- total de piezas planeadas por posicion de menu, SUMADO
sobre TODO el periodo de arriba -- clave: nombre tal como aparece en el PDF
(sin normalizar); metrics.py normaliza (acentos, mayusculas, punto final) al
comparar contra el nombre real de la base.
"""

PLAN_POR_DIA = {
    "2026-08-22": 1413.0,
    "2026-09-01": 1099.0,
    "2026-09-02": 1045.0,
    "2026-09-03": 1045.0,
    "2026-09-04": 1126.0,
    "2026-09-05": 1322.0,
    "2026-09-06": 1258.0,
    "2026-09-07": 1111.0,
    "2026-09-08": 1099.0,
    "2026-09-09": 1045.0,
    "2026-09-10": 1053.0,
    "2026-09-11": 1136.0,
    "2026-09-12": 1276.0,
    "2026-09-13": 1386.0,
    "2026-09-14": 956.0,
    "2026-09-15": 1495.0,
    "2026-09-16": 1495.0,
    "2026-09-17": 1050.0,
    "2026-09-18": 1076.0,
    "2026-09-19": 1088.0,
    "2026-09-20": 1199.0,
    "2026-09-21": 956.0,
    "2026-09-22": 1004.0,
    "2026-09-23": 797.0,
    "2026-09-24": 874.0,
    "2026-09-25": 1076.0,
    "2026-09-26": 1088.0,
    "2026-09-27": 1199.0,
    "2026-09-28": 956.0,
}

PLAN_POR_PRODUCTO = {
    "Croissant Chocolate": 1476.0,
    "Croissant Frutos Rojos": 1476.0,
    "Concha Chocolate": 1452.0,
    "Croissant Frambuesa": 1356.0,
    "Croissant Pistache": 1344.0,
    "Vatrushka Rusa": 1344.0,
    "Concha Vainilla": 1224.0,
    "Croissant Natural": 1020.0,
    "Croissant Fresa": 996.0,
    "Nido Cereza": 984.0,
    "Roll Clásico": 936.0,
    "Roll De Canela": 822.0,
    "Roll Chocolate": 786.0,
    "Roll Pistache": 762.0,
    "Tusson Frances": 720.0,
    "Concha Fresa": 648.0,
    "Oreja Chica Natural": 640.0,
    "Tropezienne": 636.0,
    "Bostock": 632.0,
    "Danes Mango Maracuya": 624.0,
    "Mini Croissant Frutos": 588.0,
    "Mini Croissant Chocolate": 588.0,
    "Mini Croissant Pistache": 588.0,
    "Mini Croissant Mango Maracuya": 588.0,
    "Mini Croissant Mascarpone": 588.0,
    "Canasta De Fresa": 588.0,
    "Doble Chocolatin De Cafe": 584.0,
    "Panque Elote": 475.0,
    "Danes Guayaba": 456.0,
    "Salchicha": 415.0,
    "Baguette Serrano": 386.0,
    "Baguette Ch": 382.0,
    "Muffin Manzana": 365.0,
    "Mini Croissant Natural": 360.0,
    "Oreja Grande Natural": 335.0,
    "Berlina De Pistache": 320.0,
    "Berlina De Chocolate": 320.0,
    "Croffin De Dulce De Leche": 300.0,
    "Croffin De Limon Y Frambuesa": 297.0,
    "Panque Platano": 295.0,
    "Panque Zanahoria": 295.0,
    "Hogaza Integral": 290.0,
    "Berlina De Fresa": 264.0,
    "Muffin De Cafe De Ola": 260.0,
    "Muffin De Blueberries": 260.0,
    "Berlina De Muselina": 224.0,
    "Croissant Pechuga De Pavo": 216.0,
    "Hogaza Queso": 214.0,
    "Hogaza Lino": 214.0,
    "Berlina De Dulce De Leche": 212.0,
    "Tartaleta Fina De Bluebery": 196.0,
    "Tartaleta Fina De Frambuesa": 196.0,
    "Tartaleta Fina De Frutos Rojos": 196.0,
    "Tartaleta Fina De Zarzamora": 196.0,
    "Focaccia": 192.0,
    "Corbatin De Toffee": 156.0,
    "Corbatin De Fresa": 112.0,
    "Corbatin De Pistache": 96.0,
    "Tarta Frutos": 62.0,
    "Tarta Mango": 62.0,
    "Tarta Cereza": 62.0,
    "Tarta Higo": 52.0,
}
