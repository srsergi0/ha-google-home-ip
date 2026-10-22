# Google Home IP

Integración personalizada para [Home Assistant](https://www.home-assistant.io/) que reproduce audio en un **Google Home / Nest** conectándose **directamente a su IP local**, sin depender del descubrimiento mDNS.

Útil cuando Home Assistant está en otra red o subred (Docker sin `network_mode: host`, VLAN, VPN, Tailscale…) y la integración oficial *Google Cast* no encuentra el dispositivo.

- Se configura desde la interfaz: **Ajustes → Dispositivos y servicios → Añadir integración → Google Home IP**.
- Crea una entidad `media_player` por dispositivo: reproducir, pausa, stop, volumen (fijar, subir, bajar, silenciar), encender/apagar, posición (seek) y siguiente/anterior cuando la app lo permite.
- Compatible con **Media Source** (explorador multimedia) y **TTS** (`tts.speak`).
- **Avisos que interrumpen y reanudan**: un TTS o un sonido corta la radio o el audio que esté sonando y, al terminar, lo reanuda en el mismo punto.
- Servicio `google_home_ip.announce` **pensado para automatizaciones**: campanita opcional + voz o audio, volumen automático día/noche, y la acción **espera a que termine** antes de seguir.
- **Campanitas incluidas** (`ding`, `ding_dong`, `aviso`, `alerta`), servidas por la propia integración.
- Servicio `google_home_ip.play_audio` con volumen temporal, restauración del volumen, **bucle** y **subida gradual** del volumen.
- Servicios `google_home_ip.fade_volume` (volumen progresivo) y `google_home_ip.sleep_timer` (apagado con bajada de volumen).
- **Entidad de eventos** y **disparadores de dispositivo** para el editor visual: aviso iniciado/terminado, reproducción terminada, error y temporizador terminado.
- **Entidades de ajuste**: volumen de avisos de día y de noche, y horario del modo noche.
- Sensores de diagnóstico: **conexión Cast**, **señal WiFi** (con red, punto de acceso y ruido), **último reinicio** y **temporizador de apagado**. La ficha del dispositivo muestra modelo, firmware y MAC.
- Reconexión automática si el Google Home se reinicia o se cae la red; la entidad aparece como *no disponible* mientras no responde.

## Requisitos

- Home Assistant **2025.10** o superior.
- Home Assistant debe llegar a la IP del Google Home por los puertos **8009** (protocolo Cast) y **8443** (información del dispositivo).
- Para reproducir **archivos locales o TTS**, el Google Home tiene que poder descargar el audio desde Home Assistant. Por defecto se usa la URL interna (**Ajustes → Sistema → Red**). Si Home Assistant está en otra red (por ejemplo, en un VPS con acceso a casa por VPN o Tailscale), indica en las opciones de la integración una **URL de Home Assistant para el altavoz** que el Google Home pueda abrir, como tu URL pública `https://…`. Las URLs externas (`https://…`) funcionan siempre que el Google Home tenga Internet.
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

### Opciones

En la tarjeta de la integración pulsa **Configurar**:

- **Dirección IP**: cambia la IP si el Google Home tiene una nueva. Se valida y la integración se recarga.
- **URL de Home Assistant para el altavoz** (opcional): URL base desde la que el Google Home descarga los archivos de `/config/www` y el TTS, por ejemplo `https://ha.midominio.com`, sin ruta. Déjala vacía para usar la URL interna de Home Assistant.

## Entidades

Para un dispositivo llamado `Salón`:

| Entidad | Descripción |
|---|---|
| `media_player.salon` | Reproductor. Está `off` cuando no hay ninguna app Cast abierta. |
| `binary_sensor.salon_cast_connection` | `on` si el socket Cast (puerto 8009) está conectado. Siempre disponible, útil para avisar de caídas. |
| `sensor.salon_wifi_signal` | Señal WiFi en dBm. Atributos: `ssid`, `bssid`, `noise_level`, `ip_address`. |
| `sensor.salon_last_boot` | Hora del último arranque del altavoz. |
| `sensor.salon_sleep_timer` | Hora a la que el temporizador apagará el altavoz (sin valor si no hay). |
| `event.salon_events` | Último evento del altavoz; úsalo como disparador en automatizaciones. |
| `number.salon_announcement_volume_day` / `_night` | Volumen (%) de los avisos de día y de noche. |
| `time.salon_night_mode_start` / `_end` | Inicio y fin del tramo nocturno para el volumen de los avisos. |

Los sensores de diagnóstico se leen cada 60 s de la API local del dispositivo (puerto 8443) y no necesitan cuenta de Google. Los nombres se muestran traducidos, pero Home Assistant genera los IDs a partir del nombre en inglés.

## Servicio `google_home_ip.play_audio`

| Parámetro | Obligatorio | Descripción |
|---|---|---|
| `entity_id` (target) | sí | Uno o varios `media_player` de esta integración. |
| `media` | sí | URL `http(s)://`, ID `media-source://…` o ruta local dentro de `/config/www`. |
| `volume` | no | Volumen (0–1) a fijar antes de reproducir. |
| `restore_volume` | no | `true` para volver al volumen anterior cuando termine el audio (por defecto `false`). |
| `announce` | no | `true` para reanudar lo que estaba sonando cuando termine el audio (por defecto `false`). |

**Rutas locales:** se aceptan `/config/www/sonidos/timbre.mp3`, `/local/sonidos/timbre.mp3` o `sonidos/timbre.mp3` (relativa a `www`). Se convierten automáticamente en `<URL de HA>/local/sonidos/timbre.mp3` para que el Google Home pueda descargarlas. Se usa la URL de las opciones de la integración o, si no hay, la URL interna. Por seguridad, solo se permiten archivos dentro de `/config/www`.

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

### Avisos (`announce`)

Con `announce: true` (o con `tts.speak`, que siempre lo envía) el audio se reproduce como un aviso: si el Google Home estaba reproduciendo algo con el receptor genérico (radio, archivos, otro TTS…), se guarda el punto exacto y se reanuda cuando termina el aviso, después de restaurar el volumen si se pidió `restore_volume`. Si detienes el aviso a mano, no se reanuda nada. Lo que suena desde apps como Spotify o YouTube no se puede recuperar: el aviso lo corta.

También funcionan los servicios estándar: `media_player.play_media`, `media_player.media_pause`, `media_player.media_stop`, `media_player.volume_set`, `media_player.volume_up`, `media_player.volume_down`, `media_player.volume_mute` y el explorador multimedia de la entidad.

## Servicio `google_home_ip.announce`

El servicio recomendado para automatizaciones. Reproduce una **campanita** opcional y luego un **mensaje de voz** (TTS) o un **audio**, y al terminar reanuda lo que estuviera sonando. La acción **no termina hasta que el aviso acaba**, así que el siguiente paso de tu automatización se ejecuta después.

| Parámetro | Descripción |
|---|---|
| `entity_id` (target) | Uno o varios `media_player` de esta integración. |
| `message` | Texto a leer en voz alta (TTS). Usa esto **o** `media`. |
| `media` | URL, `media-source://…` o ruta local, en lugar de un mensaje de voz. |
| `chime` | Campanita antes del mensaje: `ding`, `ding_dong`, `aviso`, `alerta` o `none`. |
| `volume` | Volumen del aviso (0–1). Si se omite, se usa el **volumen automático día/noche**. |
| `tts_entity` | Entidad TTS a usar (si no, la predeterminada). |
| `language` | Idioma del mensaje, p. ej. `es`. |
| `fade_in` | Segundos para subir el volumen desde cero. |
| `resume` | Reanudar lo que sonaba al terminar (por defecto `true`). |

```yaml
action: google_home_ip.announce
target:
  entity_id: media_player.salon
data:
  message: "La cena está lista"
  chime: ding
```

El **volumen automático día/noche** se controla con las entidades `number.<nombre>_announcement_volume_day` / `_night` y el horario con `time.<nombre>_night_mode_start` / `_end`. Así un mismo aviso suena fuerte de día y bajo de noche sin tocar la automatización.

## Servicio `google_home_ip.fade_volume`

Lleva el volumen hasta un valor a lo largo de un tiempo. Si cambias el volumen a mano durante el fundido, se detiene.

```yaml
action: google_home_ip.fade_volume
target:
  entity_id: media_player.salon
data:
  volume: 0.6
  duration: 300   # 5 minutos
```

## Servicio `google_home_ip.sleep_timer`

Apaga el altavoz tras unos minutos, bajando el volumen poco a poco antes. `minutes: 0` cancela un temporizador en curso. La hora de apagado aparece en `sensor.<nombre>_sleep_timer`.

```yaml
action: google_home_ip.sleep_timer
target:
  entity_id: media_player.salon
data:
  minutes: 30
  fade_out: 30
```

## Automatizaciones por evento

La entidad `event.<nombre>_events` y los **disparadores de dispositivo** exponen estos eventos: `announcement_started`, `announcement_finished`, `playback_finished`, `playback_error` y `sleep_timer_finished`. En el editor visual aparecen como «Cuando _Baño speaker_ → …».

```yaml
alias: Luz cuando termina la música
triggers:
  - trigger: device
    domain: google_home_ip
    device_id: <id del dispositivo>
    type: playback_finished
actions:
  - action: light.turn_off
    target:
      entity_id: light.salon
```

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

### Timbre que no corta la radio para siempre

```yaml
alias: Timbre
triggers:
  - trigger: state
    entity_id: binary_sensor.timbre
    to: "on"
actions:
  - action: google_home_ip.play_audio
    target:
      entity_id: media_player.salon
    data:
      media: /config/www/sonidos/timbre.mp3
      volume: 0.8
      restore_volume: true
      announce: true
mode: single
```

### Aviso si el altavoz se desconecta

```yaml
alias: Google Home desconectado
triggers:
  - trigger: state
    entity_id: binary_sensor.salon_cast_connection
    to: "off"
    for: "00:10:00"
actions:
  - action: notify.notify
    data:
      message: "El Google Home del salón lleva 10 minutos sin conexión."
mode: single
```

### Despertador amanecer (sube el volumen solo)

```yaml
alias: Despertador amanecer
triggers:
  - trigger: time
    at: "07:00:00"
actions:
  - action: google_home_ip.play_audio
    target:
      entity_id: media_player.salon
    data:
      media: https://tu-emisora.example/stream.mp3
      volume: 0.5
      fade_in: 300   # sube de 0 a 50 % en 5 min
mode: single
```

### Lluvia para dormir (bucle + apagado)

```yaml
alias: Lluvia 30 min
triggers: []
actions:
  - action: google_home_ip.play_audio
    target:
      entity_id: media_player.salon
    data:
      media: /local/sonidos/lluvia.mp3
      loop: true
  - action: google_home_ip.sleep_timer
    target:
      entity_id: media_player.salon
    data:
      minutes: 30
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
- **La entidad está "no disponible"**: el Google Home no responde (míralo en `binary_sensor.<nombre>_cast_connection` y en el diagnóstico descargable de la integración). La integración reintenta sola cada pocos segundos y vuelve a estar disponible cuando el dispositivo vuelve.
- **El volumen cambia pero no suena nada (TTS o archivos locales)**: el Google Home no puede descargar el audio desde la URL de Home Assistant. Abre esa URL desde otro dispositivo de la misma red que el altavoz. Si no carga, configura la **URL de Home Assistant para el altavoz** en las opciones de la integración. Con el registro en `debug` verás la URL exacta que se envía (`Reproduciendo en …`).
- **Suena una versión antigua de un archivo**: si accedes a Home Assistant a través de Cloudflare u otro CDN, los archivos de `/local/` pueden quedar en caché. Usa un nombre de archivo nuevo o purga la caché del CDN.
- **Algunas URLs externas no suenan**: hay servicios que bloquean las descargas desde dispositivos Cast (por ejemplo, el endpoint web de Google Translate). Usa una entidad TTS de Home Assistant con `tts.speak`.

Para ver el detalle en el registro:

```yaml
logger:
  logs:
    custom_components.google_home_ip: debug
    pychromecast: info
```

## Cómo funciona

La integración usa [pychromecast](https://github.com/home-assistant-libs/pychromecast) con `known_hosts=[ip]` y sin zeroconf: pychromecast consulta la IP cada 30 segundos y mantiene un socket Cast con reintentos indefinidos. Todas las llamadas bloqueantes se ejecutan en el executor de Home Assistant. Al eliminar o recargar la integración se cierran la conexión y el sondeo.

Los sensores leen `https://<ip>:8443/setup/eureka_info`, la API local que usa la app Google Home. Su lectura no requiere token; el diagnóstico descargable oculta la MAC, la red WiFi y los identificadores del dispositivo.

## Licencia

[MIT](LICENSE)
