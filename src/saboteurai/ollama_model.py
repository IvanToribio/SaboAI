"""Envía cada consulta del controlador al servidor local de Ollama."""

import json

import httpx
from ollama import Client, ResponseError

from .controller import ModelQuery, ModelReply, ModelServiceError, ModelSettings


_METRIC_FIELDS = {
    'prompt_eval_count': 'prompt_tokens',
    'eval_count': 'completion_tokens',
    'total_duration': 'total_duration_ns',
    'load_duration': 'load_duration_ns',
    'prompt_eval_duration': 'prompt_duration_ns',
    'eval_duration': 'completion_duration_ns',
}


class _FullContextTransport(httpx.BaseTransport):
    """Añade las opciones de /api/chat que Client.chat aún no expone."""

    def __init__(self, transport: httpx.BaseTransport) -> None:
        self._transport = transport

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read())
        body.update(truncate=False, shift=False)
        headers = request.headers.copy()
        headers.pop('content-length', None)
        return self._transport.handle_request(httpx.Request(
            request.method, request.url, json=body, headers=headers, extensions=request.extensions,
        ))

    def close(self) -> None:
        self._transport.close()


class OllamaModel:
    def __init__(self, name: str, *, transport: httpx.BaseTransport | None = None) -> None:
        name = name.strip()
        self.settings = ModelSettings('ollama', name, {'num_ctx': 65536, 'num_predict': 512})
        # El servidor rechaza modelos remotos cuando se exige la fuente local.
        self._model_ref = name if name.lower().endswith(':local') else f'{name}:local'
        if transport is None:
            transport = httpx.HTTPTransport(trust_env=False)
        self._client = Client(
            host='http://127.0.0.1:11434', timeout=120, trust_env=False, follow_redirects=False,
            transport=_FullContextTransport(transport),
        )

    def __call__(self, query: ModelQuery) -> ModelReply:
        # La observación ya contiene todo el historial permitido para este minero.
        prompt = {key: value for key, value in query.items() if key != 'instructions'}
        messages = [
            {'role': 'system', 'content': query['instructions']},
            {'role': 'user', 'content': json.dumps(prompt, ensure_ascii=False, separators=(',', ':'))},
        ]
        try:
            response = self._client.chat(
                model=self._model_ref, options=self.settings.parameters, messages=messages, stream=False,
            )
        except httpx.TimeoutException:
            raise ModelServiceError('timeout') from None
        except (ConnectionError, httpx.TransportError):
            raise ModelServiceError('connection') from None
        except ResponseError:
            raise ModelServiceError('service') from None
        except (httpx.DecodingError, TypeError, ValueError):
            raise ModelServiceError('invalid-response') from None

        text = response.message.content
        if response.done is not True or text is None:
            raise ModelServiceError('invalid-response')
        metrics = {}
        for field, metric in _METRIC_FIELDS.items():
            value = getattr(response, field)
            if value is not None:
                metrics[metric] = value
        return ModelReply(text, metrics or None)
