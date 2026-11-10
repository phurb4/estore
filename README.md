# Electronics Store

Tienda online ficticia de electronica construida como proyecto de portfolio de DevSecOps y Cloud Security.
No procesa pagos reales: es una excusa tecnica para mostrar un ciclo completo de construccion segura.

## Que se va a mostrar
- Microservicios (Usuarios, Productos, Pedidos) en contenedores Docker, orquestados con Kubernetes.
- Base de datos PostgreSQL sobre Amazon RDS.
- Infraestructura como codigo con Terraform.
- Pipeline CI/CD con SAST y DAST, y hallazgos centralizados (Compliance as Code).
- Autenticacion con Amazon Cognito.
- Desarrollo local con Floci (emulador de AWS) antes de pasar a una cuenta real dentro del free tier.

## Estructura
- `frontend/`: sitio estatico basado en la plantilla Electro (HTML Codex, Bootstrap 5).

## Estado
En construccion. Fase 1: Secure by Design (build).

## Licencias
El codigo propio se rige por la licencia del repositorio. La plantilla Electro conserva su propia licencia en `frontend/LICENSE.txt`.
