# Bob's World — 2.5D PoC

> **Статус:** В разработке
> **Дата:** 2026-03-03
> **Предыдущий документ:** Bob-work-PoC.md (Approach 4)
> **Decision Log:** D-017 (Return to Full 2D + Parallax)

---

## 1. Цель (PRD)

### Видение

Bob живёт в своём мире — "аквариуме", за которым наблюдает пользователь.
Камера фиксированная. Пользователь не взаимодействует — только смотрит.
Bob автономно генерирует свои окружения (Марс, мостик корабля, уютный бункер, токийское кафе)
и живёт в них: сидит, читает, работает, ходит, спит.

### Killer-фича

**Безграничные окружения.** Bob может "помечтать" о любом месте — и через 25 секунд
оказаться там. Это невозможно в 3D (нет open-source генератора 3D-сцен для Apple Silicon),
но тривиально в 2D (FLUX.2 генерирует любую сцену).

### Критерии успеха PoC

1. Bob отображается поверх AI-сгенерированного фона с параллакс-эффектом
2. Bob может менять позу (idle → сидит → печатает)
3. Bob может "переехать" в новое окружение за <60 сек
4. Визуальная идентичность Bob сохраняется между сценами
5. Весь пайплайн работает локально на Mac Mini M4 16GB

### Что НЕ входит в PoC

- Голосовой ввод/вывод (TTS, STT)
- Взаимодействие пользователя с Bob
- LLM-мозг Bob (автономное принятие решений)
- Мобильное приложение / Android

---

## 2. Бюджет RAM: Mac Mini M4 16GB

### Общий бюджет

| Компонент | RAM |
|-----------|-----|
| macOS + система | ~3.5 GB |
| **ML-бюджет** | **~12.5 GB** |

### Профили загрузки (не одновременно!)

ML-модели загружаются по очереди, не все одновременно.
Bob переключается между профилями по необходимости.

#### Профиль: SCENE_GEN (генерация "мира" Боба)

| Модель | Назначение | RAM |
|--------|-----------|-----|
| FLUX.2 Klein 4B (q4) | Генерация "мира" Боба, самого Боба | ~2.0 GB |
| FLUX.1 Kontext dev (q4) | Айдентика и стабильность "мира" и Боба, одежда, окружение | ~6.0 GB |
| **Итого** | | **~8.0 GB** |

#### Профиль: DEPTH (разделение на слои)

| Модель | Назначение | RAM |
|--------|-----------|-----|
| Depth Anything V2 (Small/Base) | Карта глубины из 2D | ~0.1-0.4 GB |
| **Итого** | | **~0.4 GB** |

#### Профиль: BRAIN (LLM для автономного Bob)

| Модель | Назначение | RAM |
|--------|-----------|-----|
| Qwen3-8B (q4) via Ollama | Мозг Bob (reasoning) | ~6.5 GB |
| Qwen3-0.6B (q4) via Ollama | Быстрые решения | ~0.9 GB |
| Qwen3Guard-Gen-0.6B (q4) via Ollama | ContentGuard (фильтр контента) | ~0.9 GB |
| nomic-embed-text via Ollama | SemanticMemory embeddings | ~0.3 GB |
| **Итого** | | **~8.6 GB** |

#### Профиль: VOICE (речь Bob)

| Модель | Назначение | RAM |
|--------|-----------|-----|
| Qwen3-TTS-0.6B via mlx-audio | TTS (голос Bob) | ~1.5 GB |
| Whisper Large-v3-Turbo via mlx-audio | STT (слух Bob) | ~3.0 GB |
| **Итого** | | **~4.5 GB** |

#### Профиль: VISION (зрение Bob)

| Модель | Назначение | RAM |
|--------|-----------|-----|
| YOLO26n via ultralytics | Камера с гимбалом — детекция людей, объектов, жестов | ~0.3 GB |
| **Итого** | | **~0.3 GB** |

#### Профиль: DEV (самоулучшение и разработка)

| Инструмент | Назначение | RAM |
|------------|-----------|-----|
| Claude Code CLI (Opus 4.6) | Буст IQ, рефлексия, самоулучшение, разработка, мультиагентный режим | ~1.0-3.0 GB |
| **Итого** | | **~1.0-3.0 GB** |

### Почему это работает

