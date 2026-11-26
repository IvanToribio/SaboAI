# SaboteurAI

SaboteurAI ejecuta una partida experimental de Saboteur con cinco mineros.
Los mineros comparten un modelo local de Ollama. Cada consulta incluye la mano y
las inspecciones del minero que interviene, junto con la información pública de la partida.

Desde la raíz del proyecto, instala el [cliente de Python de Ollama](https://github.com/ollama/ollama-python):

```sh
python3 -m pip install -r requirements.txt
```

Con [Ollama](https://ollama.com/) en ejecución en `127.0.0.1:11434`, descarga el modelo
si todavía no está instalado y empieza la partida:

```sh
ollama pull llama3.1:8b
PYTHONPATH=src python3 -m saboteurai --model llama3.1:8b
```

`llama3.1:8b` es el modelo por defecto. Con `--model` puedes elegir otro modelo instalado
localmente. SaboteurAI añade el selector `:local` para que Ollama rechace modelos remotos.
Usa una versión de Ollama que admita ese selector, como la 0.40.11 usada en la prueba.
Para simular una partida sin Ollama, ejecuta `PYTHONPATH=src python3 -m saboteurai --demo`.

La consola muestra la ruta del registro privado. Pulsa Ctrl+C para detener la partida
y guardar lo ocurrido. Cada consulta solicita 65 536 tokens de contexto y desactiva
el recorte del historial en Ollama. El tiempo de espera es de 120 segundos por intento.
Son valores provisionales para el piloto.
