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

### Полный стек Bob (актуален на 2026-03-04)

| # | Модель | Назначение | Runtime | RAM | Установка | Статус |
|---|--------|-----------|---------|-----|-----------|--------|
| 1 | **Qwen3-0.6B** (q4) | Быстрые решения | Ollama | ~0.9 GB | `ollama pull qwen3:0.6b` | RFC |
| 2 | **Qwen3-8B** (q4) | Мозг Bob (reasoning) | Ollama | ~6.5 GB | `ollama pull qwen3:8b` | RFC |
| 3 | **Qwen3-TTS-0.6B** | TTS (голос Bob) | mlx-audio | ~1.5 GB | `pip install "mlx-audio>=0.1"` | RFC |
| 4 | **Whisper Large-v3-Turbo** | STT (слух Bob) | mlx-audio | ~3.0 GB | (то же — mlx-audio) | RFC |
| 5 | **Qwen3Guard-Gen-0.6B** (q4) | ContentGuard | Ollama | ~0.9 GB | `ollama pull sileader/qwen3guard:0.6b` | Обновлено (замена LlamaGuard) |
| 6 | **nomic-embed-text** | SemanticMemory embeddings | Ollama | ~0.3 GB | `ollama pull nomic-embed-text` | Обновлено (замена MiniLM) |
| 7 | **YOLO11n** | Зрение Bob (камера с гимбалом) + валидация спрайтов | ultralytics | ~0.3 GB | `pip install ultralytics` | Валидирован (D-020) |
| 8 | **FLUX.2 Klein 4B** (q4) | Генерация "мира" Боба, самого Боба | mflux | ~2.0 GB | `uv tool install mflux --with tiktoken --with protobuf --with sentencepiece` | Валидирован (D-004) |
| 9 | **FLUX.1 Kontext dev** (q4) | Айдентика и стабильность "мира" и Боба, одежда, Боб в сцене, элементы окружения | mflux | ~6.0 GB | (то же — mflux, модель: `akx/FLUX.1-Kontext-dev-mflux-4bit`) | Валидирован (этот PoC) |
| 10 | ~~**Depth Anything V2** (Small)~~ | ~~Карта глубины → parallax слои~~ | ~~HF Transformers + MPS~~ | ~~~0.4 GB~~ | ~~`pip install transformers torch`~~ | Валидирован (D-017), исключён (D-019: 2.5D parallax отклонён) |
| 11 | **InsightFace ArcFace** (buffalo_l) | Валидация идентичности Bob — 512-d face embeddings | onnxruntime | ~0.5 GB | `pip install insightface onnxruntime` | Валидирован (D-020) |
| 12 | **DINOv2-base** (Meta) | Fine-grained face crop similarity (cartoon identity) | HF Transformers + MPS | ~0.33 GB | `pip install transformers torch` (модель: `facebook/dinov2-base`) | Валидирован (D-020) |
| 13 | **CLIP ViT-L-14** (OpenAI) | Стилистическая консистентность (Vault-Tec aesthetic) | open-clip-torch | ~0.9 GB | `pip install open-clip-torch` | Валидирован (D-020) |
| 14 | **Claude Code CLI** (Opus 4.6) | Буст IQ, рефлексия, самоулучшение, разработка, мультиагентный режим | Claude Code CLI (локально на Mac Mini M4) | ~1.0-3.0 GB | `npm install -g @anthropic-ai/claude-code` | Используется |

#### Профиль: VALIDATION (валидация спрайтов Bob, D-020)

| Модель | Назначение | RAM |
|--------|-----------|-----|
| YOLO11n | Person detection + bbox | ~0.3 GB |
| InsightFace ArcFace (buffalo_l) | Face identity (512-d embeddings) | ~0.5 GB |
| DINOv2-base | Face crop similarity (fine-grained) | ~0.33 GB |
| CLIP ViT-L-14 | Style consistency | ~0.9 GB |
| **Итого** | | **~2.0 GB** |

### История обновлений стека

