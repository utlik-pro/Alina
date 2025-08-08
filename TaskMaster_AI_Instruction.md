# Инструкция: Как уменьшить ошибки AI-кодинга с помощью TaskMaster AI

## Обзор

Эта инструкция поможет вам настроить эффективную систему разработки с использованием AI, которая значительно сократит количество ошибок и повысит качество кода. В основе подхода лежит использование MCP сервера TaskMaster AI для управления задачами.

## Что вы изучите

1. Написание детальных требований
2. Создание PRD файла (Product Requirements Document)
3. Настройка системы управления задачами через MCP
4. Процесс кодирования приложения с использованием задач
5. Решение сложных багов через систему задач

## Шаг 1: Написание требований

**Время:** 10-15 минут

Потратьте время на детальное описание вашего приложения. Включите:

- **Название приложения**
- **Технологический стек**
- **Основные функции**
- **База данных**
- **API интеграции**
- **Стиль дизайна**
- **Что НЕ нужно строить**
- **Исследование аналогичных приложений** (если применимо)

### Пример промпта для ChatGPT:

```markdown
I would like to create concise functional requirements for the following application:

[Ваше подробное описание приложения]

Output as markdown code.
```

### Пример детального описания:

```markdown
The app is called MyApp and is a [описание аналога].
Research [аналог] to get a better understanding of the app.

My Requirements:
- It should integrate with [API]. The model used is [модель]
- The app should have a unified interface with [описание интерфейса]
- The interface should be responsive: [детали адаптивности]
- There should be filters with the ability to filter by:
  - [критерий 1]
  - [критерий 2]
  - [критерий 3]
- User should be able to [основная функция]
- There should be a details view which shows:
  - [деталь 1]
  - [деталь 2]
  - [деталь 3]
- Each item can have the following options:
  - [опция 1]: [варианты]
  - [опция 2]: [варианты]
- Data should be stored [где и как]
- There is already a codebase using [технологии].

Output as markdown code.
```

### Готовый пример:

```
I would like to create concise functional requirements for the following application:

The app is called ImgxAI and is a midjourney clone, but using OpenAI's image model.
Research midjourney to get a better understanding of the app.

My Requirements:
- It should integrate with the OpenAI APIs. The image model used is gpt-image-1
- The app should have a unified interface with a chat input and a timeline of results
- The timeline should be scrollable and have infinite loading with pagination
- The timeline should be responsive, a grid of 1 on mobile, 2 on tablet and 4 on desktop
- There should be minimal filters on the timeline, with the ability to filter by
  - date
  - status
  - aspect ratio
  - order by newest first or oldest first
- You should be able to download each image by clicking on it
- There should be a details view for the entire prompt which shows:
  - all images for the prompt
  - the jobId
  - created
  - status
  - image count
  - dimensions
  - model
  - quality
  - allow to easily re-run the prompt and download each of the images
- The images should be shown in their correct aspect ratio but within a square container
- You are able to submit the prompt multiple times; more items will be added to the timeline (as background jobs)
- Each prompt can have the following options:
  - quality: (low, mid, high)
  - aspect ratio: 1024x1024, 1536x1024, 1024x1536
  - output_compression ((0-100%)) - default is 50%
  - output_format should be webp
  - moderation should be "low"
  - n (number of images to generate)
  - response_format should be b64_json
  - model should be "gpt-image-1"
- You should be able to see a previous prompt and easily rerun it by clicking on it
- The response images should be stored locally in the browser storage
- You should have a simple navigation bar with a settings button
- In the settings menu you can set your OpenAI API key which is also stored locally in the browser storage
- There is already a codebase using Next.js 15, TailwindCSS, Lucide Icons, React Hook Form with zod and Shadcn UI.

Output as markdown code.
```

