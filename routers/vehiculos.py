from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool

from dependencies import Contenedor, get_contenedor
from models.respuestas import Creado, Mensaje
from models.vehiculo import Vehiculo, VehiculoActualizar, VehiculoCrear, VehiculoDetalle
from autorizacion import INVITADO, Identidad, demo_visible, exigir_admin, permiso_unidad

from .comun import BASE, CON_404, PROTEGIDO

router = APIRouter(prefix="/vehiculos", tags=["Vehículos"])


@router.get(
    "", response_model=list[Vehiculo], responses=BASE,
    summary="Listar todos los vehículos (Administrador)",
    description="**Stored Procedure:** `sp_obtener_vehiculos`. Solo lectura. 4.3: solo Administrador o X-API-Key.",
)
async def listar(_: Identidad = Depends(exigir_admin), c: Contenedor = Depends(get_contenedor)):
    return await run_in_threadpool(c.vehiculos.listar)


@router.get(
    "/{id_vehiculo}", response_model=VehiculoDetalle, responses=CON_404,
    summary="Consultar un vehículo con sus comandos, último estado y DEMO",
    description="**Stored Procedures:** `sp_obtener_vehiculo`, `sp_obtener_comandos_vehiculo`, "
    "`sp_obtener_estado`, `sp_obtener_demos`. Solo lectura. `estado` es `null` si aún no hay estado. "
    "4.3: requiere sesión con permiso sobre la unidad (propietario, Admin en unidad de la empresa o con soporte, "
    "o el Invitado de esa unidad).",
)
async def detalle(id_vehiculo: int, ident: Identidad = Depends(permiso_unidad("ver")),
                  c: Contenedor = Depends(get_contenedor)):
    datos = await run_in_threadpool(c.vehiculos.detalle, id_vehiculo)
    # 4.3: cada cuenta ve solo las demos que le corresponden; el Invitado, solo sus comandos permitidos
    datos["demos"] = [d for d in datos["demos"] if demo_visible(d, ident)]
    if ident.tipo == INVITADO:
        datos["comandos"] = [x for x in datos["comandos"] if x.get("permitido_invitado") and x["activo"]]
    return datos


@router.post(
    "", response_model=Creado, status_code=201, responses=BASE,
    summary="Crear un vehículo",
    description="**Stored Procedure:** `sp_crear_vehiculo`.",
)
async def crear(datos: VehiculoCrear, _: Identidad = Depends(exigir_admin), c: Contenedor = Depends(get_contenedor)):
    nuevo = await run_in_threadpool(c.vehiculos.crear, datos)
    return Creado(id=nuevo, mensaje="Vehículo creado")


@router.post(
    "/{id_vehiculo}/actualizar", response_model=Mensaje, responses=CON_404,
    summary="Actualizar un vehículo",
    description="**Stored Procedures:** `sp_obtener_vehiculo` (verifica existencia), `sp_actualizar_vehiculo`.",
)
async def actualizar(id_vehiculo: int, datos: VehiculoActualizar, _: Identidad = Depends(exigir_admin),
                     c: Contenedor = Depends(get_contenedor)):
    await run_in_threadpool(c.vehiculos.actualizar, id_vehiculo, datos)
    return Mensaje(mensaje="Vehículo actualizado")


@router.post(
    "/{id_vehiculo}/eliminar", response_model=Mensaje, responses=PROTEGIDO,
    dependencies=[Depends(exigir_admin)],
    summary="Eliminar un vehículo (solo Administrador o X-API-Key)",
    description="**Stored Procedure:** `sp_eliminar_vehiculo`. Borra en cascada sus comandos, demos, estado e historial.",
)
async def eliminar(id_vehiculo: int, c: Contenedor = Depends(get_contenedor)):
    await run_in_threadpool(c.vehiculos.eliminar, id_vehiculo)
    return Mensaje(mensaje="Vehículo eliminado")
