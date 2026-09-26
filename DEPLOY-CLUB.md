# Publicar El Molino Club

Esta configuración publica la API, la PWA y el panel del equipo en un único
servicio HTTPS. El dashboard de Streamlit sigue siendo un servicio aparte;
ambos usan el mismo `DATABASE_URL`.

## Render

1. Sube el código del proyecto a un repositorio privado de GitHub. Verifica que
   `.env`, `el_molino.db` y las exportaciones de `data/` queden fuera del commit.
2. En Render, crea un **Blueprint** desde ese repositorio. `render.yaml` define
   `el-molino-club` como servicio web Python y configura `/health`.
3. Render solicitará las variables con `sync: false`. Copia sus valores del
   `.env` local al formulario de Render, sin pegarlos en GitHub ni en el chat:
   `DATABASE_URL`, `AUTH_TOKEN_SECRET`, `ADMIN_API_KEY`, `CASHIER_API_KEY`,
   `LABSMOBILE_USERNAME`, `LABSMOBILE_API_TOKEN`.
4. Tras el despliegue, comprueba `https://<host>/health`, abre
   `https://<host>/` y `https://<host>/staff.html`. Usa las claves de caja y
   gerencia actuales. Para una prueba de SMS, usa únicamente un número propio.

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
