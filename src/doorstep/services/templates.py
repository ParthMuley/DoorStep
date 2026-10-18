"""Fixed resident-facing text. LLMs never generate safety wording.

English text is from master spec Section 8. The Spanish text is a careful
translation that MUST be reviewed by a fluent speaker before any demo
(tracked in docs/decisions.md). Every message starts with DOORSTEP DEMO and
says it is a simulation.
"""

from __future__ import annotations

TEMPLATES: dict[str, dict[str, str]] = {
    "checkin": {
        "en": ("DOORSTEP DEMO: A simulated warning affects your test area. Do you need "
               "transportation planning help? Reply 1 NEED HELP, 2 HAVE A PLAN, 3 ALREADY LEFT, "
               "4 CALL ME. This is a simulation, not an emergency alert."),
        "es": ("DOORSTEP DEMO: Una advertencia simulada afecta su área de prueba. ¿Necesita ayuda "
               "para planear su transporte? Responda 1 NECESITO AYUDA, 2 TENGO UN PLAN, 3 YA SALÍ, "
               "4 LLÁMENME. Esto es una simulación, no una alerta de emergencia."),
    },
    "confirm_needs": {
        "en": ("DOORSTEP DEMO: To confirm, you need: {summary}. Reply YES if correct or NO if not. "
               "This is a simulation."),
        "es": ("DOORSTEP DEMO: Para confirmar, usted necesita: {summary}. Responda SÍ si es correcto "
               "o NO si no lo es. Esto es una simulación."),
    },
    "needs_confirmed": {
        "en": ("DOORSTEP DEMO: Thank you. We are checking which partner services are available. "
               "No ride is confirmed yet. This is a simulation."),
        "es": ("DOORSTEP DEMO: Gracias. Estamos verificando qué servicios asociados están disponibles. "
               "Todavía no hay transporte confirmado. Esto es una simulación."),
    },
    "provider_accepted": {
        "en": ("DOORSTEP DEMO: A simulated partner provider ({provider}) has accepted your transport "
               "request. Pickup has not happened yet. This is a simulation."),
        "es": ("DOORSTEP DEMO: Un proveedor asociado simulado ({provider}) aceptó su solicitud de "
               "transporte. La recogida todavía no ha ocurrido. Esto es una simulación."),
    },
    "arrival_confirmed": {
        "en": ("DOORSTEP DEMO: Your simulated arrival at {destination} is recorded. Would you like us to "
               "share your accessibility needs with a recovery support organization to request help "
               "finding temporary accommodation? This is a simulation."),
        "es": ("DOORSTEP DEMO: Su llegada simulada a {destination} quedó registrada. ¿Desea que "
               "compartamos sus necesidades de accesibilidad con una organización de apoyo para "
               "solicitar ayuda con alojamiento temporal? Esto es una simulación."),
    },
    "help_on_the_way": {
        "en": ("DOORSTEP DEMO: A volunteer has accepted and is on the way (simulated). Estimated arrival about "
               "{eta} minutes. This is an estimate, not a guarantee. This is a simulation."),
        "es": ("DOORSTEP DEMO: Un voluntario aceptó y va en camino (simulado). Llegada estimada en unos {eta} "
               "minutos. Es una estimación, no una garantía. Esto es una simulación."),
    },
    "recovery_requested": {
        "en": ("DOORSTEP DEMO: We asked {org} about {help}. Only the details you agreed to share were sent. "
               "Nothing is confirmed yet. This is a simulation."),
        "es": ("DOORSTEP DEMO: Pedimos ayuda a {org} con {help}. Solo enviamos los datos que usted aceptó compartir. "
               "Todavía no hay nada confirmado. Esto es una simulación."),
    },
    "recovery_accepted": {
        "en": ("DOORSTEP DEMO: {org} accepted your request for help with {help}. This is not a confirmed "
               "reservation or service yet. This is a simulation."),
        "es": ("DOORSTEP DEMO: {org} aceptó su solicitud de ayuda con {help}. Todavía no es una reservación "
               "ni un servicio confirmado. Esto es una simulación."),
    },
    "recovery_completed": {
        "en": "DOORSTEP DEMO: {org} confirmed help with {help} (simulated reference {ref}). This is a simulation.",
        "es": "DOORSTEP DEMO: {org} confirmó la ayuda con {help} (referencia simulada {ref}). Esto es una simulación.",
    },
    "volunteer_outreach": {
        "en": ("DOORSTEP DEMO: A simulated {calamity} alert affects {zone}. {org} is asking: can you help "
               "with accessible transport? Reply YES or NO. This is a simulation."),
        "es": ("DOORSTEP DEMO: Una alerta simulada de {calamity} afecta {zone}. {org} pregunta: ¿puede ayudar "
               "con transporte accesible? Responda SÍ o NO. Esto es una simulación."),
    },
    "coordinator_followup": {
        "en": ("DOORSTEP DEMO: Assistance is NOT confirmed yet. Your request was passed to a coordinator "
               "for follow-up. For emergencies call 911. This is a simulation."),
        "es": ("DOORSTEP DEMO: La asistencia todavía NO está confirmada. Su solicitud pasó a un "
               "coordinador para seguimiento. En emergencias llame al 911. Esto es una simulación."),
    },
}

NEED_LABELS = {
    "wheelchair_accessible_vehicle": {"en": "wheelchair-accessible vehicle", "es": "vehículo accesible para silla de ruedas"},
    "transfer_assistance": {"en": "help getting into the vehicle", "es": "ayuda para subir al vehículo"},
    "portable_oxygen_equipment": {"en": "space for oxygen equipment", "es": "espacio para equipo de oxígeno"},
    "pet": {"en": "space for {n} pet(s)", "es": "espacio para {n} mascota(s)"},
    "service_animal": {"en": "a service animal", "es": "un animal de servicio"},
}


def render(template_id: str, language: str, **kwargs: str) -> str:
    lang = language if language in ("en", "es") else "en"
    text = TEMPLATES[template_id][lang].format(**kwargs)
    assert text.startswith("DOORSTEP DEMO"), "every resident message must be DEMO-labeled"
    return text


def summarize_needs(needs: dict, language: str) -> str:
    lang = language if language in ("en", "es") else "en"
    parts = []
    for key in ("wheelchair_accessible_vehicle", "transfer_assistance", "portable_oxygen_equipment",
                "service_animal"):
        if needs.get(key):
            parts.append(NEED_LABELS[key][lang])
    if needs.get("pet_count"):
        parts.append(NEED_LABELS["pet"][lang].format(n=needs["pet_count"]))
    if not parts:
        return "transportation help" if lang == "en" else "ayuda con transporte"
    return ", ".join(parts)
