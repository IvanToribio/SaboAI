# Acuerdos del MVP de SaboteurAI

Este documento recoge las decisiones confirmadas durante la entrevista actual. El código existente y los archivos de `antiguos-docs/` son contexto revisable; las propuestas que contienen requieren confirmación antes de incorporarlas al MVP.

## Objetivo y participantes

El objetivo inicial es estudiar la cooperación entre agentes LLM. Todos los jugadores serán mineros y sus instrucciones indicarán que todos comparten el objetivo de conectar la entrada con el oro. No se mantendrá incertidumbre sobre la presencia de un saboteador en el MVP.

Los agentes deben poder comunicarse mediante mensajes públicos.

## Protocolo inicial de comunicación

Antes de cada acción se celebrará una ronda pública de conversación. Cada uno de los cinco agentes tendrá una oportunidad de intervenir, con un máximo inicial de 80 palabras, o podrá guardar silencio. El orden completo de los cinco hablantes se barajará antes de cada conversación; este acuerdo sustituye la propuesta inicial de primer hablante rotatorio.

El orden será reproducible mediante una semilla y quedará registrado en cada turno. La aleatoriedad de la conversación se mantendrá separada de la preparación del juego para que modificar el protocolo no altere el reparto inicial. El barajado evita una posición de conversación fijada sistemáticamente por el turno de juego, pero no garantiza posiciones equilibradas en una partida corta.

Las intervenciones serán secuenciales. Se conservarán los mensajes y su orden para que cada agente pueda leer las intervenciones anteriores antes de responder. Después de la conversación, el jugador activo elegirá su acción.

Si un mensaje supera las 80 palabras, se solicitará una versión más corta una sola vez. Si la revisión también supera el límite, se publicarán únicamente sus primeras 80 palabras. El registro conservará el mensaje original, la revisión y el texto finalmente publicado, identificando cualquier recorte.

Este protocolo es provisional. Se revisará en el piloto según el tiempo de ejecución, el rendimiento del modelo y la utilidad observada de la conversación.

## Partidas y memoria

Cada partida experimental será una ronda independiente. Los agentes conservarán memoria dentro de esa partida y empezarán la siguiente sin memoria de partidas anteriores.

Inicialmente se conservará el historial completo permitido para cada agente, sin resúmenes automáticos: estado actual observable, mensajes y acciones públicas anteriores y sus propios resultados privados de inspección. Se excluirán manos e inspecciones privadas ajenas, salvo lo que otros jugadores declaren públicamente.

Esta estrategia queda sujeta al tiempo de ejecución y a la capacidad de contexto del modelo. Si resulta demasiado lenta o excede esa capacidad, se revisará explícitamente cómo reducir el contexto, sin eliminar información silenciosamente.

## Configuración provisional para el piloto

Se mantienen cinco jugadores y seis cartas iniciales por jugador. El mazo tendrá 47 cartas: 32 túneles, cinco cartas para romper picos, cuatro para repararlos, tres mapas y tres derrumbes.

El piloto comprobará la dificultad de las partidas y la utilidad de esta composición. Las cantidades podrán cambiar según lo observado; mantenerlas ahora no implica que su equilibrio esté demostrado.

## Mecánicas y referencia del juego

Se conservan como base provisional las mecánicas descritas en las reglas antiguas: colocación y conexiones internas de túneles, giros, inspecciones, revelación de destinos, derrumbes, efectos del pico, robo y finalización de la ronda.

La intención es que las mecánicas aplicables a las cartas utilizadas funcionen como en Saboteur original. El [contraste con el reglamento oficial](contraste-mecanicas.md) recoge las coincidencias comprobadas, las convenciones digitales y los límites de la verificación del motor y el catálogo.

Las adaptaciones deliberadas son la composición reducida del mazo, la retirada de lámparas, vagonetas y sus reparaciones, y la ausencia de saboteadores. Se mantiene únicamente el pico como herramienta. La unidad experimental sigue siendo una ronda independiente, sin puntuación acumulada entre rondas.

El contraste deberá distinguir estas adaptaciones de discrepancias no previstas en las mecánicas. Las discrepancias se presentarán para decidir si deben corregirse o aceptarse como nuevas adaptaciones; no se incorporarán como decisiones ya aprobadas.

## Registro y criterio de completado

El MVP debe ejecutar una partida local completa con cinco agentes LLM que reciben su información, conversan, eligen acciones y conservan memoria dentro de la ronda. Python valida las acciones y determina el resultado. Una victoria y una derrota reglamentarias son resultados válidos; una interrupción técnica se registra por separado y no cuenta como partida completa.

El registro forma parte del MVP. Debe permitir reconstruir la partida y conocer qué información recibió cada agente, qué mensajes intercambió, qué respuestas produjo y qué acciones se aplicaron. Se conservarán configuración, semillas, estado inicial, instrucciones y parámetros del modelo, observaciones entregadas, mensajes ordenados, respuestas originales, intentos de acción, validaciones, reintentos, intervenciones automáticas, cambios de estado, resultado y errores. Se recogerán tiempos y consumo cuando el proveedor los facilite, distinguiendo datos ausentes de valores cero.

