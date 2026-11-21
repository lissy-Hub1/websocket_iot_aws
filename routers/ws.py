"""Endpoint WebSocket por vehículo (no aparece en Swagger; ver README).

4.3: el primer mensaje del cliente debe autenticar el canal, en menos de 10 s:
    {"tipo": "auth", "token": "<token de sesión o inv_…>"}   o   {"tipo": "auth", "api_key": "<X-API-Key>"}
Se comprueba el permiso sobre ESA unidad. Códigos de cierre: 4401 sin autenticación válida,
4403 sin permiso (también cuando se pierde después), 4404 vehículo inexistente.
"""
import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool

from autorizacion import INVITADO, SERVICIO, Identidad, comprobar_unidad, es_api_key_valida, resolver_token
from config import get_settings
from dependencies import Contenedor, get_contenedor_ws
from exceptions import ErrorDeNegocio, NoEncontrado
from models.eventos import EventoWS, TipoEvento
from websocket.autorizados import SocketAutorizado

ESPERA_AUTH_S = 10
GRACIA_INVITADO_S = 20  # si el Invitado no se reconecta en este tiempo, su prueba termina y la unidad se detiene


async def _autenticar(websocket: WebSocket, c: Contenedor, id_vehiculo: int):
    try:
        texto = await asyncio.wait_for(websocket.receive_text(), timeout=ESPERA_AUTH_S)
        datos = json.loads(texto)
    except (asyncio.TimeoutError, ValueError, WebSocketDisconnect):
        return None, 4401, "Falta el mensaje de autenticación"
    if not isinstance(datos, dict) or datos.get("tipo") != "auth":
        return None, 4401, "Falta el mensaje de autenticación"
    if datos.get("api_key"):
        if not es_api_key_valida(str(datos["api_key"]), get_settings()):
            return None, 4401, "API key inválida"
        ident = Identidad(SERVICIO)
    else:
        try:
            ident = await run_in_threadpool(resolver_token, c, str(datos.get("token") or ""))
        except ErrorDeNegocio:
            return None, 1013, "Base de datos no disponible"
        if ident is None:
            return None, 4401, "Sesión vencida o inválida"
    try:
        await comprobar_unidad(c, ident, id_vehiculo, "ver")
    except HTTPException as exc:
        return None, (4404 if exc.status_code == 404 else 4403), str(exc.detail)[:120]
    return ident, None, None


async def _tras_desconexion_invitado(c: Contenedor, ident: Identidad) -> None:
    """Pérdida de conexión del Invitado: si no vuelve a conectarse, termina su prueba y se detiene la unidad."""
    await asyncio.sleep(GRACIA_INVITADO_S)
    if c.registro.hay_de_token(ident.token_hash):
        return
    try:
        if await run_in_threadpool(c.invitados.terminar, ident.token_hash, "DESCONEXION"):
            await c.paro.detener(ident.id_vehiculo, "FIN_INVITADO")
            c.control.liberar(ident.id_vehiculo)
            await c.auditoria.registrar_async(ident, "INVITADO_DESCONEXION", "vehiculo", ident.id_vehiculo)
    except Exception:
        log.exception("No se pudo cerrar la prueba del invitado tras la desconexión")

log = logging.getLogger("app_iot.ws")
router = APIRouter()


@router.websocket("/ws/vehiculos/{id_vehiculo}")
async def monitorear(websocket: WebSocket, id_vehiculo: int, c: Contenedor = Depends(get_contenedor_ws)):
    await websocket.accept()
    ident, codigo, motivo = await _autenticar(websocket, c, id_vehiculo)
    if ident is None:
        await websocket.close(code=codigo, reason=motivo)
        return
    try:
        estado = await run_in_threadpool(c.estados.obtener, id_vehiculo)
    except NoEncontrado:
        await websocket.close(code=4404, reason="Vehiculo no encontrado")
        return
    except ErrorDeNegocio:
        await websocket.close(code=1013, reason="Base de datos no disponible")
        return

    c.manager.conectar(id_vehiculo, websocket)
    c.registro.agregar(SocketAutorizado(websocket, id_vehiculo, ident.tipo, ident.id_usuario, ident.token_hash))
    try:
        inicial = EventoWS(
            tipo=TipoEvento.ESTADO_INICIAL, id_vehiculo=id_vehiculo,
            comando=estado["comando"] if estado else None,
            codigo=estado["codigo"] if estado else None,
            id_comando=estado["id_comando"] if estado else None,
            conectado=bool(estado["conectado"]) if estado else False,
        )
        await c.manager.enviar(websocket, inicial)
        while True:
            texto = await websocket.receive_text()  # mantiene viva la conexión
            if texto.strip().lower() == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("Error en la conexión WebSocket del vehículo %s", id_vehiculo)
    finally:
        c.manager.desconectar(id_vehiculo, websocket)
        c.registro.quitar(websocket)
        if ident.tipo == INVITADO:
            asyncio.create_task(_tras_desconexion_invitado(c, ident))
