"""Contenedor de dependencias: crea una sola vez los objetos de la aplicación."""
from dataclasses import dataclass, field

from fastapi import Request, WebSocket

from config import Settings
from database import Database
from services.comando_service import ComandoService
from services.demo_runner import DemoRunner
from services.demo_service import DemoService
from services.estado_service import EstadoService
from services.historial_service import HistorialService
from services.movimiento_service import MovimientoService
from services.vehiculo_service import VehiculoService
from websocket import ConnectionManager
# --- práctica 4.3 ---
from services.auth_service import AuthService
from services.editor_demo_service import EditorDemoService
from services.invitado_service import InvitadoService, ParoSeguro, VigilanteInvitados
from services.plataforma_service import AuditoriaService, ControlExclusivo, LimiteSolicitudes, Plataforma
from websocket.autorizados import RegistroSockets


@dataclass
class Contenedor:
    db: Database
    manager: ConnectionManager
    vehiculos: VehiculoService
    comandos: ComandoService
    estados: EstadoService
    historial: HistorialService
    movimientos: MovimientoService
    demos: DemoService
    runner: DemoRunner
    # --- práctica 4.3 (administración, roles, invitados) ---
    plataforma: Plataforma = field(default=None)
    auditoria: AuditoriaService = field(default=None)
    auth: AuthService = field(default=None)
    invitados: InvitadoService = field(default=None)
    paro: ParoSeguro = field(default=None)
    vigilante: VigilanteInvitados = field(default=None)
    editor: EditorDemoService = field(default=None)
    control: ControlExclusivo = field(default=None)
    registro: RegistroSockets = field(default=None)
    limite_login: LimiteSolicitudes = field(default=None)
    limite_invitado: LimiteSolicitudes = field(default=None)

    @classmethod
    def crear(cls, settings: Settings) -> "Contenedor":
        db = Database(settings)
        manager = ConnectionManager()
        estados = EstadoService(db)
        movimientos = MovimientoService(db)
        runner = DemoRunner(db, manager, estados)
        plataforma = Plataforma(db)
        auditoria = AuditoriaService(plataforma)
        registro = RegistroSockets()
        paro = ParoSeguro(db, manager, runner, movimientos, estados)
        return cls(
            db=db,
            manager=manager,
            vehiculos=VehiculoService(db),
            comandos=ComandoService(db),
            estados=estados,
            historial=HistorialService(db),
            movimientos=movimientos,
            demos=DemoService(db),
            runner=runner,
            plataforma=plataforma,
            auditoria=auditoria,
            auth=AuthService(settings, plataforma, auditoria),
            invitados=InvitadoService(settings, db, plataforma),
            paro=paro,
            vigilante=VigilanteInvitados(plataforma, paro, registro, auditoria),
            editor=EditorDemoService(db, runner),
            control=ControlExclusivo(),
            registro=registro,
            limite_login=LimiteSolicitudes(maximo=10, ventana_s=60),
            limite_invitado=LimiteSolicitudes(maximo=6, ventana_s=60),
        )


def get_contenedor(request: Request) -> Contenedor:
    return request.app.state.contenedor


def get_contenedor_ws(websocket: WebSocket) -> Contenedor:
    return websocket.app.state.contenedor
