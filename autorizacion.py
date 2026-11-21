"""Práctica 4.3: identidad y autorización (RBAC + permiso sobre la unidad).

Quién hace la petición se decide SOLO en el servidor, a partir de:
  * `Authorization: Bearer <token>`: sesión de Admin/Usuario (login con Google) o de Invitado (`inv_…`).
  * `X-API-Key`: acceso técnico de servicio (Swagger, Thunder Client, scripts). Igual que en 4.1/4.2.
El navegador nunca envía rol, id_usuario ni propietario: todo se consulta en RDS.
"""
import hmac
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from fastapi import Depends, HTTPException, Security
from fastapi.concurrency import run_in_threadpool
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from config import Settings, get_settings
from dependencies import Contenedor, get_contenedor
from services.plataforma_service import hash_token

PREFIJO_INVITADO = "inv_"
SERVICIO, ADMIN, USUARIO, INVITADO = "SERVICIO", "ADMIN", "USUARIO", "INVITADO"


@dataclass(frozen=True)
class Identidad:
    tipo: str                              # SERVICIO | ADMIN | USUARIO | INVITADO
    id_usuario: Optional[int] = None
    email: Optional[str] = None
    nombre: Optional[str] = None
    id_vehiculo: Optional[int] = None      # Invitado: unidad reservada
    token_hash: Optional[str] = None
    expira_en: Optional[datetime] = None

    @property
    def rol_auditoria(self) -> str:
        return "SISTEMA" if self.tipo == SERVICIO else self.tipo

    @property
    def clave_control(self) -> str:
        """Identifica a quien opera una unidad (para el control exclusivo)."""
        return self.token_hash or f"{self.tipo}:{self.id_usuario}"


def resolver_token(c: Contenedor, token: str) -> Optional[Identidad]:
    """Valida un token de sesión o de invitado contra RDS. Bloqueante: llamar fuera del event loop."""
    h = hash_token(token)
    if token.startswith(PREFIJO_INVITADO):
        fila = c.plataforma.validar_invitado(h)
        if fila.get("estatus") != "1":
            return None
        return Identidad(INVITADO, id_vehiculo=int(fila["id_vehiculo"]), token_hash=h, expira_en=fila["expira_en"])
    fila = c.plataforma.validar_sesion(h)
    if fila.get("estatus") != "1":
        return None
    return Identidad(
        fila["rol"], id_usuario=int(fila["id_usuario"]), email=fila["email"], nombre=fila.get("nombre"),
        token_hash=h, expira_en=fila["expira_en"],
    )


def es_api_key_valida(clave: Optional[str], settings: Settings) -> bool:
    return bool(clave) and hmac.compare_digest(clave, settings.api_key)


_bearer = HTTPBearer(auto_error=False, description="Token de sesión (login con Google) o de Invitado")
_api_key = APIKeyHeader(name="X-API-Key", auto_error=False, description="Acceso técnico de servicio (ver .env)")


async def identidad_opcional(
    credenciales: Optional[HTTPAuthorizationCredentials] = Security(_bearer),
    clave: Optional[str] = Security(_api_key),
    settings: Settings = Depends(get_settings),
    c: Contenedor = Depends(get_contenedor),
) -> Optional[Identidad]:
    if clave is not None:
        if not es_api_key_valida(clave, settings):
            raise HTTPException(status_code=403, detail="API key inválida")
        return Identidad(SERVICIO)
    if credenciales is not None:
        identidad = await run_in_threadpool(resolver_token, c, credenciales.credentials)
        if identidad is None:
            raise HTTPException(status_code=401, detail="La sesión venció o no es válida. Vuelve a iniciar sesión.")
        return identidad
    return None


async def identidad(ident: Optional[Identidad] = Depends(identidad_opcional)) -> Identidad:
    if ident is None:
        raise HTTPException(status_code=401, detail="Inicia sesión para continuar")
    return ident


def exigir_tipos(*tipos: str) -> Callable:
    async def dependencia(ident: Identidad = Depends(identidad)) -> Identidad:
        if ident.tipo not in tipos:
            raise HTTPException(status_code=403, detail="Tu cuenta no tiene permiso para esta operación")
        return ident
    return dependencia


exigir_admin = exigir_tipos(ADMIN, SERVICIO)
exigir_cuenta = exigir_tipos(ADMIN, USUARIO, SERVICIO)


async def comprobar_unidad(c: Contenedor, ident: Identidad, id_vehiculo: int, accion: str) -> None:
    """Autorización por RECURSO: no basta el rol, también la unidad concreta."""
    if ident.tipo == SERVICIO:
        return
    if ident.tipo == INVITADO:
        if ident.id_vehiculo != id_vehiculo:
            await c.auditoria.registrar_async(ident, "ACCESO_UNIDAD", "vehiculo", id_vehiculo, "RECHAZADO", {"accion": accion})
            raise HTTPException(status_code=403, detail="Tu prueba de Invitado solo permite la unidad reservada")
        return
    fila = await run_in_threadpool(c.plataforma.permiso_unidad, ident.id_usuario, id_vehiculo)
    estatus = fila.get("estatus")
    if estatus == "2":
        raise HTTPException(status_code=404, detail=f"El vehículo {id_vehiculo} no existe")
    if estatus != "1":
        await c.auditoria.registrar_async(ident, "ACCESO_UNIDAD", "vehiculo", id_vehiculo, "RECHAZADO", {"accion": accion})
        raise HTTPException(status_code=403, detail="No tienes permiso sobre esta unidad")


def permiso_unidad(accion: str) -> Callable:
    """Dependencia para rutas con `{id_vehiculo}`: accion = 'ver' | 'operar'."""
    async def dependencia(
        id_vehiculo: int, ident: Identidad = Depends(identidad), c: Contenedor = Depends(get_contenedor)
    ) -> Identidad:
        await comprobar_unidad(c, ident, id_vehiculo, accion)
        return ident
    return dependencia


def demo_visible(demo: dict, ident: Identidad) -> bool:
    """Las demos de FÁBRICA las ve quien puede ver la unidad; las PRIVADAS solo su dueño (y el servicio)."""
    if ident.tipo == SERVICIO:
        return True
    if ident.tipo == INVITADO:
        return False
    return demo.get("tipo", "FABRICA") != "PRIVADA" or demo.get("id_propietario") == ident.id_usuario