| Было (RFC) | Стало | Причина |
|-----------|-------|---------|
| Qwen2.5-0.5B | **Qwen3-0.6B** | Апгрейд поколения, thinking mode |
| Qwen2.5-7B-Q4 | **Qwen3-8B** | Апгрейд поколения, Qwen3-4B ≈ Qwen2.5-72B |
| Llama Guard 3-1B-INT4 | **Qwen3Guard-Gen-0.6B** | Компактнее (484 vs 923 MB), 119 языков, Apache 2.0, tri-class |
| all-MiniLM-L6-v2 | **nomic-embed-text** | Устарел (2021), 512→8K контекст, значительно лучше качество |
| YOLOv8 | **YOLO11n** | Быстрее, точнее; YOLO26n пока не стабилен в ultralytics |
| Stable Diffusion | **FLUX.2 + Kontext + Depth Anything V2** | mflux не поддерживает SD; FLUX.2 качественнее |
| Kokoro TTS | **Qwen3-TTS-0.6B + Whisper** (через mlx-audio) | Единый пакет STT+TTS, нативный Apple Silicon |
| face_recognition (dlib, 128-d) | **InsightFace ArcFace** (512-d) | 4x больше embedding, кардинально лучше на cartoon faces |
| CLIP ViT-B-32 (face crop) | **DINOv2-base** | 70% vs 15% на fine-grained visual tasks |
| CLIP ViT-B-32 (style) | **CLIP ViT-L-14** | 3x больше модель, +12% accuracy |

### Зависимости (pip / uv)

| Пакет | Команда установки | Назначение |
|-------|-------------------|-----------|
| mflux | `uv tool install mflux --with tiktoken --with protobuf --with sentencepiece` | FLUX.2 + Kontext |
| mlx-audio | `pip install "mlx-audio>=0.1"` | TTS (Qwen3-TTS) + STT (Whisper) |
| ultralytics | `pip install ultralytics` | YOLO11n (зрение Bob + валидация) |
| transformers + torch | `pip install transformers torch` | Depth Anything V2 + DINOv2 (MPS на Apple Silicon) |
| insightface + onnxruntime | `pip install insightface onnxruntime` | ArcFace face identity (D-020) |
| open-clip-torch | `pip install open-clip-torch` | CLIP ViT-L-14 style consistency (D-020) |
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

### 5.3 Depth Anything V2 — ВАЛИДИРОВАН

| Параметр | Результат |
|----------|----------|
| Модель | `depth-anything/Depth-Anything-V2-Small-hf` (24.8M params) |
| Runtime | HuggingFace Transformers + PyTorch MPS |
| Установка | `uv run --with torch --with transformers ...` |
| Устройство | MPS (Metal Performance Shaders) на M1 Max |
| Загрузка модели | 53.2s (первый запуск; далее из кэша ~2-5s) |
| **Inference** | **2.525s** на 1024x768 |
| RAM | ~300-500 MB |
| Вход | `bob-preview/bob_bunker_reading.png` (1024x768) |
| Выход | depth map + 4 parallax-слоя с прозрачностью |

**Качество карты глубины:**
- Чёткое разделение Bob (передний план) от фона (стена, постер)
- Средний план (стеллаж, лампа, столик) корректно определён
- Книга в руках Bob и подлокотник кресла — ближайший план
- Depth range: нормализован 0.0–1.0, распределение: P10=0.049, P50=0.168, P90=0.341

**Качество слоёв (4 слоя по квантилям глубины):**
- Layer 0 (far): стена, постер — корректно
- Layer 1 (mid): стеллаж, лампа, столик, радио — корректно
- Layer 2 (near): Bob (верхняя часть), кресло — корректно
- Layer 3 (fg): руки+книга, ноги, подлокотник, пол — корректно

**Артефакты / замечания:**
- Границы слоёв имеют небольшие зазубрины (edge feathering помогает, но не идеально)
- Распределение по квантилям (25% пикселей на слой) — простое, но рабочее
- Для production можно настроить пороги вручную под конкретную сцену

**Скрипт валидации:** `validate_depth.py`
**Выходные файлы:** `depth-validation/` (depth_map.png + 4 layer PNG)

**Альтернативные варианты (исследованы, не тестировались):**
- CoreML (Apple official): Small only, ~25ms — для production deployment
- ONNX + CoreML EP: все размеры, Neural Engine
- MLX: порт не существует

**Вывод:** Depth Anything V2 Small через HF Transformers + MPS полностью работает
на Apple Silicon. 2.5s inference + ~0.4 GB RAM — вписывается в профиль DEPTH.
Для production рассмотреть CoreML (~25ms).

### 5.4 Kontext inset-method — ВАЛИДИРОВАН

**Открытие сессии:** Kontext принимает только 1 изображение, но если вклеить
Bob-reference (192x256) в угол сцены (1024x768), Kontext понимает задачу
"поместить персонажа в сцену" и удаляет вставку-референс.

