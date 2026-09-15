# Changelog

Todos los cambios notables de este proyecto se documentan en este fichero.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y este proyecto
usa [Versionado Semántico](https://semver.org/lang/es/) (mayor.menor.parche).

## [1.0.0] - 2026-09-15

Primera versión pública.

### Añadido

- Búsqueda y monitorización de productos de segunda mano en Wallapop, Milanuncios, CEX y Cash
  Converters.
- Multiusuario: cada usuario gestiona sus propias búsquedas de forma independiente.
- Búsquedas independientes por producto, con su propio rango de precio y resultados.
- Filtrado de disponibilidad: solo se muestran productos que siguen a la venta.
- Deduplicación: los productos ya registrados no se vuelven a mostrar como "nuevos".
- Eliminación (soft delete) de resultados no interesantes, con apartado "Eliminados" por
  búsqueda.
- Reescaneo automático configurable por búsqueda (APScheduler).
- Notificaciones opcionales por email (SMTP) y Telegram, con interruptor por búsqueda.
- Despliegue con Docker Compose (`docker compose up -d --build`), con `SECRET_KEY` autogenerada
  y datos persistentes en un volumen.

[1.0.0]: https://github.com/0herculabs/wallabot/releases/tag/v1.0.0
