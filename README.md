# Electronics Store

Tienda online ficticia de electrónica, construida como proyecto de portfolio de seguridad y cloud. No procesa pagos reales: es la excusa para mostrar un ciclo completo de **construcción segura** (Fase 1), sobre el que después se apoya un proyecto de monitoreo, detección y respuesta (Fase 2).

> **Transparencia:** diseñé la arquitectura y tomé las decisiones, pero soy nuevo escribiendo código e infraestructura. Usé Claude (IA) para generar código y comandos, y yo los ejecuté, probé y depuré. Cada herramienta elegida tiene documentadas las alternativas descartadas y el motivo.

## Estado actual

| Estado | Qué |
|---|---|
| ✅ **Funciona en local** | Frontend con Nginx, API de Productos, API de Pedidos, PostgreSQL, login con Amazon Cognito (sobre el emulador Floci) y MFA opcional por TOTP, historial de pedidos por usuario |
| ✅ **Automatizado** | CI en GitHub Actions: tests unitarios, tests de integración de Pedidos (seguridad por filas y validación de tokens contra Floci) y análisis estático con Semgrep |
| 🛠️ **En desarrollo** | Terraform contra Floci (Cognito, repositorios ECR y una guarda que verifica la cuenta antes de aplicar) |
| 📐 **Planificado** | Base de datos en Amazon RDS, Kubernetes, gestión de secretos, DAST, Compliance as Code y despliegue en una cuenta real de AWS |

**Todavía no corre en AWS real.** Todo lo anterior se ejecuta en un emulador local.

## Arquitectura

- **Frontend:** plantilla Electro (HTML/Bootstrap, sin React), servida por Nginx, que es el único punto de entrada.
- **Productos:** API en Python (FastAPI) con catálogo de 5 categorías y 18 productos de ejemplo.
- **Pedidos:** API en Python (FastAPI). Cada usuario ve solo sus pedidos y el precio y el total se calculan en el servidor.
- **Usuarios:** delegado a Amazon Cognito (registro, login y verificación en dos pasos opcional con TOTP). No hay un servicio propio.
- **Datos:** PostgreSQL, con un rol de base distinto para cada servicio.
- **Local:** un solo `docker-compose.yml` levanta todo, incluido Floci.

## Seguridad aplicada

- Validación de cada token en el servidor (firma, emisor, tipo, cliente y vencimiento).
- Permisos mínimos por servicio en la base y seguridad por filas (Row-Level Security) para aislar los pedidos de cada usuario.
- Límites de uso: 10 pedidos por hora por usuario y 30 solicitudes por minuto por IP en Nginx.
- Nginx sin versión visible y con cabeceras de seguridad (CSP, nosniff, Referrer-Policy).
- Contenedores endurecidos: sin root, sistema de archivos de solo lectura, sin capacidades innecesarias, imágenes con versión fija.
- Dependencias fijadas con hashes; librerías de CDN con `integrity`.
- Nada sensible en el navegador: el frontend nunca decide precios ni totales, y los datos externos se insertan como texto, nunca como HTML.
- Sin credenciales en el código: todo sale de variables de entorno.

## Plan para AWS real

El destino es una cuenta de AWS dedicada, dentro del free tier. Antes de desplegar:

1. Confirmar el estado real del free tier y configurar AWS Budgets con alertas.
2. Reemplazar PostgreSQL local por Amazon RDS y mover los secretos a AWS Secrets Manager.
3. Subir las imágenes a un registro privado (ECR) y definir cómo se ejecutan (Kubernetes u otra opción, según costo).
4. Privilegio mínimo en IAM, sin usuario raíz, ningún recurso público por defecto y etiquetas en todo desde Terraform.
5. Crear los recursos solo mientras se trabaja y destruirlos al terminar cada sesión.

El vínculo con la Fase 2 será un rol de solo lectura permanente y otro de mayor privilegio de uso puntual, mediante AWS STS AssumeRole.

## Límites declarados

1. No hay despliegue en AWS real ni Kubernetes todavía.
2. No hay pagos: la tienda no procesa transacciones reales.
3. Las imágenes de productos son de la plantilla y se van a reemplazar.
4. El DAST, Compliance as Code y la gestión de secretos están planificados, no hechos.

## Estructura

- `frontend/`: sitio estático (plantilla Electro) y configuración de Nginx.
- `services/productos/` y `services/pedidos/`: APIs y sus tests.
- `terraform/`: infraestructura como código.
- `.github/workflows/`: pipeline de CI.

## Licencias

El código propio se rige por la licencia del repositorio (`LICENSE`). La plantilla Electro conserva su licencia en `frontend/LICENSE.txt` y mantiene el enlace «Designed By HTML Codex» que ella exige.