Профили загружаются по очереди:
- Bob решает "хочу на Марс" (BRAIN) → выгружаем BRAIN
- Генерируем "мир" Марса (SCENE_GEN) → выгружаем SCENE_GEN
- Строим карту глубины (DEPTH) → выгружаем DEPTH
- Bob живёт в сцене (только Godot, ~0 ML RAM)
- Bob говорит/слушает (VOICE) — загружается по необходимости
- Bob смотрит камерой (VISION) — может работать фоном (~0.3 GB)
- Bob разрабатывает/рефлексирует (DEV) — Claude Code CLI запускается по необходимости

Пиковое использование: ~8.6 GB (BRAIN) из 12.5 GB бюджета. Запас ~4 GB.

**Внимание:** BRAIN + VOICE одновременно = ~13.1 GB — на пределе бюджета.
В этом случае можно использовать Qwen3-4B (q4, ~3.5 GB) вместо 8B для reasoning.

---

## 3. Стек LLM / AI-моделей

### Полный стек Bob (актуален на 2026-03-03)

| # | Модель | Назначение | Runtime | RAM | Установка | Статус |
|---|--------|-----------|---------|-----|-----------|--------|
| 1 | **Qwen3-0.6B** (q4) | Быстрые решения | Ollama | ~0.9 GB | `ollama pull qwen3:0.6b` | RFC |
| 2 | **Qwen3-8B** (q4) | Мозг Bob (reasoning) | Ollama | ~6.5 GB | `ollama pull qwen3:8b` | RFC |
| 3 | **Qwen3-TTS-0.6B** | TTS (голос Bob) | mlx-audio | ~1.5 GB | `pip install "mlx-audio>=0.1"` | RFC |
| 4 | **Whisper Large-v3-Turbo** | STT (слух Bob) | mlx-audio | ~3.0 GB | (то же — mlx-audio) | RFC |
| 5 | **Qwen3Guard-Gen-0.6B** (q4) | ContentGuard | Ollama | ~0.9 GB | `ollama pull sileader/qwen3guard:0.6b` | Обновлено (замена LlamaGuard) |
| 6 | **nomic-embed-text** | SemanticMemory embeddings | Ollama | ~0.3 GB | `ollama pull nomic-embed-text` | Обновлено (замена MiniLM) |
| 7 | **YOLO26n** | Зрение Bob (камера с гимбалом) | ultralytics | ~0.3 GB | `pip install ultralytics` | Обновлено (замена YOLOv8) |
| 8 | **FLUX.2 Klein 4B** (q4) | Генерация "мира" Боба, самого Боба | mflux | ~2.0 GB | `uv tool install mflux --with tiktoken --with protobuf --with sentencepiece` | Валидирован (D-004) |
| 9 | **FLUX.1 Kontext dev** (q4) | Айдентика и стабильность "мира" и Боба, одежда, Боб в сцене, элементы окружения | mflux | ~6.0 GB | (то же — mflux, модель: `akx/FLUX.1-Kontext-dev-mflux-4bit`) | Валидирован (этот PoC) |
| 10 | **Depth Anything V2** | Карта глубины → parallax слои | TBD | ~0.4 GB | TBD (mlx / coreml / transformers) | Не валидирован |
| 11 | **Claude Code CLI** (Opus 4.6) | Буст IQ, рефлексия, самоулучшение, разработка, мультиагентный режим | Claude Code CLI (локально на Mac Mini M4) | ~1.0-3.0 GB | `npm install -g @anthropic-ai/claude-code` | Используется |

### История обновлений стека

| Было (RFC) | Стало | Причина |
|-----------|-------|---------|
| Qwen2.5-0.5B | **Qwen3-0.6B** | Апгрейд поколения, thinking mode |
| Qwen2.5-7B-Q4 | **Qwen3-8B** | Апгрейд поколения, Qwen3-4B ≈ Qwen2.5-72B |
| Llama Guard 3-1B-INT4 | **Qwen3Guard-Gen-0.6B** | Компактнее (484 vs 923 MB), 119 языков, Apache 2.0, tri-class |
| all-MiniLM-L6-v2 | **nomic-embed-text** | Устарел (2021), 512→8K контекст, значительно лучше качество |
| YOLOv8 | **YOLO26n** | Меньше (2.4M vs 3.2M), быстрее, точнее (40.9 vs 37.3 mAP) |
| Stable Diffusion | **FLUX.2 + Kontext + Depth Anything V2** | mflux не поддерживает SD; FLUX.2 качественнее |
| Kokoro TTS | **Qwen3-TTS-0.6B + Whisper** (через mlx-audio) | Единый пакет STT+TTS, нативный Apple Silicon |

### Зависимости (pip / uv)

