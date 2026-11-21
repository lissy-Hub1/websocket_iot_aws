"""Práctica 4.3: modelos Pydantic de autenticación, administración, invitados y editor de demos."""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

Rol = Literal["ADMIN", "USUARIO"]
EstadoAlta = Literal["DISPONIBLE", "EXHIBICION"]
EstadoUnidad = Literal["DISPONIBLE", "EXHIBICION", "INACTIVO"]

# Límites seguros del editor de demos (también se validan en el servidor al ejecutar)
MAX_PASOS = 30
MAX_DURACION_PASO_MS = 5_000
MAX_PAUSA_MS = 5_000
MAX_DEMO_TOTAL_MS = 120_000


# ---------------------------------------------------------------- autenticación
class LoginGoogle(BaseModel):
    credential: str = Field(min_length=20, description="ID token que entrega Google Identity Services")


class UsuarioSesion(BaseModel):
    id_usuario: int
    email: str
    nombre: Optional[str] = None
    rol: Rol


class SesionRespuesta(BaseModel):
    token: str = Field(description="Token de sesión. Envíalo como `Authorization: Bearer <token>`")
    expira_en: datetime
    usuario: UsuarioSesion


class ConfigPublica(BaseModel):
    google_client_id: Optional[str] = None
    invitado_minutos: int


# ---------------------------------------------------------------- usuarios
class UsuarioCrear(BaseModel):
    email: str = Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", examples=["cliente@gmail.com"])
    nombre: Optional[str] = Field(default=None, max_length=120)
    rol: Rol = "USUARIO"

    @field_validator("email")
    @classmethod
    def minusculas(cls, v: str) -> str:
        return v.strip().lower()


class UsuarioActualizar(BaseModel):
    nombre: Optional[str] = Field(default=None, max_length=120)
    rol: Rol
    activo: bool = True


class Usuario(BaseModel):
    id_usuario: int
    email: str
    nombre: Optional[str] = None
    rol: Rol
    activo: bool
    ultimo_acceso: Optional[datetime] = None
    unidades: int = 0


# ---------------------------------------------------------------- modelos y unidades
class ModeloCrear(BaseModel):
    nombre: str = Field(min_length=1, max_length=80, examples=["Excavadora IoT"])
    descripcion: Optional[str] = Field(default=None, max_length=500)
    imagen_url: Optional[str] = Field(default=None, max_length=255, pattern=r"^(https://|assets/|\./).*")


class ModeloActualizar(ModeloCrear):
    activo: bool = True


class Modelo(BaseModel):
    id_modelo: int
    nombre: str
    descripcion: Optional[str] = None
    imagen_url: Optional[str] = None
    activo: bool
    unidades: int = 0


class UnidadCrear(BaseModel):
    id_modelo: int = Field(ge=1)
    numero_serie: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9._-]+$", examples=["UNI-0002"])
    nombre: str = Field(min_length=1, max_length=80)
    descripcion: Optional[str] = Field(default=None, max_length=255)
    microcontrolador: Optional[str] = Field(default=None, max_length=50, examples=["ESP32"])
    estado: EstadoAlta = "DISPONIBLE"


class UnidadActualizar(UnidadCrear):
    estado: EstadoUnidad = "DISPONIBLE"


class Unidad(BaseModel):
    id_vehiculo: int
    numero_serie: Optional[str] = None
    nombre: str
    id_modelo: Optional[int] = None
    modelo: Optional[str] = None
    estado: str
    microcontrolador: Optional[str] = None
    id_propietario: Optional[int] = None
    propietario_email: Optional[str] = None
    propietario_nombre: Optional[str] = None
    conectado: Optional[bool] = Field(default=None, description="Último valor registrado; no prueba presencia física")
    ultimo_estado: Optional[datetime] = None


class Asignacion(BaseModel):
    id_usuario: int = Field(ge=1)


class Revocacion(BaseModel):
    estado: EstadoUnidad = "DISPONIBLE"


class ComandoInvitado(BaseModel):
    permitido: bool


class Dashboard(BaseModel):
    modelos: int
    unidades: int
    unidades_asignadas: int
    unidades_disponibles: int
    unidades_exhibicion: int
    unidades_inactivas: int
    clientes: int
    demos: int
    invitados_activos: int


class RegistroAuditoria(BaseModel):
    id_auditoria: int
    fecha: datetime
    id_actor: Optional[int] = None
    actor_email: Optional[str] = None
    actor_rol: str
    accion: str
    recurso: str
    id_recurso: Optional[str] = None
    resultado: str
    detalle: Optional[dict] = None

    @field_validator("detalle", mode="before")
    @classmethod
    def json_de_mysql(cls, v):
        """MySQL entrega la columna JSON como texto."""
        if isinstance(v, (str, bytes)):
            import json
            return json.loads(v)
        return v


# ---------------------------------------------------------------- Mis vehículos y soporte
class MiVehiculo(BaseModel):
    id_vehiculo: int
    numero_serie: Optional[str] = None
    nombre: str
    modelo: Optional[str] = None
    imagen_url: Optional[str] = None
    conectado: Optional[bool] = None
    ultimo_estado: Optional[datetime] = None
    motivo: str = Field(default="PROPIETARIO", description="PROPIETARIO, EMPRESA (unidad no vendida) o SOPORTE")


class SoporteSolicitud(BaseModel):
    minutos: int = Field(default=30, ge=5, le=240)


# ---------------------------------------------------------------- invitados
class UnidadCatalogo(BaseModel):
    id_vehiculo: int
    numero_serie: Optional[str] = None
    libre: bool


class ModeloCatalogo(BaseModel):
    id_modelo: int
    nombre: str
    descripcion: Optional[str] = None
    imagen_url: Optional[str] = None
    unidades_exhibicion: list[UnidadCatalogo]


class InvitadoSolicitud(BaseModel):
    id_vehiculo: int = Field(ge=1)


class ComandoBasico(BaseModel):
    id_comando: int
    nombre: str
    codigo: int
    descripcion: Optional[str] = None


class InvitadoSesion(BaseModel):
    token: Optional[str] = Field(default=None, description="Solo se entrega al crear la sesión")
    id_vehiculo: int
    expira_en: datetime
    segundos_restantes: int
    comandos: list[ComandoBasico]


# ---------------------------------------------------------------- editor de demos
class PasoDemo(BaseModel):
    id_comando: int = Field(ge=1)
    duracion_ms: int = Field(ge=100, le=MAX_DURACION_PASO_MS)
    pausa_ms: int = Field(default=0, ge=0, le=MAX_PAUSA_MS)


class DemoEditor(BaseModel):
    nombre: str = Field(min_length=1, max_length=80)
    descripcion: Optional[str] = Field(default=None, max_length=255)
    activo: bool = True
    pasos: list[PasoDemo] = Field(min_length=1, max_length=MAX_PASOS)

    @field_validator("pasos")
    @classmethod
    def duracion_total(cls, pasos: list[PasoDemo]) -> list[PasoDemo]:
        total = sum(p.duracion_ms + p.pausa_ms for p in pasos)
        if total > MAX_DEMO_TOTAL_MS:
            raise ValueError(f"La demo dura {total} ms; el máximo es {MAX_DEMO_TOTAL_MS} ms")
        return pasos


class DemoResumen(BaseModel):
    id_demo: int
    id_vehiculo: int
    tipo: str
    id_propietario: Optional[int] = None
    nombre: str
    descripcion: Optional[str] = None
    activo: bool
    pasos: int
    duracion_total_ms: int
    editable: bool = False
