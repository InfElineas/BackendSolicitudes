# app/models/common.py
from typing import Literal

RequestType = Literal["Soporte","Mejora","Desarrollo","Capacitación"]
RequestChannel = Literal["WhatsApp","Correo","Sistema"]
RequestStatus = Literal["Pendiente","En progreso","En revisión","Finalizada","Rechazada"]

OPEN_STATES = ["Pendiente","En progreso","En revisión"]

ALLOWED_TRANSITIONS = {
  "Pendiente": {"En progreso","Rechazada"},
  "En progreso": {"En revisión"},
  "En revisión": {"Finalizada","En progreso"},
  "Finalizada": set(),
  "Rechazada": set(),
}