| Пакет | Команда установки | Назначение |
|-------|-------------------|-----------|
| mflux | `uv tool install mflux --with tiktoken --with protobuf --with sentencepiece` | FLUX.2 + Kontext |
| mlx-audio | `pip install "mlx-audio>=0.1"` | TTS (Qwen3-TTS) + STT (Whisper) |
| ultralytics | `pip install ultralytics` | YOLO26 (зрение Bob) |
| depth-anything-v2 | TBD | Depth estimation |
| Godot 4.6 | standalone binary | Рендер + UI |
| Ollama | standalone binary | LLM runtime (Qwen3, Guard, embeddings) |
| Claude Code CLI | `npm install -g @anthropic-ai/claude-code` | AI-ассистент для разработки |

---

## 4. Полный пайплайн 2.5D

### 4.1 Обзор архитектуры

```
┌─────────────────────────────────────────────────────┐
│                    Bob's World                       │
│                                                      │
│  ┌──────────┐    ┌──────────┐    ┌───────────────┐  │
│  │  FLUX.2   │    │  Kontext  │    │ Depth Anything│  │
│  │ Klein 4B  │    │   dev     │    │     V2        │  │
│  │           │    │           │    │               │  │
│  │ Генерация │    │ Bob в     │    │ Карта глубины │  │
│  │ фона      │    │ сцене     │    │ → слои        │  │
│  └─────┬─────┘    └─────┬─────┘    └───────┬───────┘  │
│        │                │                  │          │
│        ▼                ▼                  ▼          │
│  ┌─────────────────────────────────────────────────┐  │
│  │              Godot 4.6 (2.5D рендер)            │  │
│  │                                                  │  │
│  │  Layer 0 (far):  небо / космос / дальний план   │  │
│  │  Layer 1 (mid):  стены / ландшафт               │  │
│  │  Layer 2 (near): мебель / предметы рядом с Bob  │  │
│  │  Layer 3 (bob):  ★ ANIMATED BOB SPRITE ★        │  │
│  │  Layer 4 (fg):   предметы перед Bob             │  │
│  │                                                  │  │
│  │  Camera: fixed + subtle breathing (±2px)         │  │
│  └─────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

### 4.2 Шаг за шагом

#### Шаг 1: Генерация фона (FLUX.2 Klein 4B)

```bash
mflux-generate-flux2 \
  --model flux2-klein-4b \
  --width 1024 --height 768 \
  --steps 4 --quantize 4 --seed 42 \
  --prompt "Cozy fallout vault bunker interior, warm lighting, ..."
  --output background.png
```

- Время: ~25 сек
- Выход: 1024x768 PNG (фон БЕЗ Bob)

#### Шаг 2: Генерация Bob в позе (FLUX.1 Kontext)

```bash
mflux-generate-kontext \
  --model akx/FLUX.1-Kontext-dev-mflux-4bit \
  --width 1024 --height 768 \
  --steps 24 --seed 101 \
  --image-path bob_base_vaultboy.png \
  --prompt "Place this exact character sitting in armchair reading book..."
  --output bob_in_scene.png
```

- Время: ~8 мин
- Выход: 1024x768 PNG (Bob в сцене)
- **Identity preservation**: тот же персонаж в любой позе/окружении

#### Шаг 3: Карта глубины (Depth Anything V2)

```python
# Применить к bob_in_scene.png → depth_map.png
# depth_map: чёрно-белое, светлое = близко, тёмное = далеко
```

- Время: <1 сек
- Выход: depth map того же разрешения

#### Шаг 4: Разделение на слои

```python
# По порогам глубины (0.0–1.0):
# Layer 0 (far):   depth < 0.2  — небо, дальний план
# Layer 1 (mid):   0.2–0.5      — стены, средний план
# Layer 2 (near):  0.5–0.8      — мебель, предметы
# Layer 3 (bob):   Bob sprite (вырезан из bob_in_scene.png)
# Layer 4 (fg):    depth > 0.8  — передний план