La información privada y los datos exclusivos del evaluador se conservarán sin entregarlos a agentes no autorizados. El registro excluye credenciales.

La definición completa de métricas, el protocolo experimental y los estudios de cooperación se abordarán después del MVP. El registro debe conservar desde el principio la evidencia necesaria para ese trabajo.

## Observación de las partidas

El MVP se utilizará por consola. Su salida debe permitir a Iván entender el tablero, el turno y jugador activo, los mensajes, las acciones y sus consecuencias, y el resultado. Se explicarán los símbolos y las coordenadas utilizados; un volcado de datos sin explicación no satisface este requisito.

La partida avanzará automáticamente y mostrará lo que ocurre conforme se ejecuta. Iván podrá detenerla en cualquier momento. En ese caso se guardará lo ocurrido hasta entonces y la ejecución se clasificará como interrupción manual. El modo con pausas para inspeccionar y continuar se reserva para una posible ampliación.

La visualización gráfica queda fuera del MVP y se contempla como ampliación posterior.

## Ejecución de los agentes

Se utilizará inicialmente un mismo modelo local mediante Ollama, con contextos y memoria independientes para cada jugador. Las consultas serán secuenciales. Compartir el modelo no permite compartir información privada entre agentes.

El modelo concreto se elegirá tras comprobar velocidad y fiabilidad. Si la ejecución local no funciona adecuadamente o resulta demasiado lenta, se estudiará la viabilidad de otras opciones antes de adoptarlas. No se considera aprobado ningún servicio de pago.

## Elección y validación de acciones

Python proporcionará al jugador activo las acciones legales disponibles, calculadas sin revelar información que el jugador no deba conocer. El agente elegirá entre ellas según su información y la conversación. El motor no recomendará una jugada ni resolverá la estrategia del equipo.

Python validará la respuesta antes de modificar el estado del juego. Ofrecer acciones legales no garantiza que el modelo responda con un formato correcto o elija una de ellas.

## Instrucciones iniciales y estrategia

Todos los agentes recibirán las mismas instrucciones iniciales sobre reglas, objetivo compartido, información disponible y formatos y oportunidades de acción y comunicación. Sus observaciones y su memoria serán individuales.

No se introducirán pistas estratégicas, consejos sobre cómo cooperar ni personalidades distintas. Las aclaraciones necesarias para interpretar el tablero y utilizar los formatos no deberán recomendar jugadas ni estrategias de coordinación.

Se estudiará si los agentes usan por iniciativa propia la comunicación para compartir información, acordar acciones y coordinarse. Esa conducta no se presupone ni se exige como resultado positivo: su ausencia también deberá poder observarse y analizarse. La aparición de coordinación en estas condiciones no implica que el modelo carezca de conocimientos previos sobre cooperación.

Dar pistas estratégicas y comparar su efecto se contempla como posible estudio posterior, fuera del MVP.

## Recuperación de respuestas de acción inválidas

Ante una respuesta que no se pueda interpretar o una acción inválida, Python explicará el error al jugador activo y permitirá un único reintento. Si la segunda respuesta también falla, se descartará automáticamente la primera carta según el orden registrado de la mano y se continuará la partida. No se elegirá una carta por conveniencia estratégica.

El registro conservará ambas respuestas inválidas y sus errores de interpretación o validación, el motivo comunicado para el reintento y la carta descartada automáticamente. Distinguirá estas intervenciones de las decisiones válidas del agente. Se medirá su frecuencia; si son frecuentes, deberá corregirse la interacción con el modelo antes de evaluar la cooperación.

Esta política se aplica a respuestas de acción inválidas.

## Fallos del servicio del modelo

Si Ollama no responde o se produce un fallo de conexión o del servicio durante una consulta, se permitirá un único reintento. Si vuelve a fallar, se conservará el registro de lo ocurrido y se detendrá la partida como interrupción técnica. No se contará como derrota reglamentaria ni se sustituirá la consulta fallida por un descarte automático.

El tiempo máximo de espera de una consulta sigue pendiente de fijar según las mediciones iniciales del modelo.

## Posibles ampliaciones

La prioridad actual es completar el MVP. No se adoptan como compromisos los plazos ni las estimaciones de dedicación de los documentos antiguos. Las ampliaciones se valorarán después, según el tiempo disponible.

- Introducir un saboteador y revisar qué saben los jugadores sobre su posible presencia.
- Incorporar memoria entre partidas.
- Añadir una visualización gráfica de las partidas.
- Estudiar el efecto de incluir pistas estratégicas en las instrucciones de los agentes.

Estas ampliaciones quedan fuera del MVP. Los detalles de funcionamiento restantes se concretarán en la entrevista.
