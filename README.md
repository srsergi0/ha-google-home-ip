# Google Home IP

Integración personalizada para [Home Assistant](https://www.home-assistant.io/) que reproduce audio en un **Google Home / Nest** conectándose **directamente a su IP local**, sin depender del descubrimiento mDNS.

Útil cuando Home Assistant está en otra red o subred (Docker sin `network_mode: host`, VLAN, VPN, Tailscale…) y la integración oficial *Google Cast* no encuentra el dispositivo.

- Se configura desde la interfaz: **Ajustes → Dispositivos y servicios → Añadir integración → Google Home IP**.
- Crea una entidad `media_player` por dispositivo: reproducir, pausa, stop, volumen (fijar, subir, bajar, silenciar), estado y volumen actual.
- Compatible con **Media Source** (explorador multimedia) y **TTS** (`tts.speak`).
- Servicio propio `google_home_ip.play_audio` con volumen temporal y restauración del volumen anterior.
- Reconexión automática si el Google Home se reinicia o se cae la red; la entidad aparece como *no disponible* mientras no responde.

## Requisitos

- Home Assistant **2025.10** o superior.
- Home Assistant debe llegar a la IP del Google Home por los puertos **8009** (protocolo Cast) y **8443** (información del dispositivo).
- Para reproducir **archivos locales o TTS**, el Google Home tiene que poder descargar el audio desde la URL de Home Assistant. Revisa **Ajustes → Sistema → Red → URL de Home Assistant** (red local). Las URLs públicas (`https://…`) funcionan siempre que el Google Home tenga Internet.
- Reserva la IP del Google Home en tu router (DHCP estático) para que no cambie. Si cambia, se puede actualizar desde las opciones de la integración.

## Instalación

### Con HACS (repositorio personalizado)

1. Abre **HACS** en Home Assistant.
2. Menú **⋮ → Repositorios personalizados**.
3. Repositorio: `https://github.com/srsergi0/ha-google-home-ip` · Tipo: **Integración** → **Añadir**.
4. Busca **Google Home IP** en HACS → **Descargar**.
5. **Reinicia Home Assistant.**

[![Abrir en HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=srsergi0&repository=ha-google-home-ip&category=integration)

### Manual

Copia la carpeta `custom_components/google_home_ip` en `/config/custom_components/` y reinicia Home Assistant.

## Configuración

1. **Ajustes → Dispositivos y servicios → Añadir integración → Google Home IP**.
2. Introduce la **IP** (por ejemplo `192.168.0.9`) y un **nombre** (por ejemplo `Salón`).
3. La integración comprueba que el dispositivo responde en el puerto 8009 antes de guardar y no permite añadir dos veces la misma IP.

Se crea la entidad `media_player.<nombre>` (por ejemplo `media_player.salon`).

**Cambiar la IP:** en la tarjeta de la integración pulsa **Configurar**, introduce la nueva IP y guarda. Se valida y la integración se recarga.

## Servicio `google_home_ip.play_audio`

| Parámetro | Obligatorio | Descripción |
|---|---|---|
| `entity_id` (target) | sí | Uno o varios `media_player` de esta integración. |
| `media` | sí | URL `http(s)://`, ID `media-source://…` o ruta local dentro de `/config/www`. |
| `volume` | no | Volumen (0–1) a fijar antes de reproducir. |
| `restore_volume` | no | `true` para volver al volumen anterior cuando termine el audio (por defecto `false`). |

**Rutas locales:** se aceptan `/config/www/sonidos/timbre.mp3`, `/local/sonidos/timbre.mp3` o `sonidos/timbre.mp3` (relativa a `www`). Se convierten automáticamente en `http://<URL interna de HA>/local/sonidos/timbre.mp3` para que el Google Home pueda descargarlas. Por seguridad, solo se permiten archivos dentro de `/config/www`.

**Tipo MIME:** se detecta por la extensión: `mp3` → `audio/mpeg`, `wav` → `audio/wav`, `ogg` → `audio/ogg`, `aac` → `audio/aac`, `flac` → `audio/flac`. Sin extensión reconocible (por ejemplo, streams de radio) se usa `audio/mpeg`.

```yaml
action: google_home_ip.play_audio
target:
  entity_id: media_player.salon
data:
  media: /config/www/sonidos/timbre.mp3
  volume: 0.6
  restore_volume: true
```

También funcionan los servicios estándar: `media_player.play_media`, `media_player.media_pause`, `media_player.media_stop`, `media_player.volume_set`, `media_player.volume_up`, `media_player.volume_down`, `media_player.volume_mute` y el explorador multimedia de la entidad.

## Ejemplos de automatización

### Aviso al abrir una puerta

Copia el sonido en `/config/www/sonidos/puerta.mp3`.

```yaml
alias: Aviso puerta abierta
triggers:
  - trigger: state
    entity_id: binary_sensor.puerta_entrada
    from: "off"
    to: "on"
actions:
  - action: google_home_ip.play_audio
    target:
      entity_id: media_player.salon
    data:
      media: /config/www/sonidos/puerta.mp3
      volume: 0.7
      restore_volume: true
mode: single
```

### Despertador con radio online

Sube el volumen poco a poco. Sustituye la URL por el stream de tu emisora.

```yaml
alias: Despertador con radio
triggers:
  - trigger: time
    at: "07:00:00"
conditions:
  - condition: time
    weekday: [mon, tue, wed, thu, fri]
actions:
  - action: media_player.volume_set
    target:
      entity_id: media_player.salon
    data:
      volume_level: 0.15
  - action: google_home_ip.play_audio
    target:
      entity_id: media_player.salon
    data:
      media: https://tu-emisora.example/stream.mp3
  - repeat:
      count: 5
      sequence:
        - delay: "00:01:00"
        - action: media_player.volume_up
          target:
            entity_id: media_player.salon
mode: single
```

### Mensaje de voz (TTS)

`tts.speak` funciona apuntando a la entidad de esta integración. Usa la entidad TTS que tengas (Google Translate, Piper, Home Assistant Cloud…).

```yaml
alias: Recordatorio de basura
triggers:
  - trigger: time
    at: "20:30:00"
conditions:
  - condition: time
    weekday: [tue, fri]
actions:
  - action: tts.speak
    target:
      entity_id: tts.google_translate_es_com
    data:
      media_player_entity_id: media_player.salon
      message: "Recuerda sacar la basura esta noche."
mode: single
```

## Solución de problemas

- **"El dispositivo no responde en el puerto 8009"**: comprueba la IP y que Home Assistant llega a ella, por ejemplo con `nc -vz 192.168.0.9 8009` desde el host.
- **La entidad está "no disponible"**: el Google Home no responde. La integración reintenta sola cada pocos segundos y vuelve a estar disponible cuando el dispositivo vuelve.
- **El servicio funciona pero no suena nada**: el Google Home no puede descargar el audio. Revisa la URL interna de Home Assistant (Ajustes → Sistema → Red) y que el altavoz tenga acceso a ella. En el registro aparece *"no pudo reproducir … Comprueba que la URL es accesible"*.

Para ver el detalle en el registro:

```yaml
logger:
  logs:
    custom_components.google_home_ip: debug
    pychromecast: info
```

## Cómo funciona

La integración usa [pychromecast](https://github.com/home-assistant-libs/pychromecast) con `known_hosts=[ip]` y sin zeroconf: pychromecast consulta la IP cada 30 segundos y mantiene un socket Cast con reintentos indefinidos. Todas las llamadas bloqueantes se ejecutan en el executor de Home Assistant. Al eliminar o recargar la integración se cierran la conexión y el sondeo.

## Licencia

[MIT](LICENSE)