```markdown
# ImgxAI – Concise Functional Requirements

## 1. Core Integration
- **Image Model:** Use OpenAI `gpt-image-1`.
- **API Calls:** Leverage OpenAI Images API with parameters listed in §4.
- **Moderation:** Always submit prompts with `moderation="low"`.

## 2. User Interface
| Area | Requirement |
|------|-------------|
| **Layout** | Unified interface combining a *Chat-style input* (bottom-fixed) and a *Timeline* of results (scrollable grid). |
| **Timeline Grid** | Responsive: 1 col @ mobile (<640 px), 2 cols @ tablet (≥640 px), 4 cols @ desktop (≥1024 px). |
| **Infinite Scroll** | Paginated fetch; auto-load older pages when the user nears bottom. |
| **Filters** | Date range, Status, Aspect Ratio, and Order (Newest ⇆ Oldest). Minimal UI (dropdown / pills). |
| **Image Tiles** | Images display in original aspect ratio inside square thumbnails; click = open **Details View** + download. |
| **Details View** | Shows: full prompt, all images from that prompt, `jobId`, `created`, `status`, image count, dimensions, model, quality. Buttons: **Re-run Prompt**, **Download per image**. |
| **Navigation** | Top bar with app title and *Settings* button (opens modal). |

## 3. Prompt Lifecycle
1. User enters prompt + optional options (see §4).
2. Background job calls OpenAI; placeholder card appears immediately.
3. On completion, card updates with images (stored in browser storage).
4. User may click **Re-Run** on any previous prompt → new job appended to timeline.

## 4. Prompt Options (sent to OpenAI)
| Field | Values / Default |
|-------|------------------|
| `quality` | `"low" | "mid" | "high"` |
| `aspect_ratio` | `"1024x1024" | "1536x1024" | "1024x1536"` |
| `output_compression` | `0–100`, default `50` |
| `output_format` | `"webp"` *(always)* |
| `moderation` | `"low"` *(always)* |
| `n` | Integer ≥1 |
| `response_format` | `"b64_json"` |
| `model` | `"gpt-image-1"` |

## 5. Storage
- **Local Browser Storage**
  - OpenAI API key (from Settings).
  - Generated images (Base-64) & prompt metadata for offline access.
- **Persistence Strategy**
  - Use IndexedDB via a thin wrapper; key by `jobId`.

## 6. Downloading
- Clicking a tile or image in Details triggers client-side `download` of the WebP (respecting `output_compression`).

## 7. Existing Tech Stack Alignment
- **Framework:** Next.js 15 (App Router, React Server Components where appropriate).
- **Styling:** TailwindCSS + Shadcn UI components; Lucide icons for actions.
- **Forms:** React Hook Form + Zod validation for prompt options & settings.
- **State:** React Query or SWR for API calls and cache; Context/Store for global settings.

## 8. Non-Functional
- **Performance:** Lazy-load thumbnails; compress to ≤500 kB each in storage.
- **Accessibility:** Keyboard-navigable timeline, `alt` text from prompt.
- **Responsiveness:** Must operate smoothly on touch devices and desktop.
- **Error Handling:** Clear banner for API/key errors; retry option on failed jobs.
```

## Шаг 2: Создание PRD файла

### 2.1 Генерация PRD
1. Возьмите ваши требования из Шага 1
2. Используйте ChatGPT (рекомендуется o3 или лучше) для создания структурированного PRD
3. Сохраните результат как markdown файл

### 2.2 Создание структуры проекта
1. Создайте папку `.taskmaster/docs/` в корне проекта
2. Сохраните PRD как `prd.txt` в этой папке

### Пример структуры PRD:

```markdown
# [Название приложения] – Concise Functional Requirements

## 1. Core Integration
- **API:** Use [API название] with [параметры].
- **Authentication:** [детали аутентификации].

## 2. User Interface
| Area | Requirement |
|------|-------------|
| **Layout** | [описание макета] |
| **Grid** | Responsive: [детали сетки] |
| **Navigation** | [описание навигации] |

## 3. Core Features
1. [Функция 1]: [описание]
2. [Функция 2]: [описание]
3. [Функция 3]: [описание]

## 4. Data Management
- **Storage:** [где хранить данные]
- **API calls:** [как работать с API]

## 5. Technical Requirements
- **Framework:** [фреймворк]
- **Styling:** [CSS фреймворк]
- **Icons:** [библиотека иконок]
- **Forms:** [библиотека форм]
```

### Пример готового PDR файла:

