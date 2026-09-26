# Publicar El Molino Club

Esta configuración publica la API, la PWA y el panel del equipo en un único
servicio HTTPS. El dashboard de Streamlit sigue siendo un servicio aparte;
ambos usan el mismo `DATABASE_URL`.

## Servicio actual (26 de septiembre de 2026)

- Club: <https://el-molino-club.onrender.com/>
- Panel del equipo: <https://el-molino-club.onrender.com/staff.html>
- Estado: **Live** en Render; la comprobación interna `/health` pasó.
- Código: rama `main` de `romanstroy26-hash/el-molino-dashboard` en GitHub.
- Plan gratuito, Python 3.12. Construcción: `pip install -r requirements-api.txt`.
  Inicio: `uvicorn api:app --host 0.0.0.0 --port $PORT`.

El servicio se creó desde la opción **Public Git Repository** de Render. El
repositorio ya era público; `.env`, `el_molino.db` y las exportaciones de
`data/` no se subieron. Para publicar un cambio posterior, actualiza GitHub y,
si Render no inicia una nueva construcción, usa **Manual Deploy → Deploy latest
commit** en el servicio `el-molino-club`. `render.yaml` permite recrearlo como
Blueprint si se necesita en el futuro.

Las variables `DATABASE_URL`, `AUTH_TOKEN_SECRET`, `ADMIN_API_KEY`,
`CASHIER_API_KEY`, `LABSMOBILE_USERNAME` y `LABSMOBILE_API_TOKEN` están en el
entorno de Render. No copies sus valores a GitHub ni al chat. Para una prueba
de SMS, usa únicamente un número propio.

El plan gratuito de Render suspende el servicio tras un periodo de inactividad.
Para operación diaria con inicio de sesión por SMS, cambia el plan a uno que
mantenga el servicio activo. No guardes clientes ni ventas en el sistema de
archivos del servicio; la base compartida indicada por `DATABASE_URL` persiste
fuera de Render.

## Comprobaciones locales

```powershell
python -m pip install -r requirements-api.txt
python -m uvicorn api:app --host 127.0.0.1 --port 8000
```

`APP_ENV=production` exige las seis variables de producción; el proceso falla
al arrancar si falta alguna. `/health` devuelve 503 si la base de datos no
responde.
