"""Práctica 4.3: ADMINISTRACIÓN comercial (solo rol ADMIN o X-API-Key de servicio).

Dashboard, modelos, unidades (baja lógica), clientes/roles, asignaciones, comandos del Invitado y bitácora.
Cada alta, cambio de rol, asignación y baja queda en `auditoria`.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from autorizacion import Identidad, exigir_admin
from dependencies import Contenedor, get_contenedor
from models.plataforma import (
    Asignacion, ComandoInvitado, Dashboard, Modelo, ModeloActualizar, ModeloCrear, RegistroAuditoria,
    Revocacion, Unidad, UnidadActualizar, UnidadCrear, Usuario, UsuarioActualizar, UsuarioCrear,
)
from models.respuestas import Creado, Mensaje

from .comun import BASE, E401, E403, E404, E409

router = APIRouter(prefix="/admin", tags=["Administración (4.3)"])
R = {**BASE, 401: E401, 403: E403}
R_EDIT = {**R, 404: E404, 409: E409}


async def _operar(c: Contenedor, ident: Identidad, accion: str, recurso: str, id_recurso, funcion, *args,
                  errores: dict, detalle: Optional[dict] = None) -> dict:
    """Ejecuta un SP con banderas, traduce la bandera a HTTP y deja registro en auditoría."""
    fila = await run_in_threadpool(funcion, *args)
    ban = fila.get("ban")
    if ban != "0":
        codigo, mensaje = errores.get(ban, (400, "Operación rechazada"))
        await c.auditoria.registrar_async(ident, accion, recurso, id_recurso, "RECHAZADO", {"bandera": ban, **(detalle or {})})
        raise HTTPException(status_code=codigo, detail=mensaje)
    id_final = id_recurso if id_recurso is not None else next(
        (fila[k] for k in ("id_vehiculo", "id_modelo", "id_usuario") if k in fila), None)
    await c.auditoria.registrar_async(ident, accion, recurso, id_final, "OK", detalle)
    return fila


# ------------------------------------------------------------------ dashboard y bitácora
@router.get("/dashboard", response_model=Dashboard, responses=R, summary="Métricas reales del inventario",
            description="**SP:** `sp_dashboard`. Todo sale de RDS; nada es simulado.")
async def dashboard(_: Identidad = Depends(exigir_admin), c: Contenedor = Depends(get_contenedor)):
    return await run_in_threadpool(c.plataforma.dashboard)


@router.get("/auditoria", response_model=list[RegistroAuditoria], responses=R, summary="Bitácora de auditoría",
            description="**SP:** `sp_obtener_auditoria`. Paginada, de la más reciente a la más antigua.")
async def auditoria(limite: int = Query(50, ge=1, le=200), desde: int = Query(0, ge=0),
                    _: Identidad = Depends(exigir_admin), c: Contenedor = Depends(get_contenedor)):
    return await run_in_threadpool(c.plataforma.auditoria, limite, desde)


# ------------------------------------------------------------------ modelos
@router.get("/modelos", response_model=list[Modelo], responses=R, summary="Modelos comerciales",
            description="**SP:** `sp_obtener_modelos`.")
async def modelos(_: Identidad = Depends(exigir_admin), c: Contenedor = Depends(get_contenedor)):
    return await run_in_threadpool(c.plataforma.modelos)


@router.post("/modelos", response_model=Creado, status_code=201, responses=R_EDIT, summary="Registrar modelo",
             description="**SP:** `sp_ins_modelo`. 409 si el nombre ya existe.")
async def crear_modelo(d: ModeloCrear, ident: Identidad = Depends(exigir_admin), c: Contenedor = Depends(get_contenedor)):
    fila = await _operar(c, ident, "MODELO_CREAR", "modelo", None, c.plataforma.crear_modelo,
                         d.nombre, d.descripcion, d.imagen_url, errores={"1": (409, "Ya existe un modelo con ese nombre")},
                         detalle={"nombre": d.nombre})
    return Creado(id=int(fila["id_modelo"]), mensaje="Modelo registrado")


@router.put("/modelos/{id_modelo}", response_model=Mensaje, responses=R_EDIT, summary="Editar modelo",
            description="**SP:** `sp_upd_modelo`. `activo=false` lo retira del catálogo público.")
async def editar_modelo(id_modelo: int, d: ModeloActualizar, ident: Identidad = Depends(exigir_admin),
                        c: Contenedor = Depends(get_contenedor)):
    await _operar(c, ident, "MODELO_EDITAR", "modelo", id_modelo, c.plataforma.actualizar_modelo,
                  id_modelo, d.nombre, d.descripcion, d.imagen_url, d.activo,
                  errores={"1": (404, "El modelo no existe"), "2": (409, "Ya existe un modelo con ese nombre")})
    return Mensaje(mensaje="Modelo actualizado")


# ------------------------------------------------------------------ unidades
@router.get("/unidades", response_model=list[Unidad], responses=R, summary="Inventario de unidades",
            description="**SP:** `sp_obtener_unidades` (vista `vwrptunidades`). `conectado` es el último valor "
            "registrado en RDS: no prueba que el microcontrolador esté en línea.")
async def unidades(estado: Optional[str] = Query(None, description="Filtra por estado comercial"),
                   buscar: Optional[str] = Query(None, max_length=80, description="Serie, nombre, modelo o correo"),
                   _: Identidad = Depends(exigir_admin), c: Contenedor = Depends(get_contenedor)):
    filas = await run_in_threadpool(c.plataforma.unidades)
    if estado:
        filas = [f for f in filas if f["estado"] == estado.upper()]
    if buscar:
        b = buscar.lower()
        filas = [f for f in filas if any(b in str(f.get(k) or "").lower()
                                         for k in ("numero_serie", "nombre", "modelo", "propietario_email"))]
    return filas


@router.post("/unidades", response_model=Creado, status_code=201, responses=R_EDIT, summary="Registrar unidad",
             description="**SP:** `sp_ins_unidad`. Copia el catálogo de comandos de otra unidad del mismo modelo. "
             "409 si el número de serie ya existe o el modelo está inactivo.")
async def crear_unidad(d: UnidadCrear, ident: Identidad = Depends(exigir_admin), c: Contenedor = Depends(get_contenedor)):
    fila = await _operar(c, ident, "UNIDAD_CREAR", "vehiculo", None, c.plataforma.crear_unidad,
                         d.id_modelo, d.numero_serie, d.nombre, d.descripcion, d.microcontrolador, d.estado,
                         errores={"1": (409, "Ese número de serie ya existe"),
                                  "2": (409, "El modelo no existe o está inactivo"),
                                  "3": (400, "Estado inicial inválido")},
                         detalle={"numero_serie": d.numero_serie})
    return Creado(id=int(fila["id_vehiculo"]), mensaje="Unidad registrada")


@router.put("/unidades/{id_vehiculo}", response_model=Mensaje, responses=R_EDIT, summary="Editar unidad o darla de baja",
            description="**SP:** `sp_upd_unidad`. `estado=INACTIVO` es baja lógica: la unidad y su historial se "
            "conservan. 409 si está asignada (revoca primero). Al salir de exhibición termina la prueba de Invitado.")
async def editar_unidad(id_vehiculo: int, d: UnidadActualizar, ident: Identidad = Depends(exigir_admin),
                        c: Contenedor = Depends(get_contenedor)):
    await _operar(c, ident, "UNIDAD_EDITAR", "vehiculo", id_vehiculo, c.plataforma.actualizar_unidad,
                  id_vehiculo, d.id_modelo, d.numero_serie, d.nombre, d.descripcion, d.microcontrolador, d.estado,
                  errores={"1": (404, "La unidad no existe"), "2": (409, "Ese número de serie ya existe"),
                           "3": (400, "Estado inválido"), "4": (409, "La unidad está asignada: revoca la asignación primero"),
                           "5": (404, "El modelo no existe")},
                  detalle={"estado": d.estado})
    if d.estado != "EXHIBICION" and await c.registro.cerrar_invitados_de_unidad(id_vehiculo, "La unidad salió de exhibición"):
        await c.paro.detener(id_vehiculo, "PARO_ADMIN")
    return Mensaje(mensaje="Unidad actualizada")


@router.post("/unidades/{id_vehiculo}/asignar", response_model=Mensaje, responses=R_EDIT,
             summary="Asignar (vender) una unidad a un comprador",
             description="**SP:** `sp_asignar_unidad`. Cierra la asignación anterior (queda en `asignaciones`), "
             "revoca el soporte autorizado y **cierra de inmediato** los WebSocket del dueño anterior.")
async def asignar(id_vehiculo: int, d: Asignacion, ident: Identidad = Depends(exigir_admin),
                  c: Contenedor = Depends(get_contenedor)):
    fila = await _operar(c, ident, "ASIGNAR", "vehiculo", id_vehiculo, c.plataforma.asignar,
                         id_vehiculo, d.id_usuario, ident.id_usuario,
                         errores={"1": (404, "La unidad no existe o está dada de baja"),
                                  "2": (409, "El comprador no existe, está inactivo o no tiene rol Usuario"),
                                  "3": (409, "La unidad ya pertenece a ese comprador")},
                         detalle={"id_usuario": d.id_usuario})
    await c.registro.cerrar_usuario_en_unidad(id_vehiculo, fila.get("id_propietario_anterior"), "La unidad cambió de propietario")
    await c.registro.cerrar_admins_de_unidad(id_vehiculo, "La unidad fue vendida")
    if await c.registro.cerrar_invitados_de_unidad(id_vehiculo, "La unidad fue vendida"):
        await c.paro.detener(id_vehiculo, "PARO_ADMIN")
    c.control.liberar(id_vehiculo)
    return Mensaje(mensaje="Unidad asignada")


@router.post("/unidades/{id_vehiculo}/revocar", response_model=Mensaje, responses=R_EDIT,
             summary="Quitar el propietario de una unidad",
             description="**SP:** `sp_revocar_unidad`. El historial de asignaciones se conserva.")
async def revocar(id_vehiculo: int, d: Revocacion, ident: Identidad = Depends(exigir_admin),
                  c: Contenedor = Depends(get_contenedor)):
    fila = await _operar(c, ident, "REVOCAR", "vehiculo", id_vehiculo, c.plataforma.revocar,
                         id_vehiculo, ident.id_usuario, d.estado,
                         errores={"1": (409, "La unidad no está asignada"), "2": (400, "Estado inválido")},
                         detalle={"estado": d.estado})
    await c.registro.cerrar_usuario_en_unidad(id_vehiculo, fila.get("id_propietario_anterior"), "Se revocó tu acceso a la unidad")
    c.control.liberar(id_vehiculo)
    return Mensaje(mensaje="Asignación revocada")


@router.put("/unidades/{id_vehiculo}/comandos/{id_comando}/invitado", response_model=Mensaje, responses=R_EDIT,
            summary="Permitir o quitar un comando en la prueba de Invitado",
            description="**SP:** `sp_upd_comando_invitado`.")
async def comando_invitado(id_vehiculo: int, id_comando: int, d: ComandoInvitado,
                           ident: Identidad = Depends(exigir_admin), c: Contenedor = Depends(get_contenedor)):
    await _operar(c, ident, "COMANDO_INVITADO", "comando", id_comando, c.plataforma.comando_invitado,
                  id_vehiculo, id_comando, d.permitido,
                  errores={"1": (404, "El comando no pertenece a esa unidad")}, detalle={"permitido": d.permitido})
    return Mensaje(mensaje="Comando actualizado")


# ------------------------------------------------------------------ clientes y roles
@router.get("/usuarios", response_model=list[Usuario], responses=R, summary="Cuentas (Administradores y compradores)",
            description="**SP:** `sp_obtener_usuarios` (vista `vwrptusuarios`).")
async def usuarios(_: Identidad = Depends(exigir_admin), c: Contenedor = Depends(get_contenedor)):
    return await run_in_threadpool(c.plataforma.usuarios)


@router.post("/usuarios", response_model=Creado, status_code=201, responses=R_EDIT, summary="Dar de alta un cliente o admin",
             description="**SP:** `sp_ins_usuario`. La persona entra con la cuenta de Google de ese correo.")
async def crear_usuario(d: UsuarioCrear, ident: Identidad = Depends(exigir_admin), c: Contenedor = Depends(get_contenedor)):
    fila = await _operar(c, ident, "USUARIO_CREAR", "usuario", None, c.plataforma.crear_usuario,
                         d.email, d.nombre, d.rol, ident.id_usuario,
                         errores={"1": (409, "Ese correo ya está registrado"), "2": (400, "Rol inválido"),
                                  "3": (400, "Correo inválido")},
                         detalle={"rol": d.rol})
    return Creado(id=int(fila["id_usuario"]), mensaje="Cuenta registrada")


@router.put("/usuarios/{id_usuario}", response_model=Mensaje, responses=R_EDIT, summary="Cambiar nombre, rol o dar de baja",
            description="**SP:** `sp_upd_usuario`. Al cambiar rol o dar de baja se revocan sus sesiones y se cierran "
            "sus WebSocket. No se puede dejar el sistema sin Administradores.")
async def editar_usuario(id_usuario: int, d: UsuarioActualizar, ident: Identidad = Depends(exigir_admin),
                         c: Contenedor = Depends(get_contenedor)):
    await _operar(c, ident, "USUARIO_EDITAR", "usuario", id_usuario, c.plataforma.actualizar_usuario,
                  id_usuario, d.nombre, d.rol, d.activo,
                  errores={"1": (404, "La cuenta no existe"), "2": (400, "Rol inválido"),
                           "3": (409, "Debe quedar al menos un Administrador activo"),
                           "4": (409, "Tiene unidades asignadas: revócalas antes de darlo de baja")},
                  detalle={"rol": d.rol, "activo": d.activo})
    await c.registro.cerrar_usuario(id_usuario, "Tu cuenta cambió; vuelve a iniciar sesión")
    return Mensaje(mensaje="Cuenta actualizada")


@router.delete("/usuarios/{id_usuario}", response_model=Mensaje, responses=R_EDIT,
               summary="Eliminar una cuenta sin historial",
               description="**SP:** `sp_del_usuario`. Borra cuentas que nunca iniciaron sesión (p. ej. un correo mal "
               "escrito, aunque se les haya asignado una unidad por error) o que no tienen historial. Si ya usó la "
               "plataforma responde 409: usa la baja lógica "
               "(`PUT /admin/usuarios/{id}` con `activo=false`). No puedes eliminar tu propia cuenta.")
async def eliminar_usuario(id_usuario: int, ident: Identidad = Depends(exigir_admin),
                           c: Contenedor = Depends(get_contenedor)):
    if ident.id_usuario == id_usuario:
        raise HTTPException(status_code=409, detail="No puedes eliminar tu propia cuenta")
    await _operar(c, ident, "USUARIO_ELIMINAR", "usuario", id_usuario, c.plataforma.eliminar_usuario, id_usuario,
                  errores={"1": (404, "La cuenta no existe"),
                           "2": (409, "Debe quedar al menos un Administrador activo"),
                           "3": (409, "Esta cuenta ya usó la plataforma y tiene historial: dala de baja en lugar de eliminarla"),
                           "4": (409, "La cuenta tiene una unidad asignada: revócala primero en Unidades")})
    await c.registro.cerrar_usuario(id_usuario, "Tu cuenta fue eliminada")
    return Mensaje(mensaje="Cuenta eliminada")