```
You are an expert technical product manager specializing in feature development and creating comprehensive product requirements documents (PRDs). Your task is to generate a detailed and well-structured PRD based on the following instructions:

<prd_instructions>
{{PRD_INSTRUCTIONS}}
</prd_instructions>

Follow these steps to create the PRD:

1. Begin with a brief overview explaining the project and the purpose of the document.

2. Use sentence case for all headings except for the title of the document, which should be in title case.

3. Organize your PRD into the following sections:
   a. Introduction
   b. Product Overview
   c. Goals and Objectives
   d. Target Audience
   e. Features and Requirements
   f. User Stories and Acceptance Criteria
   g. Technical Requirements / Stack
   h. Design and User Interface

4. For each section, provide detailed and relevant information based on the PRD instructions. Ensure that you:
   - Use clear and concise language
   - Provide specific details and metrics where required
   - Maintain consistency throughout the document
   - Address all points mentioned in each section

5. When creating user stories and acceptance criteria:
   - List ALL necessary user stories including primary, alternative, and edge-case scenarios
   - Assign a unique requirement ID (e.g., ST-101) to each user story for direct traceability
   - Include at least one user story specifically for secure access or authentication if the application requires user identification
   - Include at least one user story specifically for Database modelling if the application requires a database
   - Ensure no potential user interaction is omitted
   - Make sure each user story is testable

6. Format your PRD professionally:
   - Use consistent styles
   - Include numbered sections and subsections
   - Use bullet points and tables where appropriate to improve readability
   - Ensure proper spacing and alignment throughout the document

7. Review your PRD to ensure all aspects of the project are covered comprehensively and that there are no contradictions or ambiguities.

Present your final PRD within <PRD> tags. Begin with the title of the document in title case, followed by each section with its corresponding content. Use appropriate subheadings within each section as needed.

Remember to tailor the content to the specific project described in the PRD instructions, providing detailed and relevant information for each section based on the given context.
'''

Очевидно, не забудьте заменить {{PRD_INSTRUCTIONS}} на выходную разметку из предыдущего шага.

Это сделано для Claude, но должно работать и с другими LLM (я не проверял).

Выходные данные будут выглядеть следующим образом:
```

