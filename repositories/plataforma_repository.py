"""Práctica 4.3: acceso a los Stored Procedures de bd_vehiculo_iot_4_3.sql (usuarios, sesiones, modelos,
unidades, asignaciones, invitados, soporte, demos del editor, auditoría y dashboard).
Solo llama SP; las reglas viven en los servicios."""
import json
from typing import Any, Optional

from database import StoredProcedures


def primera(filas: list[dict]) -> dict:
    return filas[0] if filas else {}


class PlataformaRepository:
    def __init__(self, sp: StoredProcedures):
        self._sp = sp

    def _una(self, nombre: str, *args: Any) -> dict:
        return primera(self._sp.consultar(nombre, *args))

    # ---- acceso y sesiones ----
    def acceso_google(self, email, google_sub, nombre, es_admin) -> dict:
        return self._una("sp_acceso_google", email, google_sub, nombre, es_admin)

    def crear_sesion(self, id_usuario, token_hash, minutos) -> dict:
        return self._una("sp_ins_sesion", id_usuario, token_hash, minutos)

    def validar_sesion(self, token_hash) -> dict:
        return self._una("sp_validar_sesion", token_hash)

    def cerrar_sesion(self, token_hash) -> dict:
        return self._una("sp_cerrar_sesion", token_hash)

    # ---- usuarios ----
    def crear_usuario(self, email, nombre, rol, creado_por) -> dict:
        return self._una("sp_ins_usuario", email, nombre, rol, creado_por)

    def actualizar_usuario(self, id_usuario, nombre, rol, activo) -> dict:
        return self._una("sp_upd_usuario", id_usuario, nombre, rol, activo)

    def eliminar_usuario(self, id_usuario) -> dict:
        return self._una("sp_del_usuario", id_usuario)

    def usuarios(self) -> list[dict]:
        return self._sp.consultar("sp_obtener_usuarios")

    # ---- modelos y unidades ----
    def crear_modelo(self, nombre, descripcion, imagen_url) -> dict:
        return self._una("sp_ins_modelo", nombre, descripcion, imagen_url)

    def actualizar_modelo(self, id_modelo, nombre, descripcion, imagen_url, activo) -> dict:
        return self._una("sp_upd_modelo", id_modelo, nombre, descripcion, imagen_url, activo)

    def modelos(self) -> list[dict]:
        return self._sp.consultar("sp_obtener_modelos")

    def crear_unidad(self, id_modelo, numero_serie, nombre, descripcion, microcontrolador, estado) -> dict:
        return self._una("sp_ins_unidad", id_modelo, numero_serie, nombre, descripcion, microcontrolador, estado)

    def actualizar_unidad(self, id_vehiculo, id_modelo, numero_serie, nombre, descripcion, microcontrolador, estado) -> dict:
        return self._una(
            "sp_upd_unidad", id_vehiculo, id_modelo, numero_serie, nombre, descripcion, microcontrolador, estado
        )

    def unidades(self) -> list[dict]:
        return self._sp.consultar("sp_obtener_unidades")

    def asignar(self, id_vehiculo, id_usuario, actor) -> dict:
        return self._una("sp_asignar_unidad", id_vehiculo, id_usuario, actor)

    def revocar(self, id_vehiculo, actor, estado_nuevo) -> dict:
        return self._una("sp_revocar_unidad", id_vehiculo, actor, estado_nuevo)

    def mis_vehiculos(self, id_usuario) -> list[dict]:
        return self._sp.consultar("sp_mis_vehiculos", id_usuario)

    def permiso_unidad(self, id_usuario, id_vehiculo) -> dict:
        return self._una("sp_permiso_unidad", id_usuario, id_vehiculo)

    def otorgar_soporte(self, id_vehiculo, id_usuario, minutos) -> dict:
        return self._una("sp_otorgar_soporte", id_vehiculo, id_usuario, minutos)

    def revocar_soporte(self, id_vehiculo, id_usuario) -> dict:
        return self._una("sp_revocar_soporte", id_vehiculo, id_usuario)

    def comando_invitado(self, id_vehiculo, id_comando, permitido) -> dict:
        return self._una("sp_upd_comando_invitado", id_vehiculo, id_comando, permitido)

    # ---- invitados ----
    def catalogo(self) -> list[dict]:
        return self._sp.consultar("sp_catalogo_publico")

    def iniciar_invitado(self, id_vehiculo, token_hash, minutos) -> dict:
        return self._una("sp_iniciar_sesion_invitado", id_vehiculo, token_hash, minutos)

    def validar_invitado(self, token_hash) -> dict:
        return self._una("sp_validar_sesion_invitado", token_hash)

    def terminar_invitado(self, token_hash, motivo) -> dict:
        return self._una("sp_terminar_sesion_invitado", token_hash, motivo)

    def comandos_invitado(self, id_vehiculo) -> list[dict]:
        return self._sp.consultar("sp_comandos_invitado", id_vehiculo)

    def vencer_invitados(self) -> list[dict]:
        return self._sp.consultar("sp_vencer_invitados")

    # ---- demos del editor ----
    def demos_usuario(self, id_vehiculo, id_usuario) -> list[dict]:
        return self._sp.consultar("sp_obtener_demos_usuario", id_vehiculo, id_usuario)

    def crear_demo(self, id_vehiculo, id_usuario, nombre, descripcion) -> dict:
        return self._una("sp_crear_demo_editor", id_vehiculo, id_usuario, nombre, descripcion)

    def vaciar_pasos(self, id_demo) -> dict:
        return self._una("sp_vaciar_pasos_demo", id_demo)

    # ---- auditoría, dashboard y salud ----
    def auditar(self, id_actor, actor_rol, accion, recurso, id_recurso, resultado, detalle: Optional[dict]) -> None:
        self._sp.ejecutar(
            "sp_ins_auditoria", id_actor, actor_rol, accion, recurso,
            None if id_recurso is None else str(id_recurso), resultado,
            None if detalle is None else json.dumps(detalle, ensure_ascii=False, default=str),
        )

    def auditoria(self, limite, desde) -> list[dict]:
        return self._sp.consultar("sp_obtener_auditoria", limite, desde)

    def dashboard(self) -> dict:
        return self._una("sp_dashboard")

    def salud(self) -> dict:
        return self._una("sp_salud")
