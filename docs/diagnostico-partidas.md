# Diagnóstico de duración y juego de los mineros

Se analizó un registro local de 47 turnos con Llama 3.1 8B. Terminó por agotamiento y acumuló **10 h 08 min en 541 intentos a Ollama**. Se reprodujeron sus jugadas con el motor actual y se hicieron consultas aisladas sobre una conversación y una posición a una jugada del oro.

| Causa | Evidencia | Cambio a probar |
|---|---|---|
| El historial crece y se reenvía en cada consulta | El máximo por turno pasó de 1.508 a 24.740 tokens. Ollama registró 5 h 11 min de procesamiento de entrada en respuestas exitosas. En la misma intervención del turno 9, conservar 5 mensajes y 10 eventos bajó de **4.330 a 1.568 tokens** y de **24,75 a 3,56 s**. El procesamiento de entrada pasó de 20,22 a 3,23 s. | Mantener tablero, mano, inspecciones propias y hechos públicos relevantes, más una ventana reciente. Conservar el historial íntegro en el registro. |
| Se hacen cinco intervenciones antes de actuar | Hablar y acortar mensajes sumaron **8 h 16 min (81,5 %)**. Se pidieron 106 revisiones por longitud y 52 mensajes se recortaron tras la revisión. Reproducir las mismas jugadas con un hablante por turno pasó de **282 a 94 consultas base**. | Probar un hablante por turno, con intervenciones adicionales tras acontecimientos relevantes. Pedir mensajes breves y recortar localmente. Mostrar quién está respondiendo antes de llamar al modelo. |
| Los reintentos amplifican la espera y cambian jugadas | Hubo **116 timeouts** de 120 s, 3 h 52 min de espera del cliente. El registro tuvo **37 primeras acciones inválidas de 47** y 12 descartes automáticos. En una prueba, el texto libre falló con y sin numeración. El esquema de enteros legales sí devolvió una elección válida. | Enviar opciones numeradas con salida restringida. Validar en Python y registrar formato inválido, timeout y descarte automático por separado. Fijar el plazo por consulta después de medir el perfil compacto. |
| El modelo elige acciones válidas que no avanzan hacia el oro | En el registro se colocaron 22 túneles y ninguno pasó de x=2, con destinos en x=8. En una posición con el oro inspeccionado a una jugada, la ficha de coordenadas y bocas dio **0/4** aciertos entre Llama 3.1 8B y Gemma 4 E2B. Escribir qué casillas comunica cada túnel dio **2/4**. Ambos aciertos ocurrieron al invertir las opciones. | Probar esta representación con casos variados y orden aleatorio. Medir por separado la validez, el avance y la victoria. La ficha puede mostrar geometría y hechos visibles sin recomendar una jugada. |
| El resultado llega a la consola, pero el controlador deja de consultar a los mineros | Con una acción prescrita, el motor emitió victoria al conectar el oro y derrota al agotar la última carta. Revelar piedra permitió el siguiente turno. En los cierres reglamentarios hubo **cero consultas posteriores** y el controlador solo envió el resultado al canal público. | Entregar el evento terminal a cada agente con estado, resultado y causa. Vaciar las acciones disponibles y detener las solicitudes de generación. |

Mediana por intento en el registro, incluidos los timeouts. Hablar **57,26 s**, acortar **81,20 s**, elegir acción **64,56 s** y corregirla **53,18 s**. En la reproducción sin Ollama, construir todas las observaciones llevó **1,43 s**, aplicar y registrar las jugadas **0,08 s** y guardar el episodio **0,20 s**.

**Prioridad del siguiente piloto.** Comparar historial acotado, número de hablantes y salida restringida por separado, con las mismas semillas. Evaluar primero situaciones cortas de avance, victoria y cierre. Registrar mediana y p95 por llamada y turno, tokens de entrada, acciones inválidas, descartes automáticos, uso de la información compartida y victorias. La reducción de llamadas mantiene jugadas fijadas de antemano. La comparación de historial procede de una sola pareja y la de victoria usa una sola posición en dos órdenes. Falta medir la duración y la victoria del protocolo combinado en partidas completas.

## Reproducción

Desde la raíz, con el registro privado del piloto como argumento:

```sh
PYTHONPATH=src python3 experiments/profile_episode.py /ruta/al/episode.json
PYTHONPATH=src python3 experiments/probe_ollama.py /ruta/al/episode.json
```

Pruebas de cierre y de decisión sobre el mismo tablero sintético, sin depender del registro:

```sh
PYTHONPATH=src python3 experiments/profile_episode.py
PYTHONPATH=src python3 experiments/probe_ollama.py --action-sheet-only --model gemma4:e2b
PYTHONPATH=src python3 experiments/probe_ollama.py --action-sheet-only --show-links --model gemma4:e2b
```

Las pruebas de decisión requieren Ollama local. Cada consulta tiene un plazo de 32 s de lectura y los resultados pueden variar con el modelo y el estado de la caché.