```markdown
# ImgxAI - Product Requirements Document

## 1. Introduction

This document outlines the comprehensive product requirements for ImgxAI, a web application that enables users to generate images through OpenAI's image generation API. The PRD serves as a reference for the development team, providing detailed specifications for features, user interface, technical requirements, and design guidelines to ensure consistent implementation of the product vision.

## 2. Product overview

ImgxAI is a user-friendly web application that allows users to create AI-generated images by submitting text prompts to OpenAI's image generation API. The application provides a simple, intuitive interface where users can enter prompts, customize generation parameters, view their generation history in a timeline format, and download the resulting images. ImgxAI emphasizes ease of use, performance, and accessibility while maintaining a minimalist design aesthetic.

## 3. Goals and objectives

### 3.1 Primary goals
- Create a streamlined interface for generating images using OpenAI's `gpt-image-1` model
- Provide users with a persistent timeline of their image generation history
- Enable customization of image parameters while maintaining simplicity
- Ensure responsive performance across all device types
- Deliver a minimalist, accessible user experience

## 4. Target audience

### 4.1 Primary users
- Creative professionals seeking inspiration or assets
- Designers exploring visual concepts
- Content creators needing custom imagery
- Hobbyists experimenting with AI image generation
- Anyone with an OpenAI API key interested in creating images

### 4.2 User needs
- Simple, intuitive interface for prompt submission
- Quick access to previously generated images
- Ability to customize image parameters
- Offline access to previous generations
- Easy downloading of generated images

## 5. Features and requirements

### 5.1 Core integration

| Requirement ID | Requirement | Description | Priority |
|----------------|-------------|-------------|----------|
| CI-101 | Image model integration | Implement integration with OpenAI `gpt-image-1` model | High |
| CI-102 | API call implementation | Configure the application to make calls to OpenAI Images API | High |
| CI-103 | Default moderation | Ensure all prompt submissions include `moderation="low"` parameter | High |

### 5.2 User interface

| Requirement ID | Requirement | Description | Priority |
|----------------|-------------|-------------|----------|
| UI-101 | Unified layout | Implement single-page interface with fixed bottom chat input and scrollable timeline grid | High |
| UI-102 | Responsive timeline grid | Create responsive grid layout: 1 column (mobile), 2 columns (tablet), 4 columns (desktop) | High |
| UI-103 | Infinite scroll | Implement pagination with automatic loading of older results when approaching bottom of scroll | Medium |
| UI-104 | Timeline filters | Add filters for date range, status, aspect ratio, and sort order (newest/oldest) with minimal UI | Medium |
| UI-105 | Image tile display | Show images in original aspect ratio within square thumbnails, with click action to open details view | High |
| UI-106 | Details view | Create modal showing full prompt, all related images, metadata, re-run button, and download options | High |
| UI-107 | Navigation | Implement top bar with app title and settings button | Medium |

### 5.3 Prompt lifecycle

| Requirement ID | Requirement | Description | Priority |
|----------------|-------------|-------------|----------|
| PL-101 | Prompt submission | Allow users to enter text prompts with optional parameters | High |
| PL-102 | Job processing | Process submissions as background jobs with immediate placeholder display | High |
| PL-103 | Result display | Update placeholder with actual images upon job completion | High |
| PL-104 | Re-run capability | Enable users to re-run any previous prompt as a new job | Medium |

### 5.4 Prompt options

| Requirement ID | Requirement | Description | Priority |
|----------------|-------------|-------------|----------|
| PO-101 | Quality selection | Allow selection between "low", "mid", and "high" quality | High |
| PO-102 | Aspect ratio selection | Provide options for "1024x1024", "1536x1024", and "1024x1536" aspect ratios | High |
| PO-103 | Output compression | Enable compression setting between 0-100 with default of 50 | Medium |
| PO-104 | Fixed parameters | Set fixed values for output_format ("webp"), moderation ("low"), response_format ("b64_json"), and model ("gpt-image-1") | High |
| PO-105 | Image count | Allow user to specify number of images to generate (n ≥ 1) | Medium |

### 5.5 Storage

| Requirement ID | Requirement | Description | Priority |
|----------------|-------------|-------------|----------|
| ST-101 | API key storage | Securely store OpenAI API key in browser local storage | High |
| ST-102 | Image storage | Store generated images as Base-64 strings with prompt metadata | High |
| ST-103 | IndexedDB implementation | Use IndexedDB via wrapper for persistent storage, keyed by jobId | High |
| ST-104 | Offline access | Enable access to previously generated images when offline | Medium |

### 5.6 Downloading

| Requirement ID | Requirement | Description | Priority |
|----------------|-------------|-------------|----------|
| DL-101 | Client-side download | Implement client-side download functionality for WebP images | High |
| DL-102 | Compression respect | Apply the specified output_compression setting to downloaded images | Medium |

## 6. User stories and acceptance criteria

### 6.1 User setup and configuration

**ST-101: First-time setup**
- As a new user, I want to set up my API key so I can start generating images
- **Acceptance Criteria:**
  - Settings modal includes field for OpenAI API key entry
  - API key is securely stored in browser storage
  - Validation confirms API key is in correct format
  - User receives confirmation when key is saved successfully

**ST-102: Updating settings**
- As a user, I want to update my API key and preferences when needed
- **Acceptance Criteria:**
  - Settings modal is accessible from the top navigation bar
  - Previously saved API key is displayed (masked) for review
  - Changes are saved only when explicitly submitted
  - User receives confirmation when settings are updated

### 6.2 Image generation

**IG-101: Basic prompt submission**
- As a user, I want to enter a text prompt to generate an image
- **Acceptance Criteria:**
  - Input field is prominently displayed at bottom of screen
  - Submit button or enter key triggers generation
  - Visual indication shows generation is in progress
  - Generated images appear in the timeline upon completion

**IG-102: Advanced parameter configuration**
- As a user, I want to customize image generation parameters
- **Acceptance Criteria:**
  - Options for quality, aspect ratio, compression, and count are available
  - UI clearly indicates current selection and default values
  - Parameter changes persist during the current session
  - Selected parameters are correctly sent with API requests

**IG-103: Error handling**
- As a user, I want to know when an error occurs during generation
- **Acceptance Criteria:**
  - Error messages are clearly displayed when API calls fail
  - Different error types (authentication, content policy, server error) show appropriate messages
  - Options to retry failed jobs are provided
  - Helpful troubleshooting suggestions are included with errors

### 6.3 Timeline and history

**TL-101: Viewing generation history**
- As a user, I want to see all my previously generated images in a timeline
- **Acceptance Criteria:**
  - Timeline displays all past generations in a grid layout
  - Grid is responsive according to device size specifications
  - Images load efficiently with lazy loading implementation
  - Timeline maintains position when returning from detail view

**TL-102: Filtering and sorting**
- As a user, I want to filter and sort my image history
- **Acceptance Criteria:**
  - Filter options for date range, status, and aspect ratio are provided
  - Sort controls allow toggling between newest and oldest first
  - Filtered view updates immediately when selections change
  - Current filter/sort state is visually indicated

**TL-103: Infinite scrolling**
- As a user, I want to seamlessly browse my entire generation history
- **Acceptance Criteria:**
  - Additional history items load automatically when scrolling near bottom
  - Loading indicator appears during pagination fetches
  - Scroll position is maintained when new items load
  - Performance remains smooth even with large history

### 6.4 Image interaction

**II-101: Viewing image details**
- As a user, I want to view detailed information about a generated image
- **Acceptance Criteria:**
  - Clicking an image opens a detail view
  - Detail view shows full prompt text, all related images, and metadata
  - Information includes jobId, creation time, status, dimensions, and other parameters
  - Navigation controls allow browsing between images from the same prompt

**II-102: Downloading images**
- As a user, I want to download generated images to my device
- **Acceptance Criteria:**
  - Download button is available for each image in detail view
  - Downloaded images maintain proper quality based on compression setting
  - Files download in WebP format with appropriate naming
  - Download works on all supported devices and browsers

**II-103: Re-running prompts**
- As a user, I want to re-run previous prompts to get new variations
- **Acceptance Criteria:**
  - Re-run button is available in the detail view
  - Re-running uses the exact same parameters as the original generation
  - New job appears as a separate entry in the timeline
  - Visual indication distinguishes between original and re-run jobs

### 6.5 Edge cases

**EC-101: Offline usage**
- As a user, I want to access my previously generated images when offline
- **Acceptance Criteria:**
  - Previously generated images are viewable when offline
  - Clear indication shows that new generations aren't possible offline
  - Application gracefully handles transition between online and offline states
  - Queued actions are processed when connection is restored

**EC-102: Storage limitations**
- As a user, I want to be able to clear my storage on the settings page

## 7. Technical requirements

### 7.1 Technology stack

The technology stack is already set up, so the requirements below are complete, but use them as a reference to implement the features.

| Requirement ID | Requirement | Description |
|----------------|-------------|-------------|
| TS-101 | Language | Implement using TypeScript for type safety and better developer experience |
| TS-102 | Framework | Use Next.js 15 with App Router and React Server Components where appropriate |
| TS-103 | Styling | Implement styling with TailwindCSS and Shadcn UI components; use Lucide icons for actions |
| TS-104 | Forms | Implement forms with React Hook Form and Zod validation |
| TS-105 | State management | Use React Query or SWR for API calls and caching; implement Context/Store for global settings |

### 7.2 API integration

| Requirement ID | Requirement | Description |
|----------------|-------------|-------------|
| API-101 | OpenAI client | Implement secure client for OpenAI's Images API |
| API-102 | Parameter mapping | Correctly map UI parameters to API request parameters |
| API-103 | Error handling | Implement comprehensive error handling for API responses |
| API-104 | Rate limiting | Add support for managing API rate limits, including user feedback |

### 7.3 Storage implementation

| Requirement ID | Requirement | Description |
|----------------|-------------|-------------|
| SI-101 | IndexedDB wrapper | Implement thin wrapper around IndexedDB for easier data access |
| SI-102 | Data schema | Define schema for storing jobs, images, and metadata |
| SI-103 | Query optimization | Optimize queries for timeline display and filtering |
| SI-104 | Data migration | Support schema migrations for future updates |

### 7.4 Performance requirements

| Requirement ID | Requirement | Description |
|----------------|-------------|-------------|
| PR-101 | Image optimization | Implement lazy loading and appropriate compression for timeline images |

## 8. Design and user interface

### 8.1 Visual design principles

- Minimalist interface focusing on content rather than chrome
- Consistent spacing and sizing throughout the application
- Clean typography with clear hierarchy
- Support for both light and dark modes via TailwindCSS
- High contrast ratio for accessibility
- Visual feedback for all user interactions

### 8.2 User interface components

#### 8.2.1 Main layout
- Single-page application with fixed navigation bar at top
- Chat-style input fixed at bottom of screen
- Scrollable timeline grid occupying main content area
- Modal overlays for details view and settings

#### 8.2.2 Timeline grid
- Responsive grid layout based on device size
- Each cell displays image thumbnail with minimal metadata
- Visual indication of job status (pending, completed, failed)
- Consistent padding and spacing between items

#### 8.2.3 Input area
- Prominent text input for prompt entry
- Expandable panel for additional parameters
- Submit button with appropriate loading states
- Error feedback displayed inline

#### 8.2.4 Details view
- Full-screen modal with close button
- Large image display with navigation between related images
- Complete metadata panel
- Action buttons for download and re-run

### 8.3 Accessibility requirements

- WCAG 2.1 AA compliance for all interface elements
- Keyboard navigation throughout the application
- Screen reader compatibility for all functionality
- Appropriate alt text derived from prompts
- Focus indicators for keyboard navigation

### 8.4 Responsive design specifications

| Breakpoint | Grid columns | UI adjustments |
|------------|--------------|----------------|
| Small (< sm) | 1 column | Simplified options UI, vertical layout |
| Medium (sm - lg) | 2 columns | Compact metadata display, horizontal options |
| Large (> lg) | 4 columns | Full feature display, expanded details view |

### 8.5 Error states and feedback

- Clear error banners for API and authentication issues
- Inline validation for form inputs
- Loading indicators for in-progress actions
- Success confirmations for completed operations
- Helpful guidance for resolving common issues
```


