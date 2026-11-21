"""Práctica 4.3: editor de demos (FÁBRICA de la empresa y PRIVADAS del comprador).

Guardar = encabezado + pasos ordenados en UNA transacción. Cada paso se valida contra el catálogo de
comandos de ESA unidad (capacidades reales del hardware): no se puede usar un comando de otro modelo.
Los límites de duración se validan en el modelo Pydantic (models/plataforma.py).
"""
from database import Database
from exceptions import Conflicto, NoEncontrado
from fastapi import HTTPException
from models.plataforma import DemoEditor
from repositories import ComandoRepository, DemoRepository
from repositories.plataforma_repository import PlataformaRepository

from .demo_runner import DemoRunner


def puede_editar(demo: dict, tipo: str, id_usuario) -> bool:
    if tipo == "SERVICIO":
        return True
    if tipo == "ADMIN":
        return demo.get("tipo", "FABRICA") == "FABRICA"
    if tipo == "USUARIO":
        return demo.get("tipo") == "PRIVADA" and demo.get("id_propietario") == id_usuario
    return False


class EditorDemoService:
    def __init__(self, db: Database, runner: DemoRunner):
        self._db = db
        self._runner = runner

    def listar(self, id_vehiculo: int, tipo: str, id_usuario) -> list[dict]:
        with self._db.transaccion() as sp:
            filas = PlataformaRepository(sp).demos_usuario(id_vehiculo, id_usuario or 0)
        for d in filas:
            d["editable"] = puede_editar(d, tipo, id_usuario)
        return filas

    @staticmethod
    def _validar_pasos(sp, id_vehiculo: int, datos: DemoEditor) -> None:
        catalogo = {c["id_comando"]: c for c in ComandoRepository(sp).listar_por_vehiculo(id_vehiculo)}
        for i, paso in enumerate(datos.pasos, start=1):
            c = catalogo.get(paso.id_comando)
            if c is None:
                raise Conflicto(f"El paso {i} usa un comando que esta unidad no tiene")
            if not c["activo"]:
                raise Conflicto(f"El paso {i} usa el comando inactivo '{c['nombre']}'")

    @staticmethod
    def _escribir_pasos(sp, id_demo: int, datos: DemoEditor) -> None:
        repo = DemoRepository(sp)
        for orden, paso in enumerate(datos.pasos, start=1):
            repo.agregar_movimiento(id_demo, paso.id_comando, orden, paso.duracion_ms, paso.pausa_ms)

    def crear(self, id_vehiculo: int, tipo: str, id_usuario, datos: DemoEditor) -> int:
        """Usuario → demo PRIVADA propia; Admin/servicio → demo de FÁBRICA."""
        dueno = id_usuario if tipo == "USUARIO" else None
        with self._db.transaccion() as sp:
            self._validar_pasos(sp, id_vehiculo, datos)
            fila = PlataformaRepository(sp).crear_demo(id_vehiculo, dueno, datos.nombre, datos.descripcion)
            if fila.get("ban") != "0":
                raise HTTPException(status_code=403, detail="Solo puedes crear demos en tus propias unidades")
            id_demo = int(fila["id_demo"])
            if not datos.activo:
                DemoRepository(sp).actualizar(id_demo, datos.nombre, datos.descripcion, False)
            self._escribir_pasos(sp, id_demo, datos)
            return id_demo

    def _exigir_editable(self, sp, id_vehiculo: int, id_demo: int, tipo: str, id_usuario) -> dict:
        demo = next((d for d in DemoRepository(sp).listar_por_vehiculo(id_vehiculo) if d["id_demo"] == id_demo), None)
        if demo is None:
            raise NoEncontrado(f"La DEMO {id_demo} no existe para el vehículo {id_vehiculo}")
        if not puede_editar(demo, tipo, id_usuario):
            raise HTTPException(status_code=403, detail="No puedes modificar esta demo")
        if self._runner.en_ejecucion(id_vehiculo) == id_demo:
            raise Conflicto("La demo se está ejecutando; cancélala antes de modificarla")
        return demo

    def guardar(self, id_vehiculo: int, id_demo: int, tipo: str, id_usuario, datos: DemoEditor) -> None:
        with self._db.transaccion() as sp:
            self._exigir_editable(sp, id_vehiculo, id_demo, tipo, id_usuario)
            self._validar_pasos(sp, id_vehiculo, datos)
            DemoRepository(sp).actualizar(id_demo, datos.nombre, datos.descripcion, datos.activo)
            PlataformaRepository(sp).vaciar_pasos(id_demo)
            self._escribir_pasos(sp, id_demo, datos)

    def eliminar(self, id_vehiculo: int, id_demo: int, tipo: str, id_usuario) -> None:
        with self._db.transaccion() as sp:
            self._exigir_editable(sp, id_vehiculo, id_demo, tipo, id_usuario)
            DemoRepository(sp).eliminar(id_demo)
