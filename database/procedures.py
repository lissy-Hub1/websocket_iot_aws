"""Ejecutor de Stored Procedures con parámetros enlazados (sin concatenar SQL)."""
from typing import Any

import pymysql.cursors

# Lista blanca: los 21 SP originales del esquema vehiculo_iot + los de la práctica 4.3.
PROCEDIMIENTOS_PERMITIDOS = frozenset(
    {
        "sp_crear_vehiculo", "sp_obtener_vehiculos", "sp_obtener_vehiculo",
        "sp_actualizar_vehiculo", "sp_eliminar_vehiculo",
        "sp_crear_comando", "sp_obtener_comandos_vehiculo",
        "sp_actualizar_comando", "sp_eliminar_comando",
        "sp_actualizar_estado", "sp_obtener_estado",
        "sp_registrar_historial", "sp_obtener_historial",
        "sp_crear_demo", "sp_obtener_demos", "sp_actualizar_demo", "sp_eliminar_demo",
        "sp_agregar_movimiento_demo", "sp_obtener_movimientos_demo",
        "sp_actualizar_movimiento_demo", "sp_eliminar_movimiento_demo",
        # --- práctica 4.3 (bd_vehiculo_iot_4_3.sql) ---
        "sp_acceso_google", "sp_ins_sesion", "sp_validar_sesion", "sp_cerrar_sesion",
        "sp_ins_usuario", "sp_upd_usuario", "sp_del_usuario", "sp_obtener_usuarios",
        "sp_ins_modelo", "sp_upd_modelo", "sp_obtener_modelos",
        "sp_ins_unidad", "sp_upd_unidad", "sp_obtener_unidades",
        "sp_asignar_unidad", "sp_revocar_unidad", "sp_mis_vehiculos", "sp_permiso_unidad",
        "sp_otorgar_soporte", "sp_revocar_soporte",
        "sp_catalogo_publico", "sp_iniciar_sesion_invitado", "sp_validar_sesion_invitado",
        "sp_terminar_sesion_invitado", "sp_comandos_invitado", "sp_vencer_invitados", "sp_upd_comando_invitado",
        "sp_obtener_demos_usuario", "sp_crear_demo_editor", "sp_vaciar_pasos_demo",
        "sp_ins_auditoria", "sp_obtener_auditoria", "sp_dashboard", "sp_salud",
    }
)


class StoredProcedures:
    """Envuelve una conexión abierta y expone `consultar` y `ejecutar`."""

    def __init__(self, conexion: pymysql.connections.Connection):
        self._conexion = conexion

    def _llamar(self, nombre: str, parametros: tuple[Any, ...]):
        if nombre not in PROCEDIMIENTOS_PERMITIDOS:
            raise ValueError(f"Procedimiento no permitido: {nombre}")
        marcadores = ", ".join(["%s"] * len(parametros))
        sql = f"CALL {nombre}({marcadores})"  # el nombre viene de la lista blanca
        cursor = self._conexion.cursor(pymysql.cursors.DictCursor)
        try:
            cursor.execute(sql, parametros)
            filas = list(cursor.fetchall())
            afectadas = cursor.rowcount
            while cursor.nextset():  # vacía los resultados restantes del CALL
                pass
            return filas, afectadas
        finally:
            cursor.close()

    def consultar(self, nombre: str, *parametros: Any) -> list[dict]:
        """SP que devuelve filas (SELECT)."""
        filas, _ = self._llamar(nombre, parametros)
        return filas

    def ejecutar(self, nombre: str, *parametros: Any) -> int:
        """SP que modifica datos. Devuelve las filas coincidentes (0 = no existía)."""
        _, afectadas = self._llamar(nombre, parametros)
        return afectadas
