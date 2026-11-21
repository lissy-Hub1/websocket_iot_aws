"""Práctica 4.3: inicio de sesión con Google, sesión actual, cierre de sesión y salud."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from autorizacion import INVITADO, SERVICIO, Identidad, identidad
from config import Settings, get_settings
from dependencies import Contenedor, get_contenedor
from exceptions import ServicioNoDisponible
from models.plataforma import ConfigPublica, LoginGoogle, SesionRespuesta, UsuarioSesion
from models.respuestas import Mensaje

from .comun import BASE, E401, E403

router = APIRouter(tags=["Autenticación (4.3)"])


def ip_cliente(request: Request) -> str:
    """Detrás de Caddy (127.0.0.1) la IP real llega en X-Forwarded-For."""
    directa = request.client.host if request.client else "?"
    if directa in ("127.0.0.1", "::1"):
        return request.headers.get("x-forwarded-for", directa).split(",")[0].strip()
    return directa


@router.get(
    "/auth/config", response_model=ConfigPublica,
    summary="Configuración pública del login",
    description="Devuelve el Client ID de Google (público por diseño) y la duración de la prueba de Invitado.",
)
async def config_publica(settings: Settings = Depends(get_settings)):
    return ConfigPublica(google_client_id=settings.google_client_id, invitado_minutos=settings.invitado_minutos)


@router.post(
    "/auth/google", response_model=SesionRespuesta, responses={**BASE, 401: E401, 403: E403},
    summary="Iniciar sesión con Google",
    description=(
        "Recibe el **ID token** de Google Identity Services y lo verifica en el servidor (firma, audiencia "
        "`GOOGLE_CLIENT_ID`, emisor y correo verificado). Solo entran correos dados de alta por un Administrador "
        "o listados en `ADMIN_EMAILS`. **SP:** `sp_acceso_google`, `sp_ins_sesion`, `sp_ins_auditoria`.\n\n"
        "Devuelve un token de sesión: envíalo como `Authorization: Bearer <token>`."
    ),
)
async def login_google(datos: LoginGoogle, request: Request, c: Contenedor = Depends(get_contenedor)):
    await c.limite_login.comprobar(f"login:{ip_cliente(request)}")
    return await run_in_threadpool(c.auth.login, datos.credential)


@router.get(
    "/auth/yo", response_model=UsuarioSesion, responses={**BASE, 401: E401, 403: E403},
    summary="Cuenta de la sesión actual",
    description="**SP:** `sp_validar_sesion`. 401 si la sesión venció o se cerró.",
)
async def yo(ident: Identidad = Depends(identidad)):
    if ident.tipo in (SERVICIO, INVITADO):
        raise HTTPException(status_code=403, detail="Esta ruta es para cuentas con inicio de sesión")
    return UsuarioSesion(id_usuario=ident.id_usuario, email=ident.email, nombre=ident.nombre, rol=ident.tipo)


@router.post(
    "/auth/logout", response_model=Mensaje, responses={**BASE, 401: E401},
    summary="Cerrar sesión",
    description="Revoca el token en RDS (**SP:** `sp_cerrar_sesion`) y cierra los WebSocket abiertos con él.",
)
async def logout(ident: Identidad = Depends(identidad), c: Contenedor = Depends(get_contenedor)):
    if ident.token_hash and ident.tipo != INVITADO:
        await run_in_threadpool(c.auth.logout, ident.token_hash)
        await c.registro.cerrar_token(ident.token_hash, "Sesión cerrada")
        await c.auditoria.registrar_async(ident, "LOGOUT", "usuario", ident.id_usuario)
    return Mensaje(mensaje="Sesión cerrada")


@router.get(
    "/salud", responses={503: {"description": "RDS no disponible"}},
    summary="Salud de la API y diagnóstico real de RDS",
    description="Pública. 200 = la API respondió y RDS ejecutó `sp_salud`; 503 = RDS no disponible.",
)
async def salud(c: Contenedor = Depends(get_contenedor)):
    try:
        fila = await run_in_threadpool(c.plataforma.salud)
    except ServicioNoDisponible:
        raise HTTPException(status_code=503, detail="La base de datos no está disponible")
    return {"api": "disponible", "rds": "disponible" if fila.get("rds_disponible") == 1 else "sin_verificar",
            "fecha_utc": fila.get("fecha_utc")}