## Шаг 3: Настройка TaskMaster AI MCP

### 3.1 Установка MCP сервера
TaskMaster AI должен быть установлен в вашем редакторе (Cursor).

### 3.2 Инициализация проекта
1. Откройте ваш проект в редакторе
2. Инициализируйте TaskMaster AI:

```markdown
Initialize taskmaster project in this directory
```

**Результат:** Система создаст необходимые папки и конфигурационные файлы.

### 3.3 Парсинг PRD в задачи
```markdown
Parse PRD file and generate initial tasks
```

**Результат:** Система создаст структурированный список задач на основе вашего PRD.

## Шаг 4: Процесс разработки приложения

### 4.1 Базовый цикл разработки

1. **Просмотр задач:**
```markdown
Show tasks
```

2. **Определение следующей задачи:**
```markdown
What's the next task I should work on? Please consider dependencies and priorities.
```

3. **Реализация задачи:**
```markdown
Implement task [номер] and all of its subtasks.
```

4. **Итерация:**
   - Протестируйте UI/функциональность
   - Если все работает хорошо, создайте новый чат
   - Повторите цикл

### 4.2 Работа с подзадачами
Для сложных задач реализуйте только отдельные подзадачи:
```markdown
Implement subtask [номер.подномер]
```

### 4.3 Дополнительные команды управления задачами