| Параметр | Результат |
|----------|----------|
| Метод | Bob-ref 192x256 в top-left угол сцены 1024x768 |
| Выход | 1024x768, полное разрешение (не нужно обрезать) |
| Identity | Сохранена: блондин, бородка, голубой комбинезон, стиль Vault Boy |
| Время | 8 мин (Kontext q4, 24 steps) |
| Сравнение с side-by-side | Лучше: полное разрешение vs 512x768, лучше identity |

**Файлы:** `bob-preview/bob_inset_test.png`, `bob-preview/bob_inset_sprite.png`

### 5.5 rembg sprite extraction — ВАЛИДИРОВАН

| Параметр | Результат |
|----------|----------|
| Модель | `isnet-anime` (176 MB, автоскачивание) |
| Время | <5 сек |
| Качество | Чистая вырезка Bob + кресло, прозрачный фон |
| Артефакты | Небольшие на краях (полупрозрачные пиксели) |

### 5.6 Godot 2D сцена + camera breathing — ВАЛИДИРОВАН

| Компонент | Статус |
|-----------|--------|
| Runtime PNG загрузка | OK |
| Camera2D breathing | OK (двойная синусоида) |
| Sprite масштабирование | OK (auto-fit viewport + 10% margin) |
| Визуальное качество | OK (целостная картинка, живая атмосфера) |

**Файлы:** `godot/scripts/parallax_scene.gd`, `godot/scenes/parallax_2d.tscn`

### 5.7 2.5D Parallax — ОТКЛОНЁН (D-019)

Все варианты разделения Bob от фона дают артефакты:
- Depth-split с Bob → Bob разъезжается между слоями
- Cutout Bob из фона → чёрные дыры при смещении
- Blur-inpaint → ghost blob
- Два слоя (0.97 / 1.0) → двоение Bob через rembg-артефакты

**Вывод:** 2.5D parallax невозможен без quality AI inpainting фона за Bob.
Отклонён в пользу 2D point-and-click подхода (D-019).

### 5.8 Итоговая архитектура — 2D Point-and-Click (D-019)

**Вместо 2.5D parallax → 2D adventure game стиль (Monkey Island / Broken Sword):**

```
Фон (FLUX.2, wide shot, без Bob):
┌───────────────────────────────────────────┐
│  [шкаф]      [стена, постеры]     [стол]  │
│                                           │
│  [книги]         [кресло]        [лампа]  │
│                                           │
│  ─────────────── пол ─────────────────    │
└───────────────────────────────────────────┘

Bob (отдельные спрайты, Kontext + rembg):
🧍 стоит  🚶 идёт  🪑 сидит  📖 читает  🔍 у полки

Godot: фон + Bob-спрайт(позиция, поза) + tween + shader-анимация
```

**Микро-анимация (без новых генераций):**
- Дыхание: Godot shader — sine-деформация грудной клетки
- Моргание: 2 спрайта (глаза открыты/закрыты), swap каждые 3-5 сек
- Микро-движения головы: tween на участке спрайта

**Макро-анимация (pre-generated sprites):**
- Набор поз: стоит, сидит, идёт, читает, тянется к полке (~6-8 штук)
- Генерация: batch ночью (~8 мин × 8 = 64 мин)
- Godot: crossfade между позами + tween-движение по сцене

**Целевой сценарий PoC:**
сидит читает → встал → подошёл к шкафу → взял книгу → вернулся → сел → читает

Подробности: DecisionLog.md, D-019

---

## 6. Открытые вопросы

### Q1: Анимация Bob — РЕШЕНО (D-019)

Два уровня:
- **Микро:** shader breathing + sprite-swap blink + tween head — без генерации
- **Макро:** pre-generated pose sprites + Godot crossfade/tween — batch ночью

### Q2: Вырезка Bob — РЕШЕНО

`rembg` с `isnet-anime` — чисто вырезает cartoon-спрайт за <5 сек.

### Q3: Сколько поз для PoC? — 6-8

1. Сидит читает (есть)
2. Стоит idle
3. Идёт влево
4. Идёт вправо
5. Стоит у шкафа (рассматривает)
6. Тянется к полке
7. Глаза закрыты (для blink, 1-2 варианта)

### Q4: Параллакс — ОТКЛОНЁН

2.5D parallax не работает с AI-спрайтами (артефакты разделения).
Используем 2D + camera breathing + shader micro-animation.

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
