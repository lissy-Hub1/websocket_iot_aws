"""Práctica 4.3: inicio de sesión con Google y sesiones del servidor.

1. El navegador obtiene un ID token con Google Identity Services (botón oficial).
2. Aquí se VERIFICA en el servidor: firma de Google, audiencia (= GOOGLE_CLIENT_ID), emisor y correo verificado.
3. El correo debe existir en `usuarios` (alta hecha por un Admin) o estar en ADMIN_EMAILS (.env).
4. Se entrega un token opaco aleatorio; en RDS solo se guarda su SHA-256.
"""
import secrets
from typing import Callable, Optional

from fastapi import HTTPException

from config import Settings
from exceptions import ServicioNoDisponible

from .plataforma_service import AuditoriaService, Plataforma, hash_token

EMISORES_GOOGLE = {"accounts.google.com", "https://accounts.google.com"}

MENSAJES_ACCESO = {
    "0": "Tu cuenta de Google no está registrada. Pide al administrador que te dé de alta.",
    "2": "Ese correo ya está vinculado a otra cuenta de Google.",
    "3": "Tu cuenta está dada de baja.",
}


class AuthService:
    def __init__(self, settings: Settings, plataforma: Plataforma, auditoria: AuditoriaService,
                 verificador: Optional[Callable[[str], dict]] = None):
        self._s = settings
        self._p = plataforma
        self._auditoria = auditoria
        # Se puede reemplazar en pruebas automáticas; en producción verifica contra Google.
        self.verificador = verificador or self._verificar_con_google
        self._transporte = None

    def _verificar_con_google(self, credential: str) -> dict:
        if not self._s.google_client_id:
            raise ServicioNoDisponible("El inicio de sesión con Google no está configurado (falta GOOGLE_CLIENT_ID)")
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token

        if self._transporte is None:
            self._transporte = google_requests.Request()
        try:
            claims = id_token.verify_oauth2_token(credential, self._transporte, self._s.google_client_id)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail="El token de Google no es válido o ya venció") from exc
        if claims.get("iss") not in EMISORES_GOOGLE:
            raise HTTPException(status_code=401, detail="El token no lo emitió Google")
        return claims

    def login(self, credential: str) -> dict:
        claims = self.verificador(credential)
        email = (claims.get("email") or "").strip().lower()
        if not email or not claims.get("email_verified"):
            raise HTTPException(status_code=403, detail="Tu correo de Google no está verificado")
        es_admin = email in self._s.admin_emails
        fila = self._p.acceso_google(email, str(claims["sub"]), claims.get("name"), es_admin)
        estatus = fila.get("estatus")
        if estatus != "1":
            self._auditoria.registrar(None, "LOGIN", "usuario", None, "RECHAZADO", {"motivo": estatus})
            raise HTTPException(status_code=403, detail=MENSAJES_ACCESO.get(estatus, "Acceso denegado"))

        token = secrets.token_urlsafe(32)
        sesion = self._p.crear_sesion(fila["id_usuario"], hash_token(token), self._s.sesion_minutos)
        usuario = {k: fila[k] for k in ("id_usuario", "email", "nombre", "rol")}
        self._auditoria.registrar_actor(fila["id_usuario"], fila["rol"], "LOGIN", "usuario", fila["id_usuario"], "OK")
        return {"token": token, "expira_en": sesion["expira_en"], "usuario": usuario}

    def logout(self, token_hash: str) -> None:
        self._p.cerrar_sesion(token_hash)
