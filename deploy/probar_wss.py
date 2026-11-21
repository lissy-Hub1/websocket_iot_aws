"""Cliente WSS de apoyo para las evidencias (alternativa/complemento a Thunder Client).

Uso:  python deploy/probar_wss.py wss://TU_DOMINIO/ws/vehiculos/1 [segundos]
Imprime cada mensaje con hora local. Abre dos terminales para simular dos clientes.
(`websockets` ya viene instalado con uvicorn[standard]).
"""
import asyncio
import sys
import time
from datetime import datetime

import websockets


async def main(url: str, segundos: float) -> None:
    async with websockets.connect(url) as ws:
        print(f"[{datetime.now():%H:%M:%S}] conectado a {url}")
        fin = time.monotonic() + segundos
        while (restante := fin - time.monotonic()) > 0:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=restante)
            except asyncio.TimeoutError:
                break
            print(f"[{datetime.now():%H:%M:%S}] {msg}")
    print("fin de la escucha")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    asyncio.run(main(sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 60))
