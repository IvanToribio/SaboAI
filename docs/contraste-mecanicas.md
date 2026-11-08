# Contraste de mecánicas y reutilización del motor

El motor Python es una base reutilizable para el MVP. Ya resuelve la preparación, las acciones y el final de una ronda y puede reproducir sus transiciones desde un registro. La integración con agentes necesita una vista individual, un controlador de partidas y un registro de las interacciones con el modelo.

La referencia principal es el [reglamento oficial de AMIGO del juego base, versión 4.0](https://blog.amigo-spiele.de/content/ap/rule/04900-GB-AmigoRule.pdf). Para contrastar los casos de borde se consultó también la [edición española de Mercurio, versión 1.0](https://garesys.com/media/rules/reglas-saboteur.pdf). El alcance experimental viene de los [acuerdos del MVP](MVP.md).

## Mecánicas contrastadas

| Mecánica | Qué coincide y qué se puede reutilizar |
| --- | --- |
| Preparación | Una entrada, tres destinos ocultos con un oro y dos piedras, siete espacios libres hasta la columna de destinos, un espacio entre destinos y seis cartas por jugador con cinco participantes. `new_game(0, seed)` prepara el MVP con 30 cartas en las manos y 17 por robar. [AMIGO, p. 1](https://blog.amigo-spiele.de/content/ap/rule/04900-GB-AmigoRule.pdf#page=1) · [state.py](../src/saboteurai/state.py#L45) |
| Túneles | El tablero puede crecer en cualquier dirección. La carta nueva debe encajar con sus vecinos visibles, quedar en vertical y estar conectada a la entrada por un camino continuo. El motor admite 0° y 180° y calcula el alcance por los extremos de los túneles, separando los ramales de una carta cortada. [AMIGO, p. 1](https://blog.amigo-spiele.de/content/ap/rule/04900-GB-AmigoRule.pdf#page=1) · [board.py](../src/saboteurai/board.py#L14) |
| Mapas y derrumbes | El mapa permite inspeccionar un destino oculto de forma privada. El derrumbe retira un túnel y deja un hueco que puede rellenarse. La entrada y los destinos están protegidos. [AMIGO, p. 2](https://blog.amigo-spiele.de/content/ap/rule/04900-GB-AmigoRule.pdf#page=2) · [engine.py](../src/saboteurai/engine.py#L104) |
| Pico | La rotura se juega sobre otro jugador con pico operativo. El pico roto bloquea la colocación de túneles y permite acciones o descarte. Una reparación puede aplicarse al pico roto propio o ajeno. Representar su estado con un valor booleano basta para esta variante de una sola herramienta. [AMIGO, p. 2](https://blog.amigo-spiele.de/content/ap/rule/04900-GB-AmigoRule.pdf#page=2) · [engine.py](../src/saboteurai/engine.py#L98) |
| Turno y cierre | Se juega o descarta una carta, se roba mientras haya mazo y se conservan ocultos los descartes de la mano. El motor cierra al alcanzar el oro o al agotarse las manos. Saltarse automáticamente una mano vacía equivale a pasar sin descartar en la edición española. [AMIGO, pp. 1–2](https://blog.amigo-spiele.de/content/ap/rule/04900-GB-AmigoRule.pdf) · [Mercurio, «Pasar»](https://garesys.com/media/rules/reglas-saboteur.pdf#page=2) · [engine.py](../src/saboteurai/engine.py#L147) |
| Destinos | El oro termina la ronda. Una piedra se revela en su casilla y la ronda continúa. Se busca una orientación compatible con los vecinos, con la excepción de encaje permitida al revelar un destino. El motor puede continuar el camino por una piedra. [AMIGO, p. 2](https://blog.amigo-spiele.de/content/ap/rule/04900-GB-AmigoRule.pdf#page=2) · [board.py](../src/saboteurai/board.py#L83) |

## Adaptaciones y convenciones digitales

- El juego base usa 40 túneles jugables y 27 cartas de acción. El MVP conserva su mazo provisional de 32 túneles y 15 cartas de acción, con el pico como única herramienta. Los cinco jugadores saben que son mineros y cada partida experimental comprende una ronda sin puntuación acumulada. [AMIGO, pp. 1–2](https://blog.amigo-spiele.de/content/ap/rule/04900-GB-AmigoRule.pdf) · [cards.py](../src/saboteurai/cards.py#L54) · [MVP.md](MVP.md)
- El manual hace empezar al jugador más joven. El motor elige al jugador inicial por semilla, como describían las reglas antiguas. Es una convención heredada adecuada para agentes sin edad, pendiente de considerar si se quiere controlar la posición inicial en la evaluación. [AMIGO, p. 1](https://blog.amigo-spiele.de/content/ap/rule/04900-GB-AmigoRule.pdf#page=1) · [state.py](../src/saboteurai/state.py#L50) · [Reglas antiguas](antiguos-docs/REGLAS.md#2-preparación-y-cartas)
- El motor resuelve las piedras con la orientación que conecta con la entrada y hace coincidir más bordes, desempata a favor de 0° y examina los destinos de arriba abajo. AMIGO describe cómo encajar la piedra y cuándo termina la ronda, pero no fija esos desempates ni el orden para dos destinos alcanzados en una jugada. Se comprobó ese caso con un cruce en `(8, -1)` que llega a los destinos de arriba y del centro. Con oro arriba, solo se revela el de arriba y termina la ronda. Con piedra arriba y oro en el centro, se revelan en ese orden y termina. Con dos piedras, se revelan ambas y continúa. Conviene conservar y documentar esta convención determinista. [AMIGO, p. 2](https://blog.amigo-spiele.de/content/ap/rule/04900-GB-AmigoRule.pdf#page=2) · [board.py](../src/saboteurai/board.py#L83)

## Geometría y cantidades del mazo

Las 16 formas del catálogo coinciden con las cartas fotografiadas del juego base en bordes abiertos y conexiones internas. Se transcribieron las formas del esquema y se compararon con los grupos de conexiones del código. Las fotos muestran las siete formas conectadas y las nueve sin paso. El reglamento de AMIGO confirma los totales del juego físico. [Túneles conectados](https://pimg.1px.tw/harry112930/1439175726-3035434718.jpg) · [Túneles sin paso](https://pimg.1px.tw/harry112930/1439175402-1969364486.jpg) · [Inventario gráfico de CMG Lee](https://commons.wikimedia.org/wiki/File:Saboteur_game_cards.svg) · [Reglamento de AMIGO](https://blog.amigo-spiele.de/content/ap/rule/04900-GB-AmigoRule.pdf) · [cards.py](../src/saboteurai/cards.py#L23)

N, E, S y O indican los bordes. En el código, el oeste se representa con `W`. El guion une bocas conectadas y la barra separa ramales sin conexión. Se usa una de las dos orientaciones equivalentes a 180°.

| Forma | Geometría | Juego base | MVP |
| --- | --- | ---: | ---: |
| Recta vertical | N–S | 4 | 3 |
| Recta horizontal | E–O | 3 | 2 |
| Curva inferior derecha | S–E | 4 | 3 |
| Curva inferior izquierda | S–O | 5 | 4 |
| Cruce vertical | N–S–E | 5 | 4 |
| Cruce horizontal | N–E–O | 5 | 4 |
| Cruce completo | N–E–S–O | 5 | 3 |
| Fondo de saco vertical | S | 1 | 1 |
| Fondo de saco horizontal | O | 1 | 1 |
| Recta vertical cortada | N / S | 1 | 1 |
| Recta horizontal cortada | E / O | 1 | 1 |
| Curva derecha cortada | S / E | 1 | 1 |
| Curva izquierda cortada | S / O | 1 | 1 |
| Cruce vertical cortado | N / S / E | 1 | 1 |
| Cruce horizontal cortado | N / E / O | 1 | 1 |
| Cruce completo cortado | N / E / S / O | 1 | 1 |
| **Total de túneles jugables** | | **40** | **32** |

Los túneles conectados pasan de 31 a 23 y los nueve sin paso se conservan. Su proporción dentro de los túneles aumenta del 22,5 % al 28,1 %. La entrada y el oro tienen cuatro bocas conectadas. Las piedras cubren las dos familias de curvas, contando giros de 180°. Estas cuatro cartas se colocan al preparar la partida y no se incluyen en el mazo. [Foto de los destinos](https://pimg.1px.tw/harry112930/1439174310-1023716907.jpg) · [Guía de Board Game Arena](https://en.doc.boardgamearena.com/Tips_saboteur#Know_your_paths!) · [cards.py](../src/saboteurai/cards.py#L54)

| Carta de acción | Juego físico | MVP |
| --- | ---: | ---: |
| Mapa | 6 | 3 |
| Derrumbe | 3 | 3 |
| Romper pico | 3 | 5 |
| Reparar pico | 2 | 4 |
| Romper lámpara o vagoneta | 6 | 0 |
| Reparar lámpara o vagoneta | 4 | 0 |
| Reparación doble | 3 | 0 |
| **Total de acciones** | **27** | **15** |
| **Mazo jugable completo** | **67** | **47** |

La versión digital de Board Game Arena usa cinco mapas y su documentación indica que retiró uno respecto a la caja. La comparación usa los seis del juego físico. [Inventario de la edición fotografiada](https://harry112930.pixnet.net/blog/posts/10299677592) · [Inventario gráfico de CMG Lee](https://commons.wikimedia.org/wiki/File:Saboteur_game_cards.svg) · [Reglas de Board Game Arena](https://en.doc.boardgamearena.com/Gamehelpsaboteur#Map) · [cards.py](../src/saboteurai/cards.py#L63)

## Evidencia de ejecución

Con CPython 3.12.8 pasaron 22 comprobaciones dirigidas. Incluyeron giros, bordes incompatibles, ramales cortados, reconexión tras derrumbe, inspecciones privadas, reparación, victoria con una piedra como parte del camino, rechazo de acciones inválidas y registro de una interrupción manual. La victoria preparada se guardó, se cargó y se reprodujo. Alterar una transición hizo que la reproducción detectara la discrepancia.

Se ejecutaron también 32 partidas con semillas de preparación del 0 al 31 y selección uniforme de acciones legales con un generador independiente de semilla 9091. Las 1.504 acciones se aplicaron y se reprodujeron sin discrepancias. En cada transición se comprobó que se conservaban todas las cartas y que un descarte de la mano no revelaba públicamente su identidad. Todas las partidas terminaron por agotamiento. Estas ejecuciones ejercitan el motor y el registro, y no miden la dificultad del mazo para mineros cooperativos. No se consultó ningún modelo.

## Reutilización en el MVP

1. **Conservar cartas, estado, tablero y reglas.** Usar `new_game(0, seed)`, `legal_actions`, `apply_action` y `interrupt_game` como puntos de entrada. Conservar la selección de 47 cartas y las reglas examinadas para el piloto. [state.py](../src/saboteurai/state.py#L45) · [engine.py](../src/saboteurai/engine.py#L124)
2. **Construir la vista de cada agente.** Reutilizar `public_board` y los eventos públicos y privados. Añadir su propia mano, sus inspecciones y el historial autorizado. El estado completo, la semilla de preparación y el registro del evaluador deben permanecer fuera de los prompts. La prueba de intercambio de dos destinos ocultos confirmó que, en el estado probado, ni el tablero público ni las acciones disponibles revelan el cambio. Falta comprobar la vista completa cuando exista. [records.py](../src/saboteurai/records.py#L147) · [engine.py](../src/saboteurai/engine.py#L155)
3. **Reutilizar la reproducción del juego y añadir la evidencia de los agentes.** El registro actual conserva estados, acciones, errores e interrupciones. Faltan observaciones entregadas, consultas al modelo, mensajes, orden de conversación, silencios, reintentos y tiempos. La cabecera está ligada al motor y formato actuales. Conviene mantener la compatibilidad con `record-v1` o versionar cualquier cambio de esquema y sustituir la referencia de código histórica antes de generar datos del piloto. [records.py](../src/saboteurai/records.py#L279) · [state.py](../src/saboteurai/state.py#L9)
4. **Añadir el controlador y la consola.** El controlador hará avanzar las conversaciones y los turnos, consultará al modelo, aplicará la recuperación acordada y mostrará la partida. El motor seguirá decidiendo si la jugada es legal y cuál es el resultado. [MVP.md](MVP.md)