```markdown
# Просмотр конкретной задачи
Get task [номер]

# Обновление статуса задачи
Set task [номер] status to [статус]

# Добавление новой задачи
Add task: [описание задачи]

# Просмотр следующей задачи
Next task

# Анализ сложности проекта
Analyze project complexity
```

## Лучшие практики

### 1. Контекст для каждой задачи
При запуске задачи предоставляйте дополнительный контекст:
- Предпочтения UI
- Документация API
- Изображения (если нужно)
- Специфические требования

**Пример:**
```markdown
Implement task 3 and all of its subtasks.

Additional context:
- Use modern, clean design similar to [пример]
- Follow the API documentation attached
- Make sure the interface is fully responsive
- Use loading states for async operations
```

### 2. Разбивайте большие файлы
Если файл превышает 500 строк, разбейте его:
```markdown
Break down this file into logical modules so it's easier to read.
Create directories if needed and move utils and interfaces to separate files, maintaining a domain-driven file structure.
```

### 3. Баги как задачи
Для сложных багов создавайте отдельные задачи:
```markdown
The filter feature is not working as expected. Create a new task to fix it:
- the filter should be case insensitive
- it should work with pagination
- it should work with the debounce
- it should maintain state when switching between views
```

### 4. Новый чат для каждой задачи
Всегда начинайте новый чат при реализации следующей задачи, чтобы избежать переизбытка контекста.

### 5. Используйте готовые шаблоны
Всегда начинайте с готового шаблона проекта, а не с нуля:
- Next.js стартеры
- React шаблоны
- Vue.js boilerplates

## Продвинутые возможности

