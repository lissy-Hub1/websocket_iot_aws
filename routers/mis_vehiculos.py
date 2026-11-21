"""Práctica 4.3: «Mis vehículos» del comprador, soporte autorizado y editor de demos."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool

from autorizacion import ADMIN, SERVICIO, USUARIO, Identidad, exigir_cuenta, exigir_tipos, permiso_unidad
from dependencies import Contenedor, get_contenedor
from models.plataforma import DemoEditor, DemoResumen, MiVehiculo, SoporteSolicitud
from models.respuestas import Creado, Mensaje

from .comun import BASE, E401, E403, E404, E409

router = APIRouter(tags=["Mis vehículos y demos (4.3)"])
R = {**BASE, 401: E401, 403: E403, 404: E404}
exigir_usuario = exigir_tipos(USUARIO)


@router.get(
    "/mis-vehiculos", response_model=list[MiVehiculo], responses=R,
    summary="Unidades que esta cuenta puede operar",
    description=(
        "Usuario: SOLO sus unidades asignadas (**SP:** `sp_mis_vehiculos`). Administrador: unidades de la "
        "empresa no vendidas (disponibles, exhibición). Las unidades vendidas solo aparecen al Admin si el "
        "comprador autorizó soporte."
    ),
)
async def mis_vehiculos(ident: Identidad = Depends(exigir_cuenta), c: Contenedor = Depends(get_contenedor)):
    if ident.tipo == USUARIO:
        return await run_in_threadpool(c.plataforma.mis_vehiculos, ident.id_usuario)
    filas = await run_in_threadpool(c.plataforma.unidades)
    resultado = []
    for f in filas:
        if f["estado"] in ("DISPONIBLE", "EXHIBICION"):
            motivo = "EMPRESA"
        elif f["estado"] == "ASIGNADO" and ident.tipo == ADMIN and (
            await run_in_threadpool(c.plataforma.permiso_unidad, ident.id_usuario, f["id_vehiculo"])
        ).get("motivo") == "SOPORTE":
            motivo = "SOPORTE"
        elif ident.tipo == SERVICIO:
            motivo = "EMPRESA"
        else:
            continue
        resultado.append({**f, "motivo": motivo})
    return resultado


@router.post(
    "/mis-vehiculos/{id_vehiculo}/soporte", response_model=Mensaje, responses=R,
    summary="Autorizar soporte del Administrador en mi unidad",
    description="El comprador da consentimiento por tiempo limitado. **SP:** `sp_otorgar_soporte`.",
)
async def otorgar_soporte(id_vehiculo: int, d: SoporteSolicitud, ident: Identidad = Depends(exigir_usuario),
                          c: Contenedor = Depends(get_contenedor)):
    fila = await run_in_threadpool(c.plataforma.otorgar_soporte, id_vehiculo, ident.id_usuario, d.minutos)
    if fila.get("ban") != "0":
        await c.auditoria.registrar_async(ident, "SOPORTE_OTORGA", "vehiculo", id_vehiculo, "RECHAZADO")
        raise HTTPException(status_code=403, detail="Solo el propietario puede autorizar soporte")
    await c.auditoria.registrar_async(ident, "SOPORTE_OTORGA", "vehiculo", id_vehiculo, "OK", {"minutos": d.minutos})
    return Mensaje(mensaje=f"Soporte autorizado por {d.minutos} minutos")


@router.delete(
    "/mis-vehiculos/{id_vehiculo}/soporte", response_model=Mensaje, responses=R,
    summary="Retirar la autorización de soporte",
    description="**SP:** `sp_revocar_soporte`. Cierra de inmediato los WebSocket del Administrador en esa unidad.",
)
async def revocar_soporte(id_vehiculo: int, ident: Identidad = Depends(exigir_usuario),
                          c: Contenedor = Depends(get_contenedor)):
    fila = await run_in_threadpool(c.plataforma.revocar_soporte, id_vehiculo, ident.id_usuario)
    if fila.get("ban") != "0":
        raise HTTPException(status_code=403, detail="Solo el propietario puede retirar el soporte")
    await c.registro.cerrar_admins_de_unidad(id_vehiculo, "El propietario retiró el soporte")
    await c.auditoria.registrar_async(ident, "SOPORTE_REVOCA", "vehiculo", id_vehiculo)
    return Mensaje(mensaje="Soporte retirado")


# ------------------------------------------------------------------ editor de demos
@router.get(
    "/vehiculos/{id_vehiculo}/demos-editor", response_model=list[DemoResumen], responses=R,
    summary="Demos de la unidad para el editor",
    description="Demos de FÁBRICA de la unidad + demos PRIVADAS propias, con número de pasos, duración total y "
    "si esta cuenta puede editarlas. **SP:** `sp_obtener_demos_usuario`.",
)
async def demos_editor(id_vehiculo: int, ident: Identidad = Depends(permiso_unidad("ver")),
                       c: Contenedor = Depends(get_contenedor)):
    return await run_in_threadpool(c.editor.listar, id_vehiculo, ident.tipo, ident.id_usuario)


@router.post(
    "/vehiculos/{id_vehiculo}/demos-editor", response_model=Creado, status_code=201, responses={**R, 409: E409},
    summary="Crear una demo con sus pasos",
    description=(
        "Usuario → demo PRIVADA en su unidad; Administrador → demo de FÁBRICA. Encabezado y pasos se guardan en una "
        "transacción. Cada paso debe usar un comando activo de ESA unidad; límites: 30 pasos, 5 s por paso, 5 s de "
        "pausa y 120 s en total. **SP:** `sp_crear_demo_editor`, `sp_agregar_movimiento_demo`."
    ),
)
async def crear_demo(id_vehiculo: int, d: DemoEditor, ident: Identidad = Depends(permiso_unidad("operar")),
                     c: Contenedor = Depends(get_contenedor)):
    _no_invitado(ident)
    id_demo = await run_in_threadpool(c.editor.crear, id_vehiculo, ident.tipo, ident.id_usuario, d)
    await c.auditoria.registrar_async(ident, "DEMO_CREAR", "demo", id_demo, "OK", {"pasos": len(d.pasos)})
    return Creado(id=id_demo, mensaje="Demo guardada")


@router.put(
    "/vehiculos/{id_vehiculo}/demos-editor/{id_demo}", response_model=Mensaje, responses={**R, 409: E409},
    summary="Guardar cambios de una demo (reemplaza sus pasos)",
    description="Solo el dueño de una demo PRIVADA o un Administrador en una de FÁBRICA. 409 si se está ejecutando. "
    "**SP:** `sp_actualizar_demo`, `sp_vaciar_pasos_demo`, `sp_agregar_movimiento_demo`.",
)
async def guardar_demo(id_vehiculo: int, id_demo: int, d: DemoEditor,
                       ident: Identidad = Depends(permiso_unidad("operar")), c: Contenedor = Depends(get_contenedor)):
    _no_invitado(ident)
    await run_in_threadpool(c.editor.guardar, id_vehiculo, id_demo, ident.tipo, ident.id_usuario, d)
    await c.auditoria.registrar_async(ident, "DEMO_GUARDAR", "demo", id_demo, "OK", {"pasos": len(d.pasos)})
    return Mensaje(mensaje="Demo guardada")


@router.delete(
    "/vehiculos/{id_vehiculo}/demos-editor/{id_demo}", response_model=Mensaje, responses={**R, 409: E409},
    summary="Eliminar una demo",
    description="Mismas reglas que editar. **SP:** `sp_eliminar_demo`.",
)
async def eliminar_demo(id_vehiculo: int, id_demo: int, ident: Identidad = Depends(permiso_unidad("operar")),
                        c: Contenedor = Depends(get_contenedor)):
    _no_invitado(ident)
    await run_in_threadpool(c.editor.eliminar, id_vehiculo, id_demo, ident.tipo, ident.id_usuario)
    await c.auditoria.registrar_async(ident, "DEMO_ELIMINAR", "demo", id_demo)
    return Mensaje(mensaje="Demo eliminada")


def _no_invitado(ident: Identidad) -> None:
    if ident.tipo not in (USUARIO, ADMIN, SERVICIO):
        raise HTTPException(status_code=403, detail="El Invitado no puede crear ni editar demos")