# Каждый слой = PNG с прозрачностью (alpha mask из depth)
```

- Время: <1 сек
- Выход: 3-5 PNG-слоёв

#### Шаг 5: Сборка в Godot (2.5D)

```
ParallaxBackground
├── ParallaxLayer (far)    — motion_scale: 0.1
├── ParallaxLayer (mid)    — motion_scale: 0.3
├── ParallaxLayer (near)   — motion_scale: 0.7
├── AnimatedSprite2D (Bob) — motion_scale: 1.0
└── ParallaxLayer (fg)     — motion_scale: 1.2
```

- Camera breathing: синусоидальное смещение ±2px → слои сдвигаются на разную величину → параллакс

### 4.3 Альтернативный подход к Шагу 2 (упрощённый)

Вместо раздельной генерации фона и Bob, можно:
1. Генерировать фон через FLUX.2 (25 сек)
2. Генерировать Bob СРАЗУ в этой сцене через Kontext (8 мин)
3. Вырезать Bob из сцены (rembg или ручная маска по depth)
4. Использовать оба: фон без Bob для слоёв + Bob как отдельный спрайт

Этот подход гарантирует стилистическое единство Bob и окружения.

---

## 5. Валидация (уже проведена)

### 5.1 FLUX.2 Klein 4B — генерация фонов

| Тест | Результат | Время | Файл |
|------|----------|-------|------|
| Mars scene concept | Отлично | 25 сек | `mars_parallax_concept.png` (удалён из repo) |

### 5.2 FLUX.1 Kontext — identity preservation

| Тест | Результат | Время | Файл |
|------|----------|-------|------|
| Base Bob (Vault Boy) | Отлично | 24 сек (FLUX.2) | `bob-preview/bob_base_vaultboy.png` |
| Bob на Марсе | Отлично — тот же персонаж | 8.5 мин | `bob-preview/bob_mars_fallout.png` |
| Bob на мостике корабля | Отлично — тот же персонаж | 8.5 мин | `bob-preview/bob_spaceship_bridge.png` |
| Bob в бункере с книгой | Отлично — тот же персонаж, другая поза | 8 мин | `bob-preview/bob_bunker_reading.png` |

**Вывод:** Kontext надёжно сохраняет идентичность Bob (лицо, бородка, волосы, комбинезон, стиль)
через совершенно разные сцены и позы. Подход D (AI-генерация спрайтов) валидирован.

### 5.3 Depth Anything V2 — НЕ валидирован

Требуется:
- Установить на macOS Apple Silicon
- Запустить на одном из сгенерированных изображений
- Проверить качество карты глубины
- Проверить возможность разделения на слои

### 5.4 Godot 2.5D parallax — НЕ валидирован

Требуется:
- Создать сцену с ParallaxBackground + ParallaxLayer
- Загрузить слои из Шага 4
- Добавить camera breathing
- Проверить визуальный результат

---

## 6. Открытые вопросы

### Q1: Анимация Bob (РЕШЕНО частично)

**Решение:** FLUX Kontext генерирует Bob в разных позах из reference-изображения.
Каждая "поза" = отдельное изображение, а не кадры анимации.

**Оставшийся вопрос:** Как переходить между позами?
- Вариант A: Резкая смена (cut) — простейший
- Вариант B: Crossfade между спрайтами (Godot modulate.a)
- Вариант C: AI-интерполяция кадров (будущее)

### Q2: Как вырезать Bob из сцены?

- `rembg` (open source, работает на CPU)
- Depth-based маска (Bob = ближайший объект)
- Ручная маска по цвету/контуру

### Q3: Сколько поз нужно для PoC?

Минимум 3:
1. Стоит (idle) — базовый
2. Сидит в кресле — валидация позы
3. Сидит + читает книгу / печатает — валидация действия

### Q4: Параллакс — Godot 2D или 3D?

- **Godot 2D** (ParallaxBackground): проще, нативная поддержка
- **Godot 3D** (billboard спрайты на Z-плоскостях): более гибко, настоящая глубина
- Рекомендация: начать с 2D, перейти на 3D если понадобится

---

## 7. Риски

| Риск | Вероятность | Влияние | Митигация |
|------|------------|---------|-----------|
| Depth Anything V2 не работает на Apple Silicon | Низкая | Высокое | Есть MLX и CoreML порты |
| Kontext не даёт достаточной консистентности для анимации | Средняя | Высокое | Fallback: pre-rendered 3D→2D спрайты (Blender + Mixamo) |
| Parallax выглядит неестественно | Средняя | Среднее | Можно уменьшить эффект или убрать совсем |
| 8 мин на позу слишком долго | Высокая | Среднее | Позы генерируются заранее (не в реальном времени) |
| Вырезка Bob из фона некачественная | Средняя | Среднее | rembg + ручная доработка маски |

---

## 8. Связь с предыдущими документами

| Документ | Статус | Связь |
|---------|--------|-------|
| Bob-work-PoC.md | Архивный | История подходов 1-4, заменён этим документом |
| DecisionLog.md | Актуальный | D-017 = решение о переходе на 2D+parallax |
| RFC-Proof-of-VR-Concept.md | Требует обновления | После валидации PoC — полный rewrite |