### Управление зависимостями задач
```markdown
# Добавление зависимости
Add dependency: task [номер1] depends on task [номер2]

# Проверка зависимостей
Validate dependencies

# Исправление проблем с зависимостями
Fix dependencies
```

### Работа с тегами
```markdown
# Создание тега для группировки задач
Add tag: [название тега]

# Переключение на другой тег
Use tag: [название тега]

# Просмотр всех тегов
List tags
```

### Исследовательские возможности
```markdown
# Исследование с контекстом проекта
Research: [ваш запрос]

# Сохранение результатов исследования в задачу
Research: [запрос] and save to task [номер]
```

## Решение проблем

### Если реализация задачи идет не так:

1. **Проблема:** Задача слишком расплывчата
   **Решение:** Переформулируйте задачу более конкретно
   ```markdown
   Update task [номер]: [новое детальное описание]
   ```

2. **Проблема:** Переизбыток контекста в чате
   **Решение:** Начните новый чат

3. **Проблема:** AI применяет поверхностные исправления
   **Решение:** Создайте новую задачу для бага с детальным описанием

4. **Проблема:** Задачи выполняются не в том порядке
   **Решение:** Проверьте и исправьте зависимости
   ```markdown
   Validate dependencies
   Fix dependencies
   ```

### Типичные ошибки и их решения:

| Проблема | Причина | Решение |
|----------|---------|---------|
| AI не понимает задачу | Неточное описание | Добавить больше контекста и примеров |
| Задачи конфликтуют | Неправильные зависимости | Пересмотреть порядок выполнения |
| Код получается плохим | Слишком большая задача | Разбить на подзадачи |
| Баги повторяются | Поверхностные исправления | Создать отдельную задачу для архитектурного решения |

## Полезные промпты

### Для анализа проекта:
```markdown
Analyze the current codebase and suggest improvements for:
- Code structure
- Performance
- Best practices
- Security considerations
```

### Для оптимизации задач:
```markdown
Review all pending tasks and suggest:
- Task consolidation opportunities
- Missing dependencies
- Priority adjustments
- Potential architectural issues
```

### Для документации:
```markdown
Generate documentation for the implemented features including:
- API endpoints
- Component usage
- Configuration options
- Deployment instructions
```

## Важные моменты

⚠️ **Реалистичные ожидания:**
- AI может написать 80-90% кода
- Вы всё ещё нужны для тестирования, отладки и направления разработки
- Проверяйте каждую функцию в UI после реализации
- Архитектурные решения требуют вашего участия

✅ **Ключи к успеху:**
- Систематический подход через задачи
- Регулярное тестирование
- Свежие чаты для новых задач
- Детальные описания требований
- Правильное управление зависимостями

🚀 **Продвинутые техники:**
- Используйте теги для разных фич
- Применяйте исследовательские возможности
- Создавайте задачи для рефакторинга
- Документируйте решения в задачах

## Чек-лист успешного проекта

### Подготовка:
- [ ] Детальные требования написаны
- [ ] PRD файл создан и сохранен
- [ ] TaskMaster AI инициализирован
- [ ] Задачи сгенерированы из PRD

### Процесс разработки:
- [ ] Следую циклу: задача → реализация → тестирование → новый чат
- [ ] Разбиваю большие файлы на модули
- [ ] Создаю отдельные задачи для багов
- [ ] Предоставляю достаточный контекст для каждой задачи
- [ ] Проверяю зависимости между задачами

### Контроль качества:
- [ ] Тестирую каждую реализованную функцию
- [ ] Проверяю адаптивность интерфейса
- [ ] Валидирую API интеграции
- [ ] Убеждаюсь в соответствии требованиям

## Заключение

TaskMaster AI обеспечивает структурированный подход к AI-разработке, разбивая сложные проекты на управляемые задачи. Хотя AI не может полностью заменить разработчика, эта система значительно повышает продуктивность и качество кода при правильном использовании.

**Помните:** Успех зависит не только от инструментов, но и от вашего умения правильно их использовать. Системный подход, детальное планирование и постоянное тестирование — ваши главные союзники в AI-разработке.

---

**Источник:** [Оригинальная статья](https://shipixen.com/tutorials/reduce-ai-coding-errors-with-taskmaster-ai)

**Версия инструкции:** 1.0  
**Дата создания:** 2025  
**Язык:** Русский 