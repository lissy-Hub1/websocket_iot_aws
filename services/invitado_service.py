"""Práctica 4.3: catálogo público, prueba temporal del Invitado y paro seguro.

* La reserva exclusiva la garantiza RDS (índice UNIQUE sobre la sesión activa de cada unidad).
* El Invitado solo puede usar los comandos marcados `permitido_invitado` de SU unidad.
* Al vencer, cancelar o desconectarse, la unidad recibe DETENER (`ParoSeguro`).
"""
import asyncio
import logging
import secrets
from typing import Optional

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool

from config import Settings
from database import Database
from exceptions import ErrorDeNegocio, NoEncontrado
from models.eventos import EventoWS, TipoEvento
from models.historial import MovimientoSolicitud
from repositories import ComandoRepository
from websocket import ConnectionManager

from .demo_runner import DemoRunner
from .estado_service import EstadoService
from .movimiento_service import MovimientoService
from .plataforma_service import Plataforma, hash_token

log = logging.getLogger("app_iot.invitado")
PREFIJO_INVITADO = "inv_"


def comando_de_solicitud(comandos: list[dict], solicitud: MovimientoSolicitud) -> Optional[dict]:
    for c in comandos:
        if (solicitud.id_comando is not None and c["id_comando"] == solicitud.id_comando) or (
            solicitud.codigo is not None and c["codigo"] == solicitud.codigo
        ):
            return c
    return None


class InvitadoService:
    def __init__(self, settings: Settings, db: Database, plataforma: Plataforma):
        self._s = settings
        self._db = db
        self._p = plataforma

    def catalogo(self) -> list[dict]:
        modelos: dict[int, dict] = {}
        for fila in self._p.catalogo():
            m = modelos.setdefault(fila["id_modelo"], {
                "id_modelo": fila["id_modelo"], "nombre": fila["nombre"], "descripcion": fila["descripcion"],
                "imagen_url": fila["imagen_url"], "unidades_exhibicion": [],
            })
            if fila["id_vehiculo"] is not None:
                m["unidades_exhibicion"].append(
                    {"id_vehiculo": fila["id_vehiculo"], "numero_serie": fila["numero_serie"], "libre": bool(fila["libre"])}
                )
        return list(modelos.values())

    def iniciar(self, id_vehiculo: int) -> dict:
        token = PREFIJO_INVITADO + secrets.token_urlsafe(32)
        fila = self._p.iniciar_invitado(id_vehiculo, hash_token(token), self._s.invitado_minutos)
        ban = fila.get("ban")
        if ban == "1":
            raise HTTPException(status_code=409, detail="Esa unidad no está disponible para pruebas de exhibición")
        if ban == "2":
            raise HTTPException(status_code=409, detail="La unidad está ocupada por otro invitado. Intenta en unos minutos.")
        return {
            "token": token, "id_vehiculo": id_vehiculo, "expira_en": fila["expira_en"],
            "segundos_restantes": self._s.invitado_minutos * 60, "comandos": self.comandos(id_vehiculo),
        }

    def estado(self, token_hash: str) -> dict:
        fila = self._p.validar_invitado(token_hash)
        if fila.get("estatus") != "1":
            raise HTTPException(status_code=401, detail="Tu prueba terminó")
        return {
            "id_vehiculo": fila["id_vehiculo"], "expira_en": fila["expira_en"],
            "segundos_restantes": max(0, int(fila["segundos_restantes"])), "comandos": self.comandos(fila["id_vehiculo"]),
        }

    def comandos(self, id_vehiculo: int) -> list[dict]:
        return self._p.comandos_invitado(id_vehiculo)

    def terminar(self, token_hash: str, motivo: str) -> bool:
        return self._p.terminar_invitado(token_hash, motivo).get("ban") == "0"

    def catalogo_unidad(self, id_vehiculo: int) -> list[dict]:
        with self._db.transaccion() as sp:
            return ComandoRepository(sp).listar_por_vehiculo(id_vehiculo)


class ParoSeguro:
    """Detiene una unidad: cancela su DEMO si hay una; si no, registra DETENER como movimiento
    individual (queda en el historial con el origen indicado y se notifica por WebSocket)."""

    def __init__(self, db: Database, manager: ConnectionManager, runner: DemoRunner,
                 movimientos: MovimientoService, estados: EstadoService):
        self._db = db
        self._manager = manager
        self._runner = runner
        self._movimientos = movimientos
        self._estados = estados

    def _id_detener(self, id_vehiculo: int) -> Optional[int]:
        with self._db.transaccion() as sp:
            for c in ComandoRepository(sp).listar_por_vehiculo(id_vehiculo):
                if c["nombre"].upper() == "DETENER" and c["activo"]:
                    return c["id_comando"]
        return None

    async def detener(self, id_vehiculo: int, origen: str) -> None:
        try:
            if self._runner.en_ejecucion(id_vehiculo) is not None:
                await self._runner.cancelar(id_vehiculo)  # el runner hace su propio paro seguro
                return
        except NoEncontrado:
            pass
        try:
            id_detener = await run_in_threadpool(self._id_detener, id_vehiculo)
            if id_detener is None:
                return
            try:
                r = await run_in_threadpool(
                    self._movimientos.registrar, id_vehiculo, MovimientoSolicitud(id_comando=id_detener, origen=origen)
                )
            except ErrorDeNegocio:  # p. ej. unidad dada de baja: solo se fija el estado
                await run_in_threadpool(self._estados.fijar_comando, id_vehiculo, id_detener)
                return
            await self._manager.difundir(id_vehiculo, EventoWS(
                tipo=TipoEvento.MOVIMIENTO, id_vehiculo=id_vehiculo, comando=r["comando"], codigo=r["codigo"],
                id_comando=r["id_comando"], origen=r["origen"], conectado=r["conectado"], timestamp=r["fecha_hora"],
            ))
        except Exception:
            log.exception("No se pudo ejecutar el paro seguro de la unidad %s", id_vehiculo)


class VigilanteInvitados:
    """Tarea de fondo: cada pocos segundos cierra las pruebas vencidas, avisa y detiene la unidad."""

    def __init__(self, plataforma: Plataforma, paro: ParoSeguro, registro, auditoria, intervalo_s: float = 3.0):
        self._p = plataforma
        self._paro = paro
        self._registro = registro
        self._auditoria = auditoria
        self._intervalo = intervalo_s
        self._tarea: Optional[asyncio.Task] = None

    async def revisar(self) -> int:
        vencidas = await run_in_threadpool(self._p.vencer_invitados)
        for v in vencidas:
            await self._registro.cerrar_token(v["token_hash"], "La prueba de invitado terminó")
            await self._paro.detener(v["id_vehiculo"], "FIN_INVITADO")
            await run_in_threadpool(
                self._auditoria.registrar_actor, None, "SISTEMA", "INVITADO_EXPIRA", "sesion_invitado",
                v["id_sesion_invitado"], "OK", {"id_vehiculo": v["id_vehiculo"]},
            )
        return len(vencidas)

    async def _bucle(self) -> None:
        while True:
            try:
                await self.revisar()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Falla al revisar sesiones de invitado vencidas")
            await asyncio.sleep(self._intervalo)

    def iniciar(self) -> None:
        if self._tarea is None:
            self._tarea = asyncio.create_task(self._bucle())

    async def cerrar(self) -> None:
        if self._tarea:
            self._tarea.cancel()
            await asyncio.gather(self._tarea, return_exceptions=True)
