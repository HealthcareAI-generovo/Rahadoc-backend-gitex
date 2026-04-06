"""Prompts module."""
from app.prompts.scribe import MEDSCRIBE_SYSTEM_PROMPT, build_medscribe_prompt
from app.prompts.diagnostic import DIAGNOSTIC_SYSTEM_PROMPT, build_diagnostic_prompt
from app.prompts.rx_guard import RX_GUARD_SYSTEM_PROMPT, build_rx_guard_prompt
from app.prompts.patient_360 import PATIENT_360_SYSTEM_PROMPT, build_patient_360_prompt

__all__ = [
    "MEDSCRIBE_SYSTEM_PROMPT",
    "build_medscribe_prompt",
    "DIAGNOSTIC_SYSTEM_PROMPT",
    "build_diagnostic_prompt",
    "RX_GUARD_SYSTEM_PROMPT",
    "build_rx_guard_prompt",
    "PATIENT_360_SYSTEM_PROMPT",
    "build_patient_360_prompt",
]
