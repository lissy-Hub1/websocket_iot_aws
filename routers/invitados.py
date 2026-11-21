"""Práctica 4.3: «Prueba nuestros vehículos IoT» (catálogo público y sesión temporal de Invitado)."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from autorizacion import INVITADO, Identidad, identidad
from dependencies import Contenedor, get_contenedor
from models.plataforma import InvitadoSesion, InvitadoSolicitud, ModeloCatalogo
from models.respuestas import Mensaje

from .auth import ip_cliente
from .comun import BASE, E401, E403, E409

router = APIRouter(tags=["Invitados (4.3)"])


@router.get(
    "/catalogo", response_model=list[ModeloCatalogo], responses=BASE,
    summary="Catálogo público de modelos",
    description="Público. Modelos activos y sus unidades en EXHIBICIÓN con disponibilidad real. "
    "No expone inventario privado ni datos de compradores. **SP:** `sp_catalogo_publico`.",
)
async def catalogo(c: Contenedor = Depends(get_contenedor)):
    return await run_in_threadpool(c.invitados.catalogo)


@router.post(
    "/invitados/sesiones", response_model=InvitadoSesion, status_code=201, responses={**BASE, 409: E409},
    summary="Iniciar una prueba temporal como Invitado",
    description=(
        "Reserva EXCLUSIVA de una unidad de exhibición durante `INVITADO_MINUTOS`. Una segunda persona recibe "
        "409 (ocupada). Devuelve un token `inv_…` que solo permite los comandos marcados para Invitado en esa "
        "unidad. Al vencer, cancelar o desconectarse, la unidad recibe DETENER. **SP:** `sp_iniciar_sesion_invitado`."
    ),
)
async def iniciar(d: InvitadoSolicitud, request: Request, c: Contenedor = Depends(get_contenedor)):
    await c.limite_invitado.comprobar(f"invitado:{ip_cliente(request)}")
    sesion = await run_in_threadpool(c.invitados.iniciar, d.id_vehiculo)
    await run_in_threadpool(c.auditoria.registrar_actor, None, "INVITADO", "INVITADO_INICIA", "vehiculo",
                            d.id_vehiculo, "OK", None)
    return sesion


def _exigir_invitado(ident: Identidad) -> Identidad:
    if ident.tipo != INVITADO:
        raise HTTPException(status_code=403, detail="Esta ruta es para la prueba de Invitado")
    return ident


@router.get(
    "/invitados/sesion", response_model=InvitadoSesion, responses={**BASE, 401: E401, 403: E403},
    summary="Tiempo restante y comandos de la prueba",
    description="Requiere `Authorization: Bearer inv_…`. **SP:** `sp_validar_sesion_invitado`, `sp_comandos_invitado`.",
)
async def estado(ident: Identidad = Depends(identidad), c: Contenedor = Depends(get_contenedor)):
    _exigir_invitado(ident)
    return await run_in_threadpool(c.invitados.estado, ident.token_hash)


@router.delete(
    "/invitados/sesion", response_model=Mensaje, responses={**BASE, 401: E401, 403: E403},
    summary="Terminar la prueba (libera la unidad y la detiene)",
    description="**SP:** `sp_terminar_sesion_invitado`. Envía DETENER a la unidad.",
)
async def terminar(ident: Identidad = Depends(identidad), c: Contenedor = Depends(get_contenedor)):
    _exigir_invitado(ident)
    if await run_in_threadpool(c.invitados.terminar, ident.token_hash, "CANCELADA"):
        await c.registro.cerrar_token(ident.token_hash, "Terminaste la prueba")
        await c.paro.detener(ident.id_vehiculo, "FIN_INVITADO")
        c.control.liberar(ident.id_vehiculo)
        await c.auditoria.registrar_async(ident, "INVITADO_TERMINA", "vehiculo", ident.id_vehiculo)
    return Mensaje(mensaje="Prueba terminada")
