"""Práctica 4.3: registro de quién está conectado por WebSocket a cada unidad.

ConnectionManager (4.1/4.2) sigue repartiendo los eventos por vehículo; este registro solo recuerda la
identidad de cada socket para CERRARLO cuando esa identidad pierde el permiso (reasignación, baja,
logout, fin de la prueba de Invitado). Así no se filtran eventos de una unidad ajena.
"""
import logging
from dataclasses import dataclass
from typing import Optional

from fastapi import WebSocket

log = logging.getLogger("app_iot.ws")

CIERRE_SIN_PERMISO = 4403


@dataclass
class SocketAutorizado:
    ws: WebSocket
    id_vehiculo: int
    tipo: str
    id_usuario: Optional[int]
    token_hash: Optional[str]


class RegistroSockets:
    def __init__(self) -> None:
        self._sockets: dict[int, SocketAutorizado] = {}

    def agregar(self, s: SocketAutorizado) -> None:
        self._sockets[id(s.ws)] = s

    def quitar(self, ws: WebSocket) -> None:
        self._sockets.pop(id(ws), None)

    def hay_de_token(self, token_hash: str) -> bool:
        return any(s.token_hash == token_hash for s in self._sockets.values())

    async def _cerrar(self, elegir, motivo: str) -> int:
        cerrados = 0
        for s in [s for s in self._sockets.values() if elegir(s)]:
            try:
                await s.ws.close(code=CIERRE_SIN_PERMISO, reason=motivo[:120])
            except Exception:
                pass
            self.quitar(s.ws)
            cerrados += 1
        if cerrados:
            log.info("Se cerraron %s sockets: %s", cerrados, motivo)
        return cerrados

    async def cerrar_usuario_en_unidad(self, id_vehiculo: int, id_usuario: Optional[int], motivo: str) -> int:
        if id_usuario is None:
            return 0
        return await self._cerrar(lambda s: s.id_vehiculo == id_vehiculo and s.id_usuario == id_usuario, motivo)

    async def cerrar_usuario(self, id_usuario: int, motivo: str) -> int:
        return await self._cerrar(lambda s: s.id_usuario == id_usuario, motivo)

    async def cerrar_token(self, token_hash: str, motivo: str) -> int:
        return await self._cerrar(lambda s: s.token_hash == token_hash, motivo)

    async def cerrar_invitados_de_unidad(self, id_vehiculo: int, motivo: str) -> int:
        return await self._cerrar(lambda s: s.id_vehiculo == id_vehiculo and s.tipo == "INVITADO", motivo)

    async def cerrar_admins_de_unidad(self, id_vehiculo: int, motivo: str) -> int:
        return await self._cerrar(lambda s: s.id_vehiculo == id_vehiculo and s.tipo == "ADMIN", motivo)
