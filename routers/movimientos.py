from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from dependencies import Contenedor, get_contenedor
from models.eventos import EventoWS, TipoEvento
from models.historial import HistorialRespuesta, MovimientoRegistrado, MovimientoSolicitud
from autorizacion import INVITADO, Identidad, permiso_unidad
from services.invitado_service import comando_de_solicitud

from .comun import BASE, CON_404, E401, E403, E409

router = APIRouter(prefix="/vehiculos/{id_vehiculo}", tags=["Movimientos e historial"])


@router.post(
    "/movimientos", response_model=MovimientoRegistrado, status_code=201,
    responses={**CON_404, 409: E409, 401: E401, 403: E403},
    summary="Registrar un movimiento individual (requiere permiso para operar la unidad)",
    description=(
        "Ejecuta un comando **existente** del catálogo del vehículo (no crea comandos). "
        "Verifica que el vehículo exista y esté activo, y que el comando exista, esté activo y "
        "pertenezca a ese vehículo.\n\n"
        "**Stored Procedures (una sola transacción):** `sp_obtener_vehiculo`, `sp_obtener_comandos_vehiculo`, "
        "`sp_obtener_estado`, `sp_actualizar_estado`, `sp_registrar_historial`.\n\n"
        "Después del COMMIT se notifica por WebSocket (evento `movimiento`). `conectado` conserva el valor "
        "real del estado: una solicitud HTTP no lo vuelve verdadero. Si se rechaza el POST no cambia nada "
        "ni se emite evento.\n\n"
        "**4.3:** requiere sesión con permiso de operar la unidad (o X-API-Key). El Invitado solo puede usar los "
        "comandos permitidos de SU unidad. Si otra sesión la está operando responde 409, salvo DETENER, que "
        "siempre pasa."
    ),
)
async def registrar_movimiento(
    id_vehiculo: int, solicitud: MovimientoSolicitud,
    ident: Identidad = Depends(permiso_unidad("operar")), c: Contenedor = Depends(get_contenedor),
):
    espera = c.control.otro_operando(id_vehiculo, ident.clave_control)
    if ident.tipo == INVITADO or espera is not None:
        catalogo = await run_in_threadpool(c.invitados.catalogo_unidad, id_vehiculo)
        comando = comando_de_solicitud(catalogo, solicitud)
        es_detener = bool(comando) and comando["nombre"].upper() == "DETENER"
        if ident.tipo == INVITADO and not (comando and comando.get("permitido_invitado") and comando["activo"]):
            await c.auditoria.registrar_async(ident, "MOVIMIENTO", "vehiculo", id_vehiculo, "RECHAZADO",
                                              {"motivo": "comando_no_permitido"})
            raise HTTPException(status_code=403, detail="Ese comando no está habilitado en la prueba de Invitado")
        if espera is not None and not es_detener:
            raise HTTPException(status_code=409, detail=f"Otra sesión está operando esta unidad. Intenta en {espera} s.")
    c.control.marcar(id_vehiculo, ident.clave_control)
    resultado = await run_in_threadpool(c.movimientos.registrar, id_vehiculo, solicitud)
    notificados = await c.manager.difundir(
        id_vehiculo,
        EventoWS(
            tipo=TipoEvento.MOVIMIENTO, id_vehiculo=id_vehiculo,
            comando=resultado["comando"], codigo=resultado["codigo"], id_comando=resultado["id_comando"],
            origen=resultado["origen"], conectado=resultado["conectado"], timestamp=resultado["fecha_hora"],
        ),
    )
    return MovimientoRegistrado(**resultado, notificados=notificados)


@router.get(
    "/historial", response_model=HistorialRespuesta, responses=CON_404,
    summary="Últimos movimientos individuales (máximo 10)",
    description=(
        "**Stored Procedures:** `sp_obtener_vehiculo`, `sp_obtener_historial`. Solo lectura.\n\n"
        "Devuelve como máximo los 10 movimientos individuales más recientes, del más nuevo al más antiguo "
        "(si hay menos, solo los disponibles; el historial completo sigue en RDS). Los movimientos de DEMO "
        "nunca aparecen aquí. Lista vacía con 200 = vehículo sin movimientos; 404 = vehículo inexistente."
    ),
)
async def historial(
    id_vehiculo: int,
    _: Identidad = Depends(permiso_unidad("ver")),
    limite: int = Query(10, ge=1, le=10, description="Cantidad máxima (1 a 10)"),
    c: Contenedor = Depends(get_contenedor),
):
    filas = await run_in_threadpool(c.historial.ultimos, id_vehiculo, limite)
    return HistorialRespuesta(
        id_vehiculo=id_vehiculo, limite=limite, total_devueltos=len(filas), movimientos=filas
    )
