# Spanish review sheet

> DOORSTEP DEMO: every message below is for a **simulation** with synthetic people. Nothing is sent to real residents.

**For the reviewer.** Doorstep texts residents (and, in future, volunteers) during a simulated evacuation. These are the exact Spanish messages, next to the English originals. Please check that each one:
1. means the same as the English;
2. sounds natural to a Spanish speaker in Los Angeles (plain, respectful, formal *usted*);
3. never sounds like a promise that someone is safe, that help is guaranteed, or that emergency services were sent.

For each row, mark **OK** or write your suggested wording in the last column. Words in `{braces}` are filled in automatically (a name, a number, a place): keep them exactly as they are. "DOORSTEP DEMO" stays in English.

Source: `src/doorstep/services/templates.py`, `src/doorstep/services/recovery_v2.py`, `src/doorstep/services/intake.py`. Last updated 2026-10-18 (wording pass by Developer B with Claude). **Reviewed 2026-10-18: all rows OK.**

## 1. Messages to residents

| # | When it's sent | English | Spanish | OK / suggestion |
|---|---|---|---|---|
| 1 | First check-in when a simulated warning starts | A simulated warning affects your test area. Do you need transportation planning help? Reply 1 NEED HELP, 2 HAVE A PLAN, 3 ALREADY LEFT, 4 CALL ME. This is a simulation, not an emergency alert. | Un aviso simulado afecta su zona de prueba. ¿Necesita ayuda para planear su transporte? Responda 1 NECESITO AYUDA, 2 TENGO UN PLAN, 3 YA SALÍ, 4 LLÁMENME. Esto es una simulación, no una alerta de emergencia. | |
| 2 | Repeating back the needs we understood | To confirm, you need: {summary}. Reply YES if correct or NO if not. This is a simulation. | Queremos confirmar que usted necesita: {summary}. Responda SÍ si es correcto o NO si no lo es. Esto es una simulación. | |
| 3 | After the resident confirms | Thank you. We are checking which partner services are available. No ride is confirmed yet. This is a simulation. | Gracias. Estamos verificando qué organizaciones colaboradoras pueden ayudar. Todavía no hay transporte confirmado. Esto es una simulación. | |
| 4 | An organization accepted (older flow) | A simulated partner provider ({provider}) has accepted your transport request. Pickup has not happened yet. This is a simulation. | Una organización colaboradora simulada ({provider}) aceptó su solicitud de transporte. Todavía no se ha realizado la recogida. Esto es una simulación. | |
| 5 | A volunteer accepted (main flow) | A volunteer has accepted and is on the way (simulated). Estimated arrival about {eta} minutes. This is an estimate, not a guarantee. This is a simulation. | Una persona voluntaria aceptó y va en camino (simulado). Llegada estimada: unos {eta} minutos. Es una estimación, no una garantía. Esto es una simulación. | |
| 6 | Arrival at the shelter recorded | Your simulated arrival at {destination} is recorded. Would you like us to share your accessibility needs with a recovery support organization to request help finding temporary accommodation? This is a simulation. | Su llegada simulada a {destination} quedó registrada. ¿Desea que compartamos sus necesidades de accesibilidad con una organización de apoyo para la recuperación, para solicitar ayuda con alojamiento temporal? Esto es una simulación. | |
| 7 | Recovery help requested | We asked {org} about {help}. Only the details you agreed to share were sent. Nothing is confirmed yet. This is a simulation. | Pedimos ayuda a {org} con {help}. Solo enviamos los datos que usted aceptó compartir. Todavía no hay nada confirmado. Esto es una simulación. | |
| 8 | Recovery organization accepted | {org} accepted your request for help with {help}. This is not a confirmed reservation or service yet. This is a simulation. | {org} aceptó su solicitud de ayuda con {help}. Todavía no es una reservación ni un servicio confirmado. Esto es una simulación. | |
| 9 | Recovery help completed | {org} confirmed help with {help} (simulated reference {ref}). This is a simulation. | {org} confirmó la ayuda con {help} (referencia simulada {ref}). Esto es una simulación. | |
| 10 | Help could not be confirmed; a coordinator takes over | Assistance is NOT confirmed yet. Your request was passed to a coordinator for follow-up. For emergencies call 911. This is a simulation. | La asistencia todavía NO está confirmada. Su solicitud se envió a un coordinador para darle seguimiento. En caso de emergencia, llame al 911. Esto es una simulación. | |

## 2. Message to volunteers (currently always sent in English)

| # | English | Spanish | OK / suggestion |
|---|---|---|---|
| 11 | A simulated {calamity} alert affects {zone}. {org} is asking: can you help with accessible transport? Reply YES or NO. This is a simulation. | Una alerta simulada de {calamity} afecta {zone}. {org} pregunta: ¿puede ayudar con transporte accesible? Responda SÍ o NO. Esto es una simulación. | |

## 3. Short phrases filled into the messages

| Used in | English | Spanish | OK / suggestion |
|---|---|---|---|
| {summary} in #2 | wheelchair-accessible vehicle | vehículo accesible para silla de ruedas | |
| {summary} | help getting into the vehicle | ayuda para subir al vehículo | |
| {summary} | space for oxygen equipment | espacio para equipo de oxígeno | |
| {summary} | space for {n} pet(s) | espacio para {n} mascota(s) | |
| {summary} | a service animal | un animal de servicio | |
| {summary} (no specific needs) | transportation help | ayuda con transporte | |
| {help} in #7–9 | temporary housing | alojamiento temporal | |
| {help} | insurance guidance | orientación sobre seguros | |
| {help} | supplies | suministros | |
| {help} | medical equipment replacement | reemplazo de equipo médico | |
| {help} | casework | manejo de casos | |

## 4. Replies the system understands

Accents and capital letters don't matter (*SÍ* = *si*). Please tell us about any common ways of answering that are missing.

| Meaning | Spanish replies understood |
|---|---|
| Need help | 1, necesito ayuda, ayuda, ayúdenme, or describing a need (e.g. "uso silla de ruedas") |
| Have a plan | 2, tengo un plan |
| Already left | 3, ya salí, ya me fui |
| Call me | 4, llámenme, llámeme, llámame, llamar |
| Yes | sí, correcto, confirmo |
| No | no, incorrecto |
| Picked up | recogido, recogida, me recogieron, ya me recogieron |
| Needs recognized in free text | silla de ruedas · ayuda para subir · oxígeno · perro/animal de servicio · perro, gato, mascota |

Missing phrases you'd expect people to send:

&nbsp;

## Sign-off

- Reviewer: Developer B
- Date: 2026-10-18
- [x] All rows OK, no changes.

Decision B-14 in `docs/decisions.md` is closed. Any later wording change should be re-checked with this sheet.
