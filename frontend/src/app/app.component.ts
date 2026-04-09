import { Component, OnInit, OnDestroy, HostListener } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Subscription } from 'rxjs';
import { GenerationService } from './generation.service';
import { AuthService } from './auth.service';
import {
  Model, GenerationRequest, GenerationVideoRequest, Settings, ComfyConfig,
  ConnectionTestResult, LlmTestResult, GalleryItem, CachedModel, ModelTypeOption,
  InventoryCategory, InventoryItem, Architecture, VideoModel, ModelFavoriteEntry, AppUserRow,
  MissingLoraResult, MissingLoraCandidate, AuthStatus,
} from './types';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <!-- LOADING -->
    <div class="login-container" *ngIf="appState === 'loading'">
      <div class="login-card">
        <div class="login-header">
          <h1 class="login-title">Krita AI</h1>
          <p class="login-subtitle">Studio</p>
        </div>
        <div class="login-loading"><span class="spinner login-spinner"></span></div>
      </div>
    </div>

    <!-- LOGIN -->
    <div class="login-container" *ngIf="appState === 'login'">
      <div class="login-card">
        <div class="login-header">
          <h1 class="login-title">Krita AI</h1>
          <p class="login-subtitle">Studio</p>
        </div>
        <button type="button" class="btn btn-secondary login-ms-btn" *ngIf="oauthAvailable"
                (click)="handleLoginMicrosoft()">
          Continuar con Microsoft
        </button>
        <p class="login-oauth-hint" *ngIf="oauthAvailable && !legacyLogin">
          Inicia sesi&oacute;n con tu cuenta de la organizaci&oacute;n.
        </p>
        <div class="login-divider" *ngIf="oauthAvailable && legacyLogin">
          <span>o credenciales locales</span>
        </div>
        <form *ngIf="legacyLogin" (ngSubmit)="handleLogin()">
          <div class="input-group">
            <label>Usuario</label>
            <input class="input-field" type="text" [(ngModel)]="loginUsername"
                   name="username" placeholder="Usuario" autocomplete="username">
          </div>
          <div class="input-group">
            <label>Contrase&ntilde;a</label>
            <input class="input-field" type="password" [(ngModel)]="loginPassword"
                   name="password" placeholder="Contrase&ntilde;a" autocomplete="current-password">
          </div>
          <button type="submit" class="btn btn-primary"
                  [disabled]="loggingIn || !loginUsername || !loginPassword">
            <span *ngIf="loggingIn" class="spinner"></span>
            {{ loggingIn ? 'Entrando...' : 'Entrar' }}
          </button>
        </form>
        <p class="login-error" *ngIf="loginError">{{ loginError }}</p>
      </div>
      <p class="login-footer">Powered by ComfyUI</p>
    </div>

    <!-- APP -->
    <div class="app-container" [class.has-bottom-nav]="true" *ngIf="appState === 'app'">
      <header class="header">
        <h1>Krita AI</h1>
        <div class="status" [class.online]="comfyOnline" [class.offline]="!comfyOnline">
          <span class="status-indicator"></span>
          <span>{{ comfyOnline ? 'Online' : 'Offline' }}</span>
        </div>
      </header>

      <!-- ============ GENERATE TAB ============ -->
      <ng-container *ngIf="activeTab === 'generate'">
        <div class="card">
          <div class="input-group">
            <div class="prompt-label-row">
              <label>Prompt</label>
              <button
                type="button"
                class="btn btn-secondary btn-compact"
                (click)="handleEnhancePrompt()"
                [disabled]="enhancingPrompt || !prompt.trim()">
                <span *ngIf="enhancingPrompt" class="spinner"></span>
                <span>{{ enhancingPrompt ? 'Mejorando...' : 'Mejorar con IA' }}</span>
              </button>
            </div>
            <textarea
              class="textarea-field"
              [(ngModel)]="prompt"
              placeholder="Describe la imagen o video que quieres generar..."
              rows="3"
              (keydown.meta.enter)="handleGenerate()"
              (keydown.control.enter)="handleGenerate()">
            </textarea>
          </div>

          <!-- Generation Mode Selector -->
          <div class="input-group">
            <label>Modo de generaci\u00f3n</label>
            <div class="mode-selector">
              <button
                class="mode-btn"
                [class.active]="generationMode === 'image'"
                (click)="setGenerationMode('image')">
                \ud83d\uddbc\ufe0f Imagen
              </button>
              <button
                class="mode-btn"
                [class.active]="generationMode === 'video'"
                (click)="setGenerationMode('video')">
                \ud83c\udfa5 Video
              </button>
            </div>
          </div>

          <!-- Image: modelo + resoluci&oacute;n (mismo patr&oacute;n que v&iacute;deo) -->
          <div class="input-group" *ngIf="generationMode === 'image'">
            <label>Modelo</label>
            <select
              class="input-field"
              [(ngModel)]="selectedModel"
              (ngModelChange)="handleMainImageModelSelectChange($event)">
              <ng-container *ngIf="!useFavoriteShortcutsForMainModel(); else mainModelFavOpts">
                <optgroup label="Checkpoints" *ngIf="getModelsByType('checkpoint').length > 0">
                  <option *ngFor="let model of getModelsByType('checkpoint')" [value]="model.name">{{ model.name }}</option>
                </optgroup>
                <optgroup label="Diffusion Models" *ngIf="getModelsByType('diffusion_model').length > 0">
                  <option *ngFor="let model of getModelsByType('diffusion_model')" [value]="model.name">{{ model.name }}</option>
                </optgroup>
                <option *ngIf="models.length === 0" value="">Cargando...</option>
              </ng-container>
              <ng-template #mainModelFavOpts>
                <optgroup label="Favoritos (selector principal)">
                  <option *ngFor="let p of getMainImageModelPickList()" [value]="p.name">{{ p.display }}</option>
                </optgroup>
                <option *ngIf="models.length === 0" value="">Cargando...</option>
              </ng-template>
              <option [value]="modelPickAdvanced" class="opt-advanced-pick" *ngIf="models.length > 0">&#9881; Avanzado&#8230;</option>
            </select>
          </div>

          <div class="input-group" *ngIf="generationMode === 'image'">
            <label>Resoluci&oacute;n</label>
            <div class="resolution-presets">
              <button type="button" class="preset-btn" [class.active]="imageResolutionPreset === '832x480'"
                      (click)="handleImageResolutionPreset('832x480')">832&times;480 <span class="preset-label">Landscape</span></button>
              <button type="button" class="preset-btn" [class.active]="imageResolutionPreset === '480x832'"
                      (click)="handleImageResolutionPreset('480x832')">480&times;832 <span class="preset-label">Portrait</span></button>
              <button type="button" class="preset-btn" [class.active]="imageResolutionPreset === '640x640'"
                      (click)="handleImageResolutionPreset('640x640')">640&times;640 <span class="preset-label">Square</span></button>
              <button type="button" class="preset-btn" [class.active]="imageResolutionPreset === '1280x720'"
                      (click)="handleImageResolutionPreset('1280x720')">1280&times;720 <span class="preset-label">HD</span></button>
            </div>
          </div>

          <!-- Video Settings (only in video mode) -->
          <div class="input-group" *ngIf="generationMode === 'video'">
            <label>Modelo de v&iacute;deo</label>
            <select class="input-field" [(ngModel)]="selectedVideoModel">
              <option value="">Auto (Wan 2.2 14B)</option>
              <option *ngFor="let vm of videoModels" [value]="vm.filename">
                {{ vm.filename }} ({{ vm.architecture_label }})
              </option>
            </select>
          </div>

          <div class="input-group" *ngIf="generationMode === 'video'">
            <label>Resoluci&oacute;n</label>
            <div class="resolution-presets">
              <button class="preset-btn" [class.active]="videoResolutionPreset === '832x480'"
                      (click)="handleVideoResolutionPreset('832x480')">832&times;480 <span class="preset-label">Landscape</span></button>
              <button class="preset-btn" [class.active]="videoResolutionPreset === '480x832'"
                      (click)="handleVideoResolutionPreset('480x832')">480&times;832 <span class="preset-label">Portrait</span></button>
              <button class="preset-btn" [class.active]="videoResolutionPreset === '640x640'"
                      (click)="handleVideoResolutionPreset('640x640')">640&times;640 <span class="preset-label">Square</span></button>
              <button class="preset-btn" [class.active]="videoResolutionPreset === '1280x720'"
                      (click)="handleVideoResolutionPreset('1280x720')">1280&times;720 <span class="preset-label">HD</span></button>
            </div>
          </div>

          <div class="input-group" *ngIf="generationMode === 'video'">
            <label>Duraci&oacute;n: {{ videoLength }} frames</label>
            <div class="slider-container">
              <input type="range" min="21" max="161" step="4" [(ngModel)]="videoLength">
              <span class="slider-value">{{ videoLength }}</span>
            </div>
            <span class="hint">~{{ (videoLength / videoFps).toFixed(1) }}s &#64; {{ videoFps }}fps</span>
          </div>

          <div class="input-group" *ngIf="generationMode === 'video'">
            <label>FPS: {{ videoFps }}</label>
            <div class="slider-container">
              <input type="range" min="1" max="30" step="0.5" [(ngModel)]="videoFps">
              <span class="slider-value">{{ videoFps }}</span>
            </div>
          </div>

          <div class="input-group" *ngIf="generationMode === 'image'">
            <label>Strength: {{ strength }}</label>
            <div class="slider-container">
              <input type="range" min="0.1" max="1" step="0.05" [(ngModel)]="strength">
              <span class="slider-value">{{ strength }}</span>
            </div>
          </div>

          <button
            class="btn btn-primary"
            (click)="handleGenerate()"
            [disabled]="generating || !comfyOnline">
            <span *ngIf="generating" class="spinner"></span>
            <span>{{ generating ? ('Generando... ' + (generationProgress > 0 ? generationProgress + '%' : '')) : (generationMode === 'video' ? 'Generar Video' : 'Generar Imagen') }}</span>
          </button>
          <div class="progress-bar-container" *ngIf="generating && generationProgress > 0">
            <div class="progress-bar-fill" [style.width.%]="generationProgress"></div>
          </div>
        </div>

        <!-- Advanced options -->
        <div class="card advanced-card">
          <button
            class="advanced-toggle"
            (click)="showAdvanced = !showAdvanced"
            [attr.aria-expanded]="showAdvanced"
            tabindex="0">
            <span class="advanced-toggle-icon" [class.open]="showAdvanced">&#9654;</span>
            Opciones avanzadas
          </button>

          <div *ngIf="showAdvanced" class="advanced-body">
            <div class="input-group" *ngIf="generationMode === 'image'">
              <label>Modelo (lista completa)</label>
              <select
                class="input-field"
                [(ngModel)]="selectedModel"
                (ngModelChange)="handleModelChange($event)">
                <optgroup label="Checkpoints" *ngIf="getModelsByType('checkpoint').length > 0">
                  <option *ngFor="let model of getModelsByType('checkpoint')" [value]="model.name">{{ model.name }}</option>
                </optgroup>
                <optgroup label="Diffusion Models" *ngIf="getModelsByType('diffusion_model').length > 0">
                  <option *ngFor="let model of getModelsByType('diffusion_model')" [value]="model.name">{{ model.name }}</option>
                </optgroup>
                <option *ngIf="models.length === 0" value="">Cargando...</option>
              </select>
            </div>

            <div class="input-group">
              <label>Negative Prompt</label>
              <textarea
                class="textarea-field"
                [(ngModel)]="negativePrompt"
                placeholder="Lo que NO quieres en la imagen..."
                rows="2">
              </textarea>
            </div>

            <div class="settings-grid">
              <div class="input-group">
                <label>Sampler</label>
                <select class="select-field" [(ngModel)]="sampler" (ngModelChange)="handleSaveSetting('sampler', $event)">
                  <option value="">Auto</option>
                  <option *ngFor="let s of samplers" [value]="s">{{ s }}</option>
                </select>
              </div>

              <div class="input-group">
                <label>Steps: {{ steps === 0 ? 'Auto' : steps }}</label>
                <div class="slider-container">
                  <input type="range" min="0" max="50" [(ngModel)]="steps" (change)="handleSaveSetting('steps', steps)">
                </div>
              </div>

              <div class="input-group">
                <label>CFG: {{ cfg === 0 ? 'Auto' : cfg }}</label>
                <div class="slider-container">
                  <input type="range" min="0" max="20" step="0.5" [(ngModel)]="cfg" (change)="handleSaveSetting('cfg', cfg)">
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Last result - Images -->
        <div class="card" *ngIf="generatedImages.length > 0">
          <div class="last-result">
            <img
              *ngFor="let img of generatedImages; let i = index"
              [src]="img"
              [alt]="'Generated ' + i"
              class="last-result-img"
              (click)="handleViewLastResult(i)">
          </div>
        </div>

        <!-- Last result - Videos -->
        <div class="card" *ngIf="generatedVideos.length > 0">
          <h3 class="card-subtitle">Video generado</h3>
          <div class="video-results">
            <div *ngFor="let videoId of generatedVideos; let i = index" class="video-container">
              <img
                [src]="getImageUrl(videoId)"
                class="generated-video"
                alt="Video generado">
              <div class="video-actions">
                <a [href]="getImageUrl(videoId)" download class="btn btn-secondary btn-small">
                  Descargar video
                </a>
              </div>
            </div>
          </div>
        </div>
      </ng-container>

      <!-- ============ GALLERY TAB ============ -->
      <ng-container *ngIf="activeTab === 'gallery'">
        <div *ngIf="galleryItems.length === 0 && !galleryLoading" class="empty-gallery">
          <div class="empty-icon">&#128444;</div>
          <p>Sin im&aacute;genes a&uacute;n</p>
          <p class="empty-sub">Las im&aacute;genes generadas aparecer&aacute;n aqu&iacute;</p>
        </div>

        <div *ngIf="galleryLoading && galleryItems.length === 0" class="gallery-loading">
          <span class="spinner"></span>
        </div>

        <div class="gallery-grid" *ngIf="galleryItems.length > 0">
          <div
            class="gallery-thumb"
            *ngFor="let item of galleryItems; let i = index"
            (click)="handleOpenViewer(i)"
            tabindex="0"
            role="button"
            [attr.aria-label]="item.prompt || 'Imagen ' + (i + 1)">
            <img
              [src]="getImageUrl(item.id)"
              [alt]="item.prompt"
              loading="lazy">
            <div class="gallery-thumb-overlay">
              <div class="gallery-badge-row">
                <span class="video-badge" *ngIf="item.type === 'video'">&#9654; Video</span>
              </div>
              <span class="gallery-thumb-time">{{ formatTime(item.created_at) }}</span>
            </div>
          </div>
        </div>

        <button
          *ngIf="galleryItems.length < galleryTotal"
          class="btn btn-secondary load-more-btn"
          (click)="handleLoadMore()"
          [disabled]="galleryLoading">
          {{ galleryLoading ? 'Cargando...' : 'Cargar m\u00e1s' }}
        </button>
      </ng-container>

      <!-- ============ CONFIG TAB ============ -->
      <ng-container *ngIf="activeTab === 'config'">
        <div class="card">
          <h2 class="card-title">Conexi&oacute;n ComfyUI</h2>

          <div class="input-group">
            <label>Host</label>
            <input
              class="input-field"
              type="text"
              [(ngModel)]="configHost"
              placeholder="comfyui.example.com o 192.168.1.100">
          </div>

          <div class="settings-grid">
            <div class="input-group">
              <label>Puerto</label>
              <input
                class="input-field"
                type="text"
                [(ngModel)]="configPort"
                placeholder="8188">
            </div>

            <div class="input-group">
              <label>Protocolo</label>
              <select class="select-field" [(ngModel)]="configSecure">
                <option value="false">HTTP</option>
                <option value="true">HTTPS</option>
              </select>
            </div>
          </div>

          <div class="config-url-preview">
            {{ configSecure === 'true' ? 'https' : 'http' }}://{{ configHost || '...' }}:{{ configPort || '...' }}
          </div>

          <h2 class="card-title" style="margin-top: 8px;">Autenticaci&oacute;n</h2>

          <div class="auth-status" [class.active]="isAuthEnabled" [class.inactive]="!isAuthEnabled">
            <span>{{ isAuthEnabled ? '&#128274; Protegido' : '&#128275; Acceso libre' }}</span>
          </div>

          <p class="auth-hint" *ngIf="!isAuthEnabled">
            Configura usuario y contrase&ntilde;a para proteger el acceso a la app.
          </p>
          <p class="auth-hint" *ngIf="isAuthEnabled">
            Cambia tus credenciales o d&eacute;jalos vac&iacute;os para desactivar.
          </p>

          <div class="settings-grid">
            <div class="input-group">
              <label>Usuario</label>
              <input
                class="input-field"
                type="text"
                [(ngModel)]="authUser"
                placeholder="admin"
                autocomplete="username">
            </div>

            <div class="input-group">
              <label>Contrase&ntilde;a</label>
              <input
                class="input-field"
                type="password"
                [(ngModel)]="authPass"
                placeholder="&#8226;&#8226;&#8226;&#8226;&#8226;&#8226;&#8226;&#8226;"
                autocomplete="new-password">
            </div>
          </div>

          <div class="logout-section" *ngIf="isAuthEnabled">
            <button class="btn btn-secondary" style="width: 100%;" (click)="handleLogout()">
              Cerrar sesi&oacute;n
            </button>
          </div>

          <h4 class="section-title" style="margin-top: 24px;">CivitAI</h4>
          <div class="settings-grid">
            <div class="input-group">
              <label>API Key (opcional)</label>
              <input
                class="input-field"
                type="password"
                [(ngModel)]="civitaiApiKey"
                placeholder="Sin API key"
                autocomplete="off">
              <p class="auth-hint" style="margin-top: 4px;">Necesaria para descargas grandes o modelos privados.</p>
            </div>
            <div class="input-group">
              <label>Moderaci&oacute;n de contenido</label>
              <div class="content-filter-header">
                <span class="content-filter-badge" [class.level-0]="contentFilterLevel === 0" [class.level-1]="contentFilterLevel === 1" [class.level-2]="contentFilterLevel === 2">
                  M&aacute;ximo permitido: {{ contentFilterLabel }}
                </span>
              </div>
              <div class="nsfw-toggles">
                <div class="nsfw-toggle-row" [class.disabled]="!isNsfwBitAllowed(1)">
                  <div class="nsfw-toggle-info">
                    <span class="nsfw-toggle-label">PG</span>
                    <span class="nsfw-toggle-desc">Safe for work</span>
                  </div>
                  <label class="toggle-switch">
                    <input type="checkbox" [checked]="hasNsfwBit(1)" [disabled]="!isNsfwBitAllowed(1)" (change)="toggleNsfwBit(1)">
                    <span class="toggle-slider"></span>
                  </label>
                </div>
                <div class="nsfw-toggle-row" [class.disabled]="!isNsfwBitAllowed(2)">
                  <div class="nsfw-toggle-info">
                    <span class="nsfw-toggle-label">PG-13</span>
                    <span class="nsfw-toggle-desc">Ropa sugerente, gore ligero</span>
                  </div>
                  <label class="toggle-switch">
                    <input type="checkbox" [checked]="hasNsfwBit(2)" [disabled]="!isNsfwBitAllowed(2)" (change)="toggleNsfwBit(2)">
                    <span class="toggle-slider"></span>
                  </label>
                </div>
                <div class="nsfw-toggle-row" [class.disabled]="!isNsfwBitAllowed(4)">
                  <div class="nsfw-toggle-info">
                    <span class="nsfw-toggle-label">R</span>
                    <span class="nsfw-toggle-desc">Desnudez parcial, situaciones adultas</span>
                  </div>
                  <label class="toggle-switch">
                    <input type="checkbox" [checked]="hasNsfwBit(4)" [disabled]="!isNsfwBitAllowed(4)" (change)="toggleNsfwBit(4)">
                    <span class="toggle-slider"></span>
                  </label>
                </div>
                <div class="nsfw-toggle-row" [class.disabled]="!isNsfwBitAllowed(8)">
                  <div class="nsfw-toggle-info">
                    <span class="nsfw-toggle-label">X</span>
                    <span class="nsfw-toggle-desc">Desnudez expl&iacute;cita, contenido adulto</span>
                  </div>
                  <label class="toggle-switch">
                    <input type="checkbox" [checked]="hasNsfwBit(8)" [disabled]="!isNsfwBitAllowed(8)" (change)="toggleNsfwBit(8)">
                    <span class="toggle-slider"></span>
                  </label>
                </div>
                <div class="nsfw-toggle-row" [class.disabled]="!isNsfwBitAllowed(16)">
                  <div class="nsfw-toggle-info">
                    <span class="nsfw-toggle-label">XXX</span>
                    <span class="nsfw-toggle-desc">Contenido extremo</span>
                  </div>
                  <label class="toggle-switch">
                    <input type="checkbox" [checked]="hasNsfwBit(16)" [disabled]="!isNsfwBitAllowed(16)" (change)="toggleNsfwBit(16)">
                    <span class="toggle-slider"></span>
                  </label>
                </div>
              </div>
            </div>
          </div>

          <h2 class="card-title" style="margin-top: 24px;">Mejora de prompts (OpenAI)</h2>
          <p class="auth-hint">Compatible con la API de chat de OpenAI y servidores con el mismo esquema (base URL hasta <code>/v1</code>). La clave se guarda en el servidor; las llamadas salen desde el backend. El texto mejorado se devuelve en <strong>ingl&eacute;s</strong> (adecuado para muchos modelos de v&iacute;deo chinos).</p>

          <div class="input-group">
            <label>Base URL de la API</label>
            <input
              class="input-field"
              type="text"
              [(ngModel)]="openaiApiBase"
              placeholder="https://api.openai.com/v1">
          </div>

          <div class="input-group">
            <label>API Key</label>
            <input
              class="input-field"
              type="password"
              [(ngModel)]="openaiApiKey"
              placeholder="sk-..."
              autocomplete="off">
          </div>

          <div class="settings-grid">
            <div class="input-group">
              <label>Modelo</label>
              <input
                class="input-field"
                type="text"
                [(ngModel)]="openaiModel"
                placeholder="gpt-4o-mini">
            </div>
            <div class="input-group">
              <label>Organizaci&oacute;n (opcional)</label>
              <input
                class="input-field"
                type="text"
                [(ngModel)]="openaiOrganization"
                placeholder="org-..."
                autocomplete="off">
            </div>
          </div>

          <div class="settings-grid">
            <div class="input-group">
              <label>Temperatura</label>
              <input
                class="input-field"
                type="number"
                step="0.1"
                min="0"
                max="2"
                [(ngModel)]="llmTemperature">
            </div>
            <div class="input-group">
              <label>M&aacute;x. tokens</label>
              <input
                class="input-field"
                type="number"
                min="32"
                max="4096"
                [(ngModel)]="llmMaxTokens">
            </div>
          </div>

          <div class="input-group" style="margin-top: 8px;">
            <label>Filtro de contenido (LLM)</label>
            <div class="content-filter-header">
              <span
                class="content-filter-badge"
                [class.level-0]="llmFilterCanToggle"
                [class.level-1]="!llmFilterCanToggle">
                {{ llmFilterMandatory ? 'Obligatorio si CONTENT_FILTER no es 0' : 'Opcional (CONTENT_FILTER=0)' }}
              </span>
            </div>
            <p class="auth-hint" style="margin-top: 6px;">
              Independiente de &laquo;Mejorar con IA&raquo;: si est&aacute; activo, el backend llama al LLM <strong>justo antes de ComfyUI</strong> y sustituye en el prompt principal (el que escribes o el ya mejorado) fragmentos inapropiados por equivalentes PG-13. Requiere API key.
            </p>
            <div class="nsfw-toggle-row" [class.disabled]="!llmFilterCanToggle">
              <div class="nsfw-toggle-info">
                <span class="nsfw-toggle-label">Filtro LLM</span>
                <span class="nsfw-toggle-desc">Paso interno previo a ComfyUI sobre el prompt positivo</span>
              </div>
              <label class="toggle-switch">
                <input
                  type="checkbox"
                  [checked]="llmFilterMandatory || llmContentFilterUserEnabled"
                  [disabled]="!llmFilterCanToggle"
                  (change)="toggleLlmContentFilter()">
                <span class="toggle-slider"></span>
              </label>
            </div>
          </div>

          <div class="config-actions">
            <button
              class="btn btn-secondary"
              (click)="handleTestLlm()"
              [disabled]="testingLlm">
              <span *ngIf="testingLlm" class="spinner"></span>
              <span>{{ testingLlm ? 'Probando...' : 'Probar OpenAI' }}</span>
            </button>
          </div>

          <div
            *ngIf="llmTestResult"
            class="connection-result"
            [class.success]="llmTestResult.status === 'ok'"
            [class.error]="llmTestResult.status === 'error'">
            {{ llmTestResult.message }}
          </div>

          <div class="config-actions">
            <button
              class="btn btn-secondary"
              (click)="handleTestConnection()"
              [disabled]="testingConnection">
              <span *ngIf="testingConnection" class="spinner"></span>
              <span>{{ testingConnection ? 'Probando...' : 'Probar conexi\u00f3n' }}</span>
            </button>

            <button
              class="btn btn-primary"
              (click)="handleSaveConfig()"
              [disabled]="savingConfig">
              Guardar
            </button>
          </div>

          <div
            *ngIf="connectionTestResult"
            class="connection-result"
            [class.success]="connectionTestResult.status === 'ok'"
            [class.error]="connectionTestResult.status === 'error'">
            {{ connectionTestResult.message }}
          </div>
        </div>

        <div class="card" *ngIf="isAdmin">
          <h2 class="card-title">Usuarios (Microsoft OAuth)</h2>
          <p class="auth-hint">
            Las credenciales <strong>Usuario / Contrase&ntilde;a</strong> de arriba son el acceso <strong>local</strong> a la app.
            Aqu&iacute; gestionas las cuentas que entran con <strong>Continuar con Microsoft</strong> (rol y desactivar).
          </p>
          <div *ngIf="adminUsersLoading" class="gallery-loading"><span class="spinner"></span></div>
          <div class="admin-users-card" *ngIf="!adminUsersLoading">
            <div class="admin-user-row" *ngFor="let u of adminUsers">
              <div class="admin-user-main">
                <span class="admin-user-email">{{ u.email || u.id }}</span>
                <span class="admin-user-name" *ngIf="u.display_name">{{ u.display_name }}</span>
                <span class="admin-user-meta">&Uacute;ltimo acceso: {{ formatUserTime(u.last_login) }}</span>
              </div>
              <select class="input-field admin-user-role"
                      [ngModel]="u.role"
                      (ngModelChange)="handleAdminUserRoleChange(u, $event)">
                <option value="user">Usuario</option>
                <option value="admin">Admin</option>
              </select>
              <label class="admin-user-dsl">
                <input type="checkbox" [checked]="u.disabled === 1"
                       (change)="handleAdminUserDisabledChange(u, $any($event.target).checked)" />
                Desactivado
              </label>
            </div>
            <div *ngIf="adminUsers.length === 0" class="empty-gallery">
              <p>A&uacute;n no hay usuarios con Microsoft; aparecer&aacute;n al iniciar sesi&oacute;n.</p>
            </div>
          </div>
          <button type="button" class="btn btn-secondary" style="width:100%;margin-top:8px;"
                  (click)="loadAdminUsers()">
            Actualizar lista
          </button>
        </div>
      </ng-container>

      <!-- ============ MODELS TAB ============ -->
      <ng-container *ngIf="activeTab === 'models'">
        <div class="sub-tabs">
          <button class="sub-tab" [class.active]="modelsView === 'search'" (click)="modelsView = 'search'">Modelos</button>
          <button class="sub-tab" [class.active]="modelsView === 'images'" (click)="modelsView = 'images'; handleBrowseImages()">Im&aacute;genes</button>
          <button class="sub-tab" [class.active]="modelsView === 'inventory'" (click)="modelsView = 'inventory'; loadInventory()">
            Inventario
          </button>
          <button class="sub-tab" *ngIf="isAdmin" [class.active]="modelsView === 'users'"
                  (click)="modelsView = 'users'; loadAdminUsers()">
            Usuarios
          </button>
        </div>

        <!-- SEARCH -->
        <ng-container *ngIf="modelsView === 'search'">
          <div class="search-bar">
            <input class="input-field search-input" type="text" [(ngModel)]="civitaiQuery"
                   placeholder="Buscar modelos en CivitAI..." (keydown.enter)="handleCivitaiSearch()">
            <button class="search-btn" (click)="handleCivitaiSearch()" [disabled]="civitaiSearching">
              <span *ngIf="civitaiSearching" class="spinner" style="width:16px;height:16px;"></span>
              <span *ngIf="!civitaiSearching">&#128269;</span>
            </button>
          </div>

          <div class="type-chips">
            <button *ngFor="let t of modelTypeOptions" class="type-chip"
                    [class.active]="civitaiType === t.value"
                    (click)="civitaiType = t.value; handleCivitaiSearch()">
              {{ t.label }}
            </button>
          </div>

          <div class="sort-row">
            <select class="select-field sort-select" [(ngModel)]="civitaiSort" (ngModelChange)="handleCivitaiSearch()">
              <option value="Most Downloaded">M&aacute;s descargados</option>
              <option value="Highest Rated">Mejor valorados</option>
              <option value="Newest">M&aacute;s recientes</option>
            </select>
          </div>

          <div class="model-grid" *ngIf="civitaiResults.length > 0">
            <div class="model-card" *ngFor="let model of civitaiResults"
                 (click)="handleOpenModelDetail(model)" tabindex="0" role="button">
              <div class="model-card-img">
                <img *ngIf="getModelThumb(model)" [src]="getModelThumb(model)" [alt]="model.name" loading="lazy">
                <div class="model-type-badge" [style.background]="getTypeColor(model.type)">{{ model.type }}</div>
              </div>
              <div class="model-card-body">
                <span class="model-card-name">{{ model.name }}</span>
                <span class="model-card-stats">
                  &darr;{{ formatNumber(model.stats?.downloadCount) }}
                  &nbsp;&nbsp;&#9733;{{ model.stats?.rating?.toFixed(1) || '-' }}
                </span>
              </div>
            </div>
          </div>

          <div *ngIf="civitaiResults.length === 0 && !civitaiSearching && civitaiSearched" class="empty-gallery">
            <p>Sin resultados</p>
          </div>

          <div *ngIf="civitaiSearching" class="gallery-loading"><span class="spinner"></span></div>

          <button *ngIf="civitaiHasMore && !civitaiSearching" class="btn btn-secondary load-more-btn"
                  (click)="handleCivitaiLoadMore()">Cargar m&aacute;s</button>
        </ng-container>

        <!-- IMAGES BROWSER -->
        <ng-container *ngIf="modelsView === 'images'">
          <div class="images-filters">
            <select class="select-field filter-select" [(ngModel)]="imgBrowseSort" (ngModelChange)="handleBrowseImages(true)">
              <option value="Most Reactions">Populares</option>
              <option value="Most Comments">Comentadas</option>
              <option value="Newest">Recientes</option>
            </select>
            <select class="select-field filter-select" [(ngModel)]="imgBrowsePeriod" (ngModelChange)="handleBrowseImages(true)">
              <option value="Day">Hoy</option>
              <option value="Week">Semana</option>
              <option value="Month">Mes</option>
              <option value="Year">A&ntilde;o</option>
              <option value="AllTime">Siempre</option>
            </select>
          </div>

          <div *ngIf="imgBrowseLoading && imgBrowseResults.length === 0" class="gallery-loading"><span class="spinner"></span></div>

          <div class="images-grid" *ngIf="imgBrowseResults.length > 0">
            <div class="images-grid-item" *ngFor="let img of imgBrowseResults"
                 (click)="handleOpenBrowsedImage(img)" tabindex="0" role="button"
                 aria-label="Ver detalles de generaci&oacute;n">
              <video *ngIf="img.type === 'video'" [src]="img.url"
                     muted loop playsinline preload="metadata"
                     (mouseenter)="handleVideoHover($event, true)"
                     (mouseleave)="handleVideoHover($event, false)"></video>
              <img *ngIf="img.type !== 'video'" [src]="getImageThumbUrl(img)" [alt]="img.username" loading="lazy">
              <div class="video-badge" *ngIf="img.type === 'video'">&#9654; Video</div>
              <div class="images-grid-overlay">
                <span class="img-stat" *ngIf="img.stats?.heartCount">&#9829; {{ img.stats.heartCount }}</span>
                <span class="img-stat" *ngIf="img.stats?.likeCount">&#128077; {{ img.stats.likeCount }}</span>
                <span class="img-stat" *ngIf="img.stats?.commentCount">&#128172; {{ img.stats.commentCount }}</span>
              </div>
              <div class="images-grid-base" *ngIf="img.baseModel">{{ img.baseModel }}</div>
            </div>
          </div>

          <div *ngIf="imgBrowseResults.length === 0 && !imgBrowseLoading" class="empty-gallery">
            <p>Sin im&aacute;genes</p>
          </div>

          <button *ngIf="imgBrowseHasMore && !imgBrowseLoading"
                  class="btn btn-secondary load-more-btn"
                  (click)="handleBrowseImagesMore()">Cargar m&aacute;s</button>
          <div *ngIf="imgBrowseLoading && imgBrowseResults.length > 0" class="gallery-loading"><span class="spinner"></span></div>
        </ng-container>

        <!-- INVENTORY -->
        <ng-container *ngIf="modelsView === 'inventory'">
          <div *ngIf="inventoryLoading && inventoryCategories.length === 0" class="gallery-loading"><span class="spinner"></span></div>

          <!-- Active downloads -->
          <div class="inv-downloads" *ngIf="inventoryActiveDownloads.length > 0">
            <div class="inv-downloads-title">Descargas activas</div>
            <div class="cache-item" *ngFor="let dl of inventoryActiveDownloads">
              <div class="cache-item-info">
                <span class="cache-item-name">{{ dl.name }}</span>
                <div class="cache-item-meta">
                  <span class="model-type-badge small" [style.background]="getTypeColor(dl.type)">{{ dl.type }}</span>
                  <span>{{ formatBytes(dl.size_bytes) }}</span>
                </div>
                <div class="cache-progress-bar">
                  <div class="cache-progress-fill" [style.width.%]="dl.progress"></div>
                </div>
                <span class="cache-item-status">{{ dl.progress?.toFixed(0) }}%</span>
              </div>
            </div>
          </div>

          <!-- Storage summary -->
          <div class="inv-summary" *ngIf="inventoryCategories.length > 0">
            <span class="inv-summary-total">{{ inventoryTotalFiles }} archivos &middot; {{ formatBytes(inventoryTotalBytes) }}</span>
          </div>

          <!-- Filter -->
          <div class="inv-filter" *ngIf="inventoryCategories.length > 0">
            <input class="input-field" type="text" [(ngModel)]="inventoryFilter"
                   placeholder="Filtrar por nombre...">
          </div>
          <p class="inv-hint" *ngIf="inventoryCategories.length > 0">
            En <strong>Modelos de Imagen</strong> o <strong>Modelos de V&iacute;deo</strong>, marca
            <em>Selector principal</em> y opcionalmente un nombre corto: esos modelos son los que ver&aacute;s en el desplegable
            de <strong>Generar &gt; Modelo</strong> (la lista completa sigue en Opciones avanzadas).
          </p>

          <!-- Categories -->
          <div class="inv-categories" *ngIf="inventoryCategories.length > 0">
            <div class="inv-category" *ngFor="let cat of inventoryCategories">
              <div class="inv-category-header" (click)="handleToggleInventoryCategory(cat.key)"
                   tabindex="0" role="button" aria-label="Expandir categor&iacute;a">
                <span class="inv-category-arrow" [class.expanded]="!inventoryCollapsed[cat.key]">&#9654;</span>
                <span class="inv-category-icon">{{ getInventoryIcon(cat.icon) }}</span>
                <span class="inv-category-label">{{ cat.label }}</span>
                <span class="inv-category-count">{{ getFilteredItems(cat).length }}</span>
                <span class="inv-category-size">{{ formatBytes(cat.total_bytes) }}</span>
              </div>
              <div class="inv-category-items" *ngIf="!inventoryCollapsed[cat.key]">
                <div class="inv-item" *ngFor="let item of getFilteredItems(cat)">
                  <div class="inv-item-main">
                    <div class="inv-item-info" (click)="handleOpenOverrideModal(item)" style="cursor:pointer"
                         tabindex="0" role="button" aria-label="Configurar modelo">
                      <span class="inv-item-name">{{ item.civitai_name || item.filename }}</span>
                      <div class="inv-item-meta">
                        <span class="inv-arch-badge" *ngIf="item.architecture">{{ item.architecture_label || item.architecture }}</span>
                        <span class="inv-base-badge" *ngIf="item.base_model">{{ item.base_model }}</span>
                        <span class="inv-civitai-badge" *ngIf="item.from_civitai">CivitAI</span>
                        <span class="inv-override-badge" *ngIf="item.has_override" title="Tiene overrides personalizados">&#9881;</span>
                        <span class="inv-item-size">{{ formatBytes(item.size_bytes) }}</span>
                      </div>
                      <span class="inv-item-file" *ngIf="item.civitai_name">{{ item.filename }}</span>
                    </div>
                    <div class="inv-fav-row" *ngIf="isPrincipalSelectorInventoryCategory(cat.key)"
                         (click)="$event.stopPropagation()">
                      <label class="inv-fav-check">
                        <input type="checkbox" [checked]="item.is_favorite"
                               (change)="handleToggleModelFavorite(item, $any($event.target).checked)" />
                        <span>Selector principal</span>
                      </label>
                      <input *ngIf="item.is_favorite" type="text" class="input-field inv-fav-short"
                             [value]="item.favorite_label || ''"
                             #favShort
                             (blur)="handleSaveFavoriteLabel(item, favShort.value)"
                             (keydown.enter)="favShort.blur()"
                             placeholder="Nombre corto en el desplegable" />
                    </div>
                  </div>
                  <button class="cache-delete-btn" (click)="handleDeleteInventoryItem(item, $event)"
                          aria-label="Eliminar modelo" title="Eliminar de ComfyUI">&#128465;</button>
                </div>
                <div class="inv-empty" *ngIf="getFilteredItems(cat).length === 0">
                  Sin resultados para el filtro
                </div>
              </div>
            </div>
          </div>

          <div *ngIf="inventoryCategories.length === 0 && !inventoryLoading" class="empty-gallery">
            <div class="empty-icon">&#128230;</div>
            <p>No se pudo cargar el inventario</p>
            <p class="empty-sub">Verifica la conexi&oacute;n con ComfyUI</p>
          </div>
        </ng-container>

        <ng-container *ngIf="modelsView === 'users'">
          <div *ngIf="adminUsersLoading" class="gallery-loading"><span class="spinner"></span></div>
          <div class="admin-users-card" *ngIf="!adminUsersLoading">
            <p class="auth-hint">
              Cuentas que han iniciado sesi&oacute;n con Microsoft. Los administradores pueden cambiar rol o desactivar acceso.
            </p>
            <div class="admin-user-row" *ngFor="let u of adminUsers">
              <div class="admin-user-main">
                <span class="admin-user-email">{{ u.email || u.id }}</span>
                <span class="admin-user-name" *ngIf="u.display_name">{{ u.display_name }}</span>
                <span class="admin-user-meta">&Uacute;ltimo acceso: {{ formatUserTime(u.last_login) }}</span>
              </div>
              <select class="input-field admin-user-role"
                      [ngModel]="u.role"
                      (ngModelChange)="handleAdminUserRoleChange(u, $event)">
                <option value="user">Usuario</option>
                <option value="admin">Admin</option>
              </select>
              <label class="admin-user-dsl">
                <input type="checkbox" [checked]="u.disabled === 1"
                       (change)="handleAdminUserDisabledChange(u, $any($event.target).checked)" />
                Desactivado
              </label>
            </div>
            <div *ngIf="adminUsers.length === 0" class="empty-gallery">
              <p>No hay usuarios registrados</p>
            </div>
          </div>
        </ng-container>

        <!-- MODEL OVERRIDE MODAL -->
        <div class="override-overlay" *ngIf="overrideModalOpen" (click)="overrideModalOpen = false">
          <div class="override-dialog" (click)="$event.stopPropagation()">
            <div class="override-header">
              <span class="override-title">Configuraci&oacute;n del modelo</span>
              <button class="viewer-close" (click)="overrideModalOpen = false">&#10005;</button>
            </div>

            <div *ngIf="overrideModalLoading" class="gallery-loading" style="padding:32px"><span class="spinner"></span></div>

            <div class="override-body" *ngIf="!overrideModalLoading && overrideModalItem">
              <div class="override-filename">{{ overrideModalItem.filename }}</div>
              <div class="override-detected">
                Detectado: <span class="inv-arch-badge">{{ overrideModalItem.architecture_label }}</span>
              </div>

              <div class="override-field">
                <label>Forzar arquitectura</label>
                <select class="select-field" [(ngModel)]="overrideForm.architecture">
                  <option value="">Auto-detectar</option>
                  <option *ngFor="let arch of overrideArchitectures" [value]="arch.id">{{ arch.label }}</option>
                </select>
              </div>

              <div class="override-row">
                <div class="override-field">
                  <label>Sampler</label>
                  <input class="input-field" type="text" [(ngModel)]="overrideForm.sampler" placeholder="Default de la arquitectura">
                </div>
                <div class="override-field">
                  <label>Scheduler</label>
                  <input class="input-field" type="text" [(ngModel)]="overrideForm.scheduler" placeholder="Default de la arquitectura">
                </div>
              </div>

              <div class="override-row">
                <div class="override-field">
                  <label>Steps</label>
                  <input class="input-field" type="number" [(ngModel)]="overrideForm.steps" placeholder="Default">
                </div>
                <div class="override-field">
                  <label>CFG</label>
                  <input class="input-field" type="number" step="0.5" [(ngModel)]="overrideForm.cfg" placeholder="Default">
                </div>
              </div>

              <div class="override-field">
                <label>VAE override</label>
                <input class="input-field" type="text" [(ngModel)]="overrideForm.vae" placeholder="Usar default de la arquitectura">
              </div>

              <div class="override-field override-checkbox">
                <label>
                  <input type="checkbox" [(ngModel)]="overrideForm.hidden">
                  Ocultar del selector de generaci&oacute;n
                </label>
              </div>

              <div class="override-field">
                <label>Notas</label>
                <textarea class="input-field" rows="2" [(ngModel)]="overrideForm.notes" placeholder="Notas opcionales..."></textarea>
              </div>
            </div>

            <div class="override-footer" *ngIf="!overrideModalLoading">
              <button class="btn btn-danger" (click)="handleDeleteOverride()"
                      *ngIf="overrideModalItem?.has_override">Eliminar override</button>
              <div class="override-footer-spacer"></div>
              <button class="btn btn-secondary" (click)="overrideModalOpen = false">Cancelar</button>
              <button class="btn btn-primary" (click)="handleSaveOverride()" [disabled]="overrideModalSaving">
                <span *ngIf="overrideModalSaving" class="spinner" style="width:14px;height:14px;"></span>
                {{ overrideModalSaving ? '' : 'Guardar' }}
              </button>
            </div>
          </div>
        </div>

        <!-- MODEL DETAIL OVERLAY -->
        <div class="model-detail-overlay" *ngIf="modelDetailOpen" (click)="modelDetailOpen = false">
          <div class="model-detail-panel" (click)="$event.stopPropagation()">
            <div class="model-detail-header">
              <button class="viewer-close" (click)="modelDetailOpen = false">&#10005;</button>
              <h3 class="model-detail-title">{{ modelDetail?.name }}</h3>
            </div>

            <div *ngIf="modelDetailLoading" class="gallery-loading"><span class="spinner"></span></div>

            <ng-container *ngIf="modelDetail && !modelDetailLoading">
              <div class="model-detail-images" *ngIf="getDetailImages().length > 0">
                <img *ngFor="let img of getDetailImages().slice(0, 6)" [src]="img" loading="lazy"
                     class="model-detail-img clickable-img"
                     (click)="handleOpenImageMeta(img)"
                     tabindex="0" role="button" aria-label="Ver detalles de generaci&oacute;n">
              </div>

              <div class="model-detail-info">
                <span class="model-type-badge" [style.background]="getTypeColor(modelDetail.type)">{{ modelDetail.type }}</span>
                <span class="model-detail-creator" *ngIf="modelDetail.creator">{{ modelDetail.creator?.username }}</span>
                <span class="model-detail-dl">&darr;{{ formatNumber(modelDetail.stats?.downloadCount) }}</span>
              </div>

              <div class="model-detail-section" *ngIf="getDetailTriggerWords().length > 0">
                <label>Trigger words</label>
                <div class="trigger-words">
                  <span class="trigger-word" *ngFor="let w of getDetailTriggerWords()">{{ w }}</span>
                </div>
              </div>

              <div class="model-detail-section">
                <label>Versi&oacute;n</label>
                <select class="select-field" [(ngModel)]="selectedVersionIdx"
                        (ngModelChange)="selectedVersionIdx = $event">
                  <option *ngFor="let v of modelDetail.modelVersions; let i = index" [ngValue]="i">
                    {{ v.name }}
                  </option>
                </select>
              </div>

              <div class="model-detail-section" *ngIf="getSelectedVersion()?.files?.length">
                <label>Archivos</label>
                <div class="file-list">
                  <div class="file-item" *ngFor="let f of getSelectedVersion().files">
                    <div class="file-item-info">
                      <span class="file-item-name">{{ f.name }}</span>
                      <span class="file-item-meta">
                        {{ formatBytes(f.sizeKB * 1024) }}
                        <span *ngIf="f.metadata?.format"> &middot; {{ f.metadata.format }}</span>
                        <span *ngIf="f.metadata?.fp"> &middot; {{ f.metadata.fp }}</span>
                      </span>
                    </div>
                    <button class="btn btn-primary file-dl-btn"
                            (click)="handleDownloadFile(f)"
                            [disabled]="f._downloading">
                      <span *ngIf="f._downloading" class="spinner" style="width:14px;height:14px;"></span>
                      {{ f._downloading ? '' : 'Descargar' }}
                    </button>
                  </div>
                </div>
              </div>
            </ng-container>
          </div>
        </div>

      </ng-container>

      <!-- ============ FULLSCREEN VIEWER ============ -->
      <div
        class="viewer-overlay"
        *ngIf="viewerOpen"
        (click)="handleCloseViewer()"
        (touchstart)="handleTouchStart($event)"
        (touchend)="handleTouchEnd($event)">

        <div class="viewer-header">
          <button class="viewer-close" (click)="handleCloseViewer()" aria-label="Cerrar">&#10005;</button>
          <div class="viewer-counter">{{ viewerIndex + 1 }} / {{ viewerItems.length }}</div>
          <div class="viewer-actions">
            <button class="viewer-action-btn" (click)="handleOpenMetaFromViewer($event)" aria-label="Detalles">&#9432;</button>
            <button class="viewer-action-btn" (click)="handleDownloadViewer($event)" aria-label="Descargar">&#8595;</button>
            <button
              class="viewer-action-btn viewer-delete"
              (click)="handleDeleteViewer($event)"
              aria-label="Eliminar">&#128465;</button>
          </div>
        </div>

        <div class="viewer-body" (click)="$event.stopPropagation()">
          <button
            *ngIf="viewerItems.length > 1"
            class="viewer-nav viewer-prev"
            (click)="handleViewerPrev($event)"
            aria-label="Anterior">&#8249;</button>

          <img
            class="viewer-img"
            [src]="viewerImageSrc"
            [alt]="viewerItems[viewerIndex]?.prompt || ''"
            (click)="$event.stopPropagation()">

          <button
            *ngIf="viewerItems.length > 1"
            class="viewer-nav viewer-next"
            (click)="handleViewerNext($event)"
            aria-label="Siguiente">&#8250;</button>
        </div>

        <div class="viewer-info" *ngIf="viewerItems[viewerIndex]?.prompt" (click)="$event.stopPropagation()">
          <p class="viewer-prompt">{{ viewerItems[viewerIndex]?.prompt }}</p>
          <p class="viewer-meta" *ngIf="viewerItems[viewerIndex]?.checkpoint">
            {{ viewerItems[viewerIndex]?.checkpoint }} &middot;
            {{ viewerItems[viewerIndex]?.width }}&times;{{ viewerItems[viewerIndex]?.height }}
          </p>
        </div>
      </div>

      <!-- ============ IMAGE META OVERLAY (Global) ============ -->
      <div class="image-meta-overlay" *ngIf="imageMetaOpen" (click)="imageMetaOpen = false">
        <div class="image-meta-panel" (click)="$event.stopPropagation()">
          <div class="image-meta-header">
            <button class="viewer-close" (click)="imageMetaOpen = false">&#10005;</button>
            <h3>Detalles de generaci&oacute;n</h3>
          </div>

          <div *ngIf="imageMetaLoading" class="gallery-loading"><span class="spinner"></span></div>

          <ng-container *ngIf="!imageMetaLoading && imageMetaData">
            <div class="image-meta-preview">
              <video *ngIf="imageMetaData?.type === 'video'" [src]="imageMetaUrl"
                     controls autoplay loop muted playsinline></video>
              <img *ngIf="imageMetaData?.type !== 'video'" [src]="imageMetaUrl" loading="lazy">
            </div>

            <div class="image-meta-grid">
              <div class="meta-item" *ngIf="imageMetaData.baseModel">
                <label>Base Model</label>
                <span>{{ imageMetaData.baseModel }}</span>
              </div>
              <div class="meta-item" *ngIf="imageMetaData.meta?.Model">
                <label>Modelo</label>
                <span>{{ imageMetaData.meta.Model }}</span>
              </div>
              <div class="meta-item" *ngIf="imageMetaData.meta?.sampler">
                <label>Sampler</label>
                <span>{{ imageMetaData.meta.sampler }}</span>
              </div>
              <div class="meta-item" *ngIf="imageMetaData.meta?.steps">
                <label>Steps</label>
                <span>{{ imageMetaData.meta.steps }}</span>
              </div>
              <div class="meta-item" *ngIf="imageMetaData.meta?.cfgScale">
                <label>CFG Scale</label>
                <span>{{ imageMetaData.meta.cfgScale }}</span>
              </div>
              <div class="meta-item" *ngIf="imageMetaData.meta?.seed">
                <label>Seed</label>
                <span class="seed-value">{{ imageMetaData.meta.seed }}</span>
              </div>
              <div class="meta-item" *ngIf="imageMetaData.meta?.Size || (imageMetaData.meta?.width && imageMetaData.meta?.height)">
                <label>Tama&ntilde;o</label>
                <span>{{ imageMetaData.meta.Size || (imageMetaData.meta.width + 'x' + imageMetaData.meta.height) }}</span>
              </div>
              <div class="meta-item" *ngIf="imageMetaData.meta?.clipSkip">
                <label>Clip Skip</label>
                <span>{{ imageMetaData.meta.clipSkip }}</span>
              </div>
              <div class="meta-item" *ngIf="imageMetaData.meta?.['Denoising strength']">
                <label>Denoise</label>
                <span>{{ imageMetaData.meta['Denoising strength'] }}</span>
              </div>
              <div class="meta-item" *ngIf="imageMetaData.username">
                <label>Autor</label>
                <span>{{ imageMetaData.username }}</span>
              </div>
            </div>

            <div class="image-meta-section" *ngIf="imageMetaData.meta?.prompt">
              <label>Prompt</label>
              <div class="meta-prompt-box">{{ imageMetaData.meta.prompt }}</div>
              <button class="btn btn-secondary meta-copy-btn"
                      (click)="handleCopyToClipboard(imageMetaData.meta.prompt)">
                Copiar prompt
              </button>
            </div>

            <div class="image-meta-section" *ngIf="imageMetaData.meta?.negativePrompt">
              <label>Negative Prompt</label>
              <div class="meta-prompt-box negative">{{ imageMetaData.meta.negativePrompt }}</div>
              <button class="btn btn-secondary meta-copy-btn"
                      (click)="handleCopyToClipboard(imageMetaData.meta.negativePrompt)">
                Copiar negative
              </button>
            </div>

            <div class="image-meta-section" *ngIf="getImageResources().length > 0">
              <label>Recursos utilizados</label>
              <div class="meta-resources">
                <div class="meta-resource" *ngFor="let r of getImageResources()">
                  <span class="resource-type" [style.background]="getResourceColor(r.type)">{{ r.type }}</span>
                  <span class="resource-name">{{ r.name }}</span>
                  <span class="resource-weight" *ngIf="r.weight">{{ r.weight }}</span>
                </div>
              </div>
            </div>

            <div class="image-meta-section" *ngIf="!imageMetaData.meta?.prompt && !imageMetaData.meta?.sampler">
              <p class="no-meta-msg">Esta imagen no tiene metadatos de generaci&oacute;n disponibles.</p>
            </div>

            <button class="btn btn-primary meta-use-btn"
                    *ngIf="imageMetaData.meta?.prompt"
                    (click)="handleUsePrompt(imageMetaData.meta)">
              Usar este prompt
            </button>
          </ng-container>

          <div *ngIf="!imageMetaLoading && !imageMetaData" class="no-meta-msg">
            <p>No se encontraron metadatos para esta imagen.</p>
          </div>
        </div>
      </div>

      <!-- ============ BOTTOM NAV ============ -->
      <nav class="bottom-nav">
        <button
          class="nav-item"
          [class.active]="activeTab === 'generate'"
          (click)="handleSwitchTab('generate')"
          aria-label="Generar">
          <span class="nav-icon">&#9998;</span>
          <span class="nav-label">Generar</span>
        </button>
        <button
          class="nav-item"
          [class.active]="activeTab === 'gallery'"
          (click)="handleSwitchTab('gallery')"
          aria-label="Galer\u00eda">
          <span class="nav-icon">&#9871;</span>
          <span class="nav-label">Galer&iacute;a</span>
          <span class="nav-badge" *ngIf="galleryTotal > 0">{{ galleryTotal }}</span>
        </button>
        <button
          class="nav-item"
          [class.active]="activeTab === 'models'"
          (click)="handleSwitchTab('models')"
          aria-label="Modelos">
          <span class="nav-icon">&#128230;</span>
          <span class="nav-label">Modelos</span>
        </button>
        <button
          class="nav-item"
          [class.active]="activeTab === 'config'"
          (click)="handleSwitchTab('config')"
          aria-label="Ajustes">
          <span class="nav-icon">&#9881;</span>
          <span class="nav-label">Ajustes</span>
        </button>
      </nav>

      <!-- Missing LoRAs Dialog -->
      <div class="ml-overlay" *ngIf="missingLorasOpen" (click)="handleCloseMissingLoras()">
        <div class="ml-dialog" (click)="$event.stopPropagation()">
          <div class="ml-header">
            <span class="ml-title">LoRAs no encontrados</span>
            <button class="ml-close" (click)="handleCloseMissingLoras()">&times;</button>
          </div>
          <div class="ml-body">
            <p class="ml-desc">Los siguientes LoRAs del prompt no existen en ComfyUI. Selecciona un candidato de CivitAI para descargar.</p>
            <div class="ml-lora-block" *ngFor="let ml of missingLoras">
              <div class="ml-lora-tag">&lt;lora:{{ ml.lora_tag }}&gt;</div>
              <div class="ml-progress-row" *ngIf="missingLoraProgress[ml.lora_tag]">
                <div class="ml-progress-bar">
                  <div class="ml-progress-fill"
                    [style.width.%]="missingLoraProgress[ml.lora_tag].progress"
                    [class.error]="missingLoraProgress[ml.lora_tag].status === 'error'">
                  </div>
                </div>
                <span class="ml-progress-text">{{ missingLoraProgress[ml.lora_tag].status === 'completed' ? 'Completado' : missingLoraProgress[ml.lora_tag].status === 'error' ? 'Error' : missingLoraProgress[ml.lora_tag].progress + '%' }}</span>
              </div>
              <div class="ml-candidates" *ngIf="ml.candidates.length > 0 && !missingLoraProgress[ml.lora_tag]">
                <div class="ml-candidate"
                  *ngFor="let c of ml.candidates"
                  [class.selected]="missingLoraSelections[ml.lora_tag] === c"
                  (click)="handleSelectLoraCandidate(ml.lora_tag, c)">
                  <img *ngIf="c.thumbnail" [src]="c.thumbnail" class="ml-thumb" alt="">
                  <div class="ml-cand-info">
                    <span class="ml-cand-name">{{ c.name }}</span>
                    <span class="ml-cand-meta">{{ c.base_model }} · {{ formatSizeMB(c.size_bytes) }} · {{ c.download_count | number }} descargas</span>
                    <span class="ml-cand-file">{{ c.filename }}</span>
                  </div>
                  <div class="ml-cand-check" *ngIf="missingLoraSelections[ml.lora_tag] === c">&#10003;</div>
                </div>
              </div>
              <div class="ml-no-results" *ngIf="ml.candidates.length === 0">
                No se encontraron resultados en CivitAI
              </div>
            </div>
          </div>
          <div class="ml-footer">
            <button class="btn btn-secondary" (click)="handleCloseMissingLoras()" [disabled]="missingLoraDownloading">Cancelar</button>
            <button class="btn btn-primary" (click)="handleDownloadMissingLoras()" [disabled]="missingLoraDownloading">
              <span *ngIf="missingLoraDownloading" class="spinner"></span>
              {{ missingLoraDownloading ? 'Descargando...' : 'Descargar y Generar' }}
            </button>
          </div>
        </div>
      </div>

      <!-- Toast -->
      <div
        class="toast"
        *ngIf="toastMessage"
        [class.success]="toastType === 'success'"
        [class.error]="toastType === 'error'">
        {{ toastMessage }}
      </div>
    </div>
  `,
  styles: [`
    .advanced-card { padding-bottom: 8px; }
    .advanced-toggle {
      display: flex; align-items: center; gap: 8px; width: 100%;
      background: none; border: none; color: var(--text-secondary);
      font-size: 14px; font-weight: 500; cursor: pointer; padding: 4px 0; font-family: inherit;
    }
    .advanced-toggle:hover { color: var(--text-primary); }
    .advanced-toggle-icon { display: inline-block; font-size: 10px; transition: transform 0.2s; }
    .advanced-toggle-icon.open { transform: rotate(90deg); }
    .advanced-body { margin-top: 16px; }
    .config-url-preview {
      font-family: monospace; font-size: 13px; color: var(--text-secondary);
      background: var(--bg-input); padding: 10px 14px; border-radius: 8px;
      margin-bottom: 16px; word-break: break-all;
    }
    .prompt-label-row {
      display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 8px;
    }
    .prompt-label-row label { margin-bottom: 0; }
    .btn-compact { padding: 6px 12px; font-size: 13px; white-space: nowrap; flex-shrink: 0; }
    .config-actions { display: flex; gap: 12px; margin-bottom: 12px; }
    .config-actions .btn { flex: 1; }
    .connection-result { padding: 12px 16px; border-radius: 10px; font-size: 14px; font-weight: 500; }
    .connection-result.success { background: rgba(34,197,94,0.15); color: var(--success); border: 1px solid rgba(34,197,94,0.3); }
    .connection-result.error { background: rgba(239,68,68,0.15); color: var(--error); border: 1px solid rgba(239,68,68,0.3); }
    .last-result { display: flex; gap: 8px; }
    .last-result-img { flex: 1; width: 100%; border-radius: 12px; cursor: pointer; }
    .last-result-img:active { transform: scale(0.98); }
    .auth-hint { font-size: 13px; color: var(--text-secondary); margin-bottom: 12px; line-height: 1.4; }
    .opt-advanced-pick { font-weight: 600; color: var(--accent, #6366f1); }
    .login-ms-btn { width: 100%; margin-bottom: 8px; }
    .login-oauth-hint { font-size: 12px; color: var(--text-secondary); text-align: center; margin-bottom: 8px; line-height: 1.4; }
    .login-divider { display: flex; align-items: center; gap: 12px; margin: 16px 0; color: var(--text-secondary); font-size: 12px; }
    .login-divider::before, .login-divider::after { content: ''; flex: 1; height: 1px; background: var(--border); }
    .admin-users-card { padding: 4px 0 16px; }
    .admin-user-row {
      display: flex; flex-wrap: wrap; align-items: center; gap: 10px;
      padding: 12px 0; border-bottom: 1px solid var(--border);
    }
    .admin-user-main { flex: 1; min-width: 180px; display: flex; flex-direction: column; gap: 4px; }
    .admin-user-email { font-weight: 600; font-size: 13px; }
    .admin-user-name { font-size: 12px; color: var(--text-secondary); }
    .admin-user-meta { font-size: 11px; color: var(--text-secondary); }
    .admin-user-role { width: 110px; padding: 6px 8px; font-size: 12px; }
    .admin-user-dsl { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-secondary); cursor: pointer; }
  `]
})
export class AppComponent implements OnInit, OnDestroy {
  appState: 'loading' | 'login' | 'app' = 'loading';
  activeTab: 'generate' | 'gallery' | 'config' | 'models' = 'generate';
  comfyOnline = false;

  loginUsername = '';
  loginPassword = '';
  loginError = '';
  loggingIn = false;
  isAuthEnabled = false;
  oauthAvailable = false;
  legacyLogin = false;
  isAdmin = false;

  adminUsers: AppUserRow[] = [];
  adminUsersLoading = false;

  modelsView: 'search' | 'images' | 'cache' | 'inventory' | 'users' = 'search';
  civitaiQuery = '';
  civitaiType = '';
  civitaiSort = 'Most Downloaded';
  civitaiResults: any[] = [];
  civitaiSearching = false;
  civitaiSearched = false;
  civitaiPage = 1;
  civitaiCursor = '';
  civitaiHasMore = false;

  modelDetailOpen = false;
  modelDetail: any = null;
  modelDetailLoading = false;
  selectedVersionIdx = 0;

  imageMetaOpen = false;
  imageMetaData: any = null;
  imageMetaLoading = false;
  imageMetaUrl = '';
  private versionImagesCache: Record<number, any[]> = {};

  imgBrowseSort = 'Most Reactions';
  imgBrowsePeriod = 'Week';
  imgBrowseResults: any[] = [];
  imgBrowseLoading = false;
  imgBrowseCursor = '';
  imgBrowseHasMore = false;
  private imgBrowseLoaded = false;

  cacheItems: CachedModel[] = [];
  cacheLoading = false;
  private cacheInterval?: ReturnType<typeof setInterval>;

  inventoryCategories: InventoryCategory[] = [];
  inventoryTotalBytes = 0;
  inventoryTotalFiles = 0;
  inventoryLoading = false;
  inventoryCollapsed: Record<string, boolean> = {};
  inventoryFilter = '';
  inventoryActiveDownloads: CachedModel[] = [];

  // Override modal
  overrideModalOpen = false;
  overrideModalItem: InventoryItem | null = null;
  overrideModalLoading = false;
  overrideModalSaving = false;
  overrideArchitectures: Architecture[] = [];
  overrideForm = {
    architecture: '' as string,
    sampler: '',
    scheduler: '',
    steps: null as number | null,
    cfg: null as number | null,
    vae: '',
    hidden: false,
    notes: '',
  };

  modelTypeOptions: ModelTypeOption[] = [
    { label: 'Todos', value: '' },
    { label: 'Checkpoint', value: 'Checkpoint' },
    { label: 'LoRA', value: 'LORA' },
    { label: 'ControlNet', value: 'Controlnet' },
    { label: 'VAE', value: 'VAE' },
    { label: 'Embedding', value: 'TextualInversion' },
    { label: 'Upscaler', value: 'Upscaler' },
  ];

  prompt = '';
  negativePrompt = 'nsfw, explicit, worst quality, worst aesthetic, bad quality, average quality, oldest, old, very displeasing, displeasing';
  /** Valor centinela: no es un checkpoint; abre opciones avanzadas */
  readonly modelPickAdvanced = '__KAS_ADVANCED__';
  /** &Uacute;ltimo modelo real de imagen (para restaurar tras elegir Avanzado) */
  lastRealImageModel = '';
  /** Favoritos para la lista reducida del selector principal de imagen */
  modelFavoriteEntries: ModelFavoriteEntry[] = [];
  selectedModel = 'novaAnimeXL_ilV125.safetensors';
  sampler = '';
  steps = 0;
  cfg = 0;
  width = 1024;
  height = 1024;
  strength = 1.0;

  showAdvanced = false;
  generating = false;
  models: Model[] = [];
  samplers: string[] = [];
  generatedImages: string[] = [];
  generatedVideos: string[] = [];  // Gallery IDs for generated videos

  // Video generation settings
  generationMode: 'image' | 'video' = 'image';
  videoLength = 81;  // Frames
  videoFps = 8.0;
  videoModels: import('./types').VideoModel[] = [];
  selectedVideoModel = '';
  videoResolutionPreset = '832x480';
  /** Coincide con un preset si width/height son exactamente 832x480, etc. */
  imageResolutionPreset = '';
  generationProgress = 0;

  configHost = '';
  configPort = '8188';
  configSecure = 'false';
  authUser = '';
  authPass = '';
  civitaiApiKey = '';
  civitaiNsfwLevel = '3';
  contentFilterLevel = 1;
  contentFilterLabel = 'PG / PG-13';
  contentMaxBitmask = 3;
  testingConnection = false;
  savingConfig = false;
  connectionTestResult: ConnectionTestResult | null = null;

  openaiApiBase = '';
  openaiApiKey = '';
  openaiModel = 'gpt-4o-mini';
  openaiOrganization = '';
  llmTemperature = '0.7';
  llmMaxTokens = '512';
  testingLlm = false;
  llmTestResult: LlmTestResult | null = null;
  enhancingPrompt = false;

  llmFilterMandatory = false;
  llmFilterCanToggle = true;
  llmContentFilterUserEnabled = false;

  galleryItems: GalleryItem[] = [];
  galleryTotal = 0;
  galleryLoading = false;

  viewerOpen = false;
  viewerIndex = 0;
  viewerItems: (GalleryItem & { src?: string })[] = [];
  viewerImageSrc = '';
  private touchStartX = 0;

  toastMessage = '';
  toastType: 'success' | 'error' = 'success';

  missingLorasOpen = false;
  missingLoras: MissingLoraResult[] = [];
  missingLoraSelections: Record<string, MissingLoraCandidate | null> = {};
  missingLoraDownloading = false;
  missingLoraProgress: Record<string, { status: string; progress: number }> = {};

  private sessionSub?: Subscription;
  private healthInterval?: ReturnType<typeof setInterval>;

  constructor(
    private generationService: GenerationService,
    private authService: AuthService,
  ) {}

  ngOnInit() {
    this.sessionSub = this.authService.sessionExpired$.subscribe(() => {
      this.loginError = 'Sesi\u00f3n expirada';
      this.checkAuthAndInit();
    });
    this.checkAuthAndInit();
  }

  ngOnDestroy() {
    this.sessionSub?.unsubscribe();
    if (this.healthInterval) clearInterval(this.healthInterval);
    if (this.cacheInterval) clearInterval(this.cacheInterval);
  }

  checkAuthAndInit() {
    const params = new URLSearchParams(window.location.search);
    const le = params.get('login_error');
    if (le) {
      this.loginError = this.mapLoginError(le);
      const u = new URL(window.location.href);
      u.searchParams.delete('login_error');
      const qs = u.searchParams.toString();
      window.history.replaceState({}, '', u.pathname + (qs ? `?${qs}` : '') + u.hash);
    }

    this.authService.checkStatus().subscribe({
      next: (status) => {
        this.applyAuthStatus(status);
        if (status.logged_in) {
          this.appState = 'app';
          this.initApp();
          if (this.isAdmin) {
            this.loadAdminUsers();
          }
        } else {
          this.appState = 'login';
        }
      },
      error: () => {
        this.appState = 'app';
        this.initApp();
      }
    });
  }

  private applyAuthStatus(status: AuthStatus) {
    this.isAuthEnabled = status.auth_enabled;
    this.oauthAvailable = !!status.oauth_available;
    this.legacyLogin = !!status.legacy_login;
    this.isAdmin = !!status.is_admin;
  }

  mapLoginError(code: string): string {
    const map: Record<string, string> = {
      state: 'Sesión de inicio inválida. Prueba de nuevo.',
      code: 'Falta el código de autorización.',
      disabled: 'Tu cuenta está desactivada.',
      config: 'OAuth no está configurado en el servidor.',
      no_id_token: 'Microsoft no devolvió identidad.',
      no_oid: 'No se pudo identificar tu cuenta.',
    };
    if (map[code]) return map[code];
    try {
      return decodeURIComponent(code.replace(/\+/g, ' '));
    } catch {
      return code;
    }
  }

  handleLoginMicrosoft() {
    this.authService.loginWithMicrosoft();
  }

  formatUserTime(ts: number): string {
    if (!ts) return '—';
    return new Date(ts * 1000).toLocaleString();
  }

  loadAdminUsers() {
    this.adminUsersLoading = true;
    this.generationService.getUsers().subscribe({
      next: (res) => {
        this.adminUsers = res.users || [];
        this.adminUsersLoading = false;
      },
      error: () => {
        this.adminUsersLoading = false;
        this.showToast('No se pudo cargar la lista de usuarios', 'error');
      },
    });
  }

  handleAdminUserRoleChange(u: AppUserRow, role: string) {
    if (role === u.role) return;
    this.generationService.patchUser(u.id, { role }).subscribe({
      next: (res) => {
        Object.assign(u, res.user);
        this.showToast('Usuario actualizado', 'success');
      },
      error: (err) => {
        this.showToast(err.error?.detail || 'Error al actualizar', 'error');
        this.loadAdminUsers();
      },
    });
  }

  handleAdminUserDisabledChange(u: AppUserRow, checked: boolean) {
    const disabled = !!checked;
    if ((u.disabled === 1) === disabled) return;
    this.generationService.patchUser(u.id, { disabled }).subscribe({
      next: (res) => {
        Object.assign(u, res.user);
        this.showToast('Usuario actualizado', 'success');
      },
      error: (err) => {
        this.showToast(err.error?.detail || 'Error al actualizar', 'error');
        this.loadAdminUsers();
      },
    });
  }

  private initApp() {
    this.loadConfig();
    this.checkHealth();
    this.loadModels();
    this.loadSamplers();
    this.loadSettings();
    this.loadGallery();
    this.loadVideoModels();
    this.loadModelFavorites();
    this.healthInterval = setInterval(() => this.checkHealth(), 30000);
  }

  handleLogin() {
    if (!this.loginUsername || !this.loginPassword) return;
    this.loggingIn = true;
    this.loginError = '';

    this.authService.login(this.loginUsername, this.loginPassword).subscribe({
      next: () => {
        this.loggingIn = false;
        this.loginUsername = '';
        this.loginPassword = '';
        this.authService.checkStatus().subscribe({
          next: (status) => {
            this.applyAuthStatus(status);
            this.appState = 'app';
            this.initApp();
            if (this.isAdmin) {
              this.loadAdminUsers();
            }
          },
          error: () => {
            this.appState = 'app';
            this.initApp();
          },
        });
      },
      error: (err) => {
        this.loggingIn = false;
        this.loginError = err.status === 401
          ? 'Usuario o contrase\u00f1a incorrectos'
          : 'Error de conexi\u00f3n';
      }
    });
  }

  handleLogout() {
    this.loginError = '';
    this.authService.logout(() => this.checkAuthAndInit());
  }

  @HostListener('document:keydown', ['$event'])
  handleKeyboard(e: KeyboardEvent) {
    if (!this.viewerOpen) return;
    if (e.key === 'Escape') this.handleCloseViewer();
    if (e.key === 'ArrowLeft') this.handleViewerPrev(e);
    if (e.key === 'ArrowRight') this.handleViewerNext(e);
  }

  handleSwitchTab(tab: 'generate' | 'gallery' | 'config' | 'models') {
    this.activeTab = tab;
    if (tab === 'gallery') this.loadGallery();
    if (tab === 'config' && this.isAdmin) {
      this.loadAdminUsers();
    }
  }

  checkHealth() {
    this.generationService.getHealth().subscribe({
      next: (status) => { this.comfyOnline = status.comfyui === 'ok'; },
      error: () => { this.comfyOnline = false; }
    });
  }

  loadConfig() {
    this.generationService.getConfig().subscribe({
      next: (cfg: any) => {
        this.configHost = cfg.comfyui_host || '';
        this.configPort = cfg.comfyui_port || '8188';
        this.configSecure = cfg.comfyui_secure || 'false';
        this.authUser = cfg.auth_user || '';
        this.authPass = cfg.auth_pass || '';
        this.civitaiApiKey = cfg.civitai_api_key || '';
        if (cfg.content_filter) {
          this.contentFilterLevel = cfg.content_filter.level ?? 1;
          this.contentFilterLabel = cfg.content_filter.label || 'PG / PG-13';
          this.contentMaxBitmask = cfg.content_filter.max_bitmask ?? 3;
          const userBm = cfg.content_filter.user_bitmask ?? this.contentMaxBitmask;
          this.civitaiNsfwLevel = String(userBm);
        }
        if (cfg.auth_enabled !== undefined) {
          this.isAuthEnabled = cfg.auth_enabled;
        }
        this.openaiApiBase = cfg.openai_api_base || 'https://api.openai.com/v1';
        this.openaiApiKey = cfg.openai_api_key || '';
        this.openaiModel = cfg.openai_model || 'gpt-4o-mini';
        this.openaiOrganization = cfg.openai_organization || '';
        this.llmTemperature = cfg.llm_temperature != null && cfg.llm_temperature !== ''
          ? String(cfg.llm_temperature) : '0.7';
        this.llmMaxTokens = cfg.llm_max_tokens != null && cfg.llm_max_tokens !== ''
          ? String(cfg.llm_max_tokens) : '512';
        const lf = cfg.llm_filter;
        if (lf) {
          this.llmFilterMandatory = !!lf.mandatory;
          this.llmFilterCanToggle = !!lf.can_toggle;
          this.llmContentFilterUserEnabled = lf.mandatory ? true : !!lf.user_enabled;
        }
      },
      error: () => {}
    });
  }

  loadModels() {
    this.generationService.getModels().subscribe({
      next: (data) => {
        const checkpoints = (data.checkpoints || []).map((item: any) => {
          if (typeof item === 'string') return { name: item, type: 'checkpoint' };
          return { name: item.name || item, type: item.type || 'checkpoint' };
        });
        const diffusionModels = (data.diffusion_models || []).map((item: any) => ({
          name: item.name || item,
          type: 'diffusion_model',
        }));
        this.models = [...checkpoints, ...diffusionModels];
        if (!this.selectedModel && this.models.length > 0) {
          this.selectedModel = this.models[0].name;
        }
        if (this.selectedModel && this.selectedModel !== this.modelPickAdvanced) {
          const im = this.models.find(
            m => m.name === this.selectedModel && (m.type === 'checkpoint' || m.type === 'diffusion_model')
          );
          if (im) this.lastRealImageModel = this.selectedModel;
        }
      },
      error: () => {}
    });
  }

  loadSamplers() {
    this.generationService.getSamplers().subscribe({
      next: (data) => { this.samplers = data.samplers; },
      error: () => { this.samplers = ['euler', 'euler_ancestral', 'dpmpp_2m', 'ddim']; }
    });
  }

  loadVideoModels() {
    this.generationService.getVideoModels().subscribe({
      next: (data) => { this.videoModels = data.models || []; },
      error: () => { this.videoModels = []; }
    });
  }

  loadModelFavorites() {
    this.generationService.getModelFavorites().subscribe({
      next: (res) => { this.modelFavoriteEntries = res.favorites || []; },
      error: () => { this.modelFavoriteEntries = []; }
    });
  }

  handleVideoResolutionPreset(preset: string) {
    this.videoResolutionPreset = preset;
    const [w, h] = preset.split('x').map(Number);
    this.width = w;
    this.height = h;
  }

  private static readonly IMAGE_RESOLUTION_PRESETS = ['832x480', '480x832', '640x640', '1280x720'] as const;

  syncImageResolutionPresetFromSize() {
    const key = `${this.width}x${this.height}`;
    this.imageResolutionPreset = (AppComponent.IMAGE_RESOLUTION_PRESETS as readonly string[]).includes(key)
      ? key
      : '';
  }

  handleImageResolutionPreset(preset: string) {
    this.imageResolutionPreset = preset;
    const [w, h] = preset.split('x').map(Number);
    this.width = w;
    this.height = h;
    this.handleSaveSetting('width', this.width);
    this.handleSaveSetting('height', this.height);
  }

  setGenerationMode(mode: 'image' | 'video') {
    this.generationMode = mode;
    if (mode === 'image') {
      this.syncImageResolutionPresetFromSize();
    }
  }

  loadSettings() {
    this.generationService.getSettings().subscribe({
      next: (s: Settings) => {
        if (s.checkpoint) {
          this.selectedModel = s.checkpoint;
          if (s.checkpoint !== this.modelPickAdvanced) {
            this.lastRealImageModel = s.checkpoint;
          }
        }
        if (s.sampler !== undefined) this.sampler = s.sampler;
        if (s.steps) this.steps = Number(s.steps) || 0;
        if (s.cfg) this.cfg = Number(s.cfg) || 0;
        if (s.width) this.width = Number(s.width) || 1024;
        if (s.height) this.height = Number(s.height) || 1024;
        if (s.negative_prompt) this.negativePrompt = s.negative_prompt;
        if (s.strength) this.strength = Number(s.strength) || 1.0;
        this.syncImageResolutionPresetFromSize();
      },
      error: () => {}
    });
  }

  handleSaveSetting(key: string, value: any) {
    this.generationService.saveSettings({ [key]: value }).subscribe();
  }

  // ─── Gallery ───────────────────────────────────────────────────────────

  loadGallery() {
    this.galleryLoading = true;
    this.generationService.getGallery(50, 0).subscribe({
      next: (res) => {
        this.galleryItems = res.items;
        this.galleryTotal = res.total;
        this.galleryLoading = false;
      },
      error: () => { this.galleryLoading = false; }
    });
  }

  handleLoadMore() {
    this.galleryLoading = true;
    this.generationService.getGallery(50, this.galleryItems.length).subscribe({
      next: (res) => {
        this.galleryItems = [...this.galleryItems, ...res.items];
        this.galleryTotal = res.total;
        this.galleryLoading = false;
      },
      error: () => { this.galleryLoading = false; }
    });
  }

  getImageUrl(imgId: string): string {
    const base = this.generationService.getGalleryImageUrl(imgId);
    return this.authService.getAuthenticatedUrl(base);
  }

  formatTime(ts: number): string {
    const d = new Date(ts * 1000);
    const now = new Date();
    const diff = now.getTime() - d.getTime();
    if (diff < 60000) return 'Ahora';
    if (diff < 3600000) return `${Math.floor(diff / 60000)} min`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)} h`;
    return d.toLocaleDateString('es-ES', { day: 'numeric', month: 'short' });
  }

  // ─── Viewer ────────────────────────────────────────────────────────────

  handleOpenViewer(index: number) {
    this.viewerItems = this.galleryItems.map(item => ({
      ...item,
      src: this.getImageUrl(item.id),
    }));
    this.viewerIndex = index;
    this.viewerImageSrc = this.viewerItems[index].src || '';
    this.viewerOpen = true;
  }

  handleOpenGalleryMeta(item: any) {
    this.imageMetaOpen = true;
    this.imageMetaLoading = true;
    this.imageMetaData = null;
    this.imageMetaUrl = this.getImageUrl(item.id);

    this.generationService.getGalleryImageMeta(item.id).subscribe({
      next: (res: any) => {
        this.imageMetaData = res;
        this.imageMetaLoading = false;
      },
      error: () => {
        // Fallback to basic item data if API fails
        this.imageMetaData = {
          ...item,
          url: this.getImageUrl(item.id),
          meta: {
            prompt: item.prompt || '',
            negativePrompt: item.neg_prompt || '',
            Model: item.checkpoint || '',
            Size: `${item.width || 0}x${item.height || 0}`,
            seed: item.seed || 0,
            sampler: item.sampler || '',
            scheduler: item.scheduler || '',
            steps: item.steps || 0,
            cfg: item.cfg || 0,
            strength: item.strength || 0,
          }
        };
        this.imageMetaLoading = false;
      },
    });
  }

  handleOpenMetaFromViewer(event: Event) {
    event.stopPropagation();
    const currentItem = this.viewerItems[this.viewerIndex];
    if (!currentItem) return;
    this.viewerOpen = false;
    this.handleOpenGalleryMeta(currentItem);
  }

  handleViewLastResult(index: number) {
    if (this.generatedImages.length === 0) return;
    this.viewerItems = this.generatedImages.map((img, i) => ({
      id: `result-${i}`,
      prompt: this.prompt,
      neg_prompt: this.negativePrompt,
      checkpoint: this.effectiveImageCheckpoint(),
      width: this.width,
      height: this.height,
      filename: '',
      created_at: Date.now() / 1000,
      src: img,
    }));
    this.viewerIndex = index;
    this.viewerImageSrc = this.viewerItems[index].src || '';
    this.viewerOpen = true;
  }

  handleCloseViewer() {
    this.viewerOpen = false;
  }

  handleViewerPrev(e: Event) {
    e.stopPropagation();
    if (this.viewerIndex > 0) {
      this.viewerIndex--;
      this.viewerImageSrc = this.viewerItems[this.viewerIndex].src || '';
    }
  }

  handleViewerNext(e: Event) {
    e.stopPropagation();
    if (this.viewerIndex < this.viewerItems.length - 1) {
      this.viewerIndex++;
      this.viewerImageSrc = this.viewerItems[this.viewerIndex].src || '';
    }
  }

  handleTouchStart(e: TouchEvent) {
    this.touchStartX = e.changedTouches[0]?.clientX || 0;
  }

  handleTouchEnd(e: TouchEvent) {
    const endX = e.changedTouches[0]?.clientX || 0;
    const diff = endX - this.touchStartX;
    if (Math.abs(diff) > 60) {
      if (diff > 0) this.handleViewerPrev(e);
      else this.handleViewerNext(e);
    }
  }

  handleDownloadViewer(e: Event) {
    e.stopPropagation();
    const item = this.viewerItems[this.viewerIndex];
    if (!item) return;
    const link = document.createElement('a');
    link.href = item.src || '';
    link.download = `krita-ai-${item.id}.png`;
    link.click();
  }

  handleDeleteViewer(e: Event) {
    e.stopPropagation();
    const item = this.viewerItems[this.viewerIndex];
    if (!item || item.id.startsWith('result-')) return;

    this.generationService.deleteGalleryImage(item.id).subscribe({
      next: () => {
        this.viewerItems.splice(this.viewerIndex, 1);
        this.galleryItems = this.galleryItems.filter(g => g.id !== item.id);
        this.galleryTotal = Math.max(0, this.galleryTotal - 1);

        if (this.viewerItems.length === 0) {
          this.handleCloseViewer();
          return;
        }
        if (this.viewerIndex >= this.viewerItems.length) {
          this.viewerIndex = this.viewerItems.length - 1;
        }
        this.viewerImageSrc = this.viewerItems[this.viewerIndex].src || '';
        this.showToast('Imagen eliminada', 'success');
      },
      error: () => { this.showToast('Error al eliminar', 'error'); }
    });
  }

  // ─── Config ────────────────────────────────────────────────────────────

  handleTestLlm() {
    this.testingLlm = true;
    this.llmTestResult = null;
    this.generationService.testLlm({
      openai_api_base: this.openaiApiBase,
      openai_api_key: this.openaiApiKey,
      openai_model: this.openaiModel,
      openai_organization: this.openaiOrganization,
    }).subscribe({
      next: (r) => {
        this.testingLlm = false;
        this.llmTestResult = r;
      },
      error: (err) => {
        this.testingLlm = false;
        const d = err?.error?.detail;
        this.llmTestResult = {
          status: 'error',
          message: typeof d === 'string' ? d : 'Error al probar OpenAI',
        };
      },
    });
  }

  handleEnhancePrompt() {
    const p = (this.prompt || '').trim();
    if (!p) {
      this.showToast('Escribe un prompt', 'error');
      return;
    }
    this.enhancingPrompt = true;
    this.generationService.enhancePrompt(p).subscribe({
      next: (res) => {
        this.enhancingPrompt = false;
        if (res?.prompt) {
          this.prompt = res.prompt;
          this.showToast('Prompt actualizado', 'success');
        }
      },
      error: (err) => {
        this.enhancingPrompt = false;
        const d = err?.error?.detail;
        const msg = typeof d === 'string' ? d : 'No se pudo mejorar el prompt';
        this.showToast(msg, 'error');
      },
    });
  }

  handleTestConnection() {
    this.testingConnection = true;
    this.connectionTestResult = null;

    this.generationService.testConnection({
      comfyui_host: this.configHost,
      comfyui_port: this.configPort,
      comfyui_secure: this.configSecure,
    }).subscribe({
      next: (result) => {
        this.testingConnection = false;
        this.connectionTestResult = result;
      },
      error: () => {
        this.testingConnection = false;
        this.connectionTestResult = { status: 'error', url: '', message: 'Error de red al probar' };
      }
    });
  }

  handleSaveConfig() {
    this.savingConfig = true;
    this.generationService.saveConfig({
      comfyui_host: this.configHost,
      comfyui_port: this.configPort,
      comfyui_secure: this.configSecure,
      auth_user: this.authUser,
      auth_pass: this.authPass,
      civitai_api_key: this.civitaiApiKey,
      civitai_nsfw_level: this.civitaiNsfwLevel,
      openai_api_base: this.openaiApiBase,
      openai_api_key: this.openaiApiKey,
      openai_model: this.openaiModel,
      openai_organization: this.openaiOrganization,
      llm_temperature: this.llmTemperature,
      llm_max_tokens: this.llmMaxTokens,
      llm_content_filter: this.llmFilterMandatory
        ? 'true'
        : (this.llmContentFilterUserEnabled ? 'true' : 'false'),
    }).subscribe({
      next: (res: any) => {
        this.savingConfig = false;
        if (res?.token) {
          this.authService.setToken(res.token);
        }
        this.isAuthEnabled = !!res?.auth_enabled;
        this.authService.checkStatus().subscribe({
          next: (s) => {
            this.applyAuthStatus(s);
            if (this.isAdmin && this.activeTab === 'config') {
              this.loadAdminUsers();
            }
          },
          error: () => {},
        });
        if (res?.auth_activated) {
          this.showToast('Autenticaci\u00f3n activada', 'success');
        } else {
          this.showToast('Configuraci\u00f3n guardada', 'success');
        }
        this.checkHealth();
        this.loadModels();
        if (res?.openai_api_key) {
          this.openaiApiKey = res.openai_api_key;
        }
        const lf = res?.llm_filter;
        if (lf) {
          this.llmFilterMandatory = !!lf.mandatory;
          this.llmFilterCanToggle = !!lf.can_toggle;
          this.llmContentFilterUserEnabled = lf.mandatory ? true : !!lf.user_enabled;
        }
      },
      error: () => {
        this.savingConfig = false;
        this.showToast('Error al guardar', 'error');
      }
    });
  }

  // ─── Generate ──────────────────────────────────────────────────────────

  handleGenerate() {
    if (!this.prompt) {
      this.showToast('Escribe un prompt', 'error');
      return;
    }

    // Dispatch to appropriate handler based on generation mode
    if (this.generationMode === 'video') {
      this.handleGenerateVideo();
    } else {
      this.handleGenerateImage();
    }
  }

  handleGenerateImage() {
    this.generating = true;
    this.generationProgress = 0;
    this.generatedImages = [];
    this.generatedVideos = [];

    const request: GenerationRequest = {
      prompt: this.prompt,
      negative_prompt: this.negativePrompt,
      width: this.width,
      height: this.height,
      steps: this.steps,
      cfg_scale: this.cfg,
      sampler: this.sampler,
      checkpoint: this.effectiveImageCheckpoint(),
      seed: -1,
      strength: this.strength,
    };

    this.generationService.generateTxt2Img(request).subscribe({
      next: (response) => {
        if (response.status === 'missing_loras' && response.missing_loras?.length) {
          this.generating = false;
          this.handleMissingLoras(response.missing_loras);
          return;
        }
        this.showToast('Generaci\u00f3n iniciada', 'success');
        this.pollJob(response.job_id);
      },
      error: (err) => {
        this.showToast('Error: ' + err.message, 'error');
        this.generating = false;
      }
    });

    this.generationService.saveSettings({
      strength: this.strength,
      negative_prompt: this.negativePrompt,
    }).subscribe();
  }

  pollJob(jobId: string) {
    let attempts = 0;
    const maxAttempts = this.generationMode === 'video' ? 600 : 60;
    const pollInterval = this.generationMode === 'video' ? 3000 : 2000;
    const interval = setInterval(() => {
      attempts++;
      if (attempts > maxAttempts) {
        clearInterval(interval);
        this.generating = false;
        this.generationProgress = 0;
        this.showToast('Tiempo de espera agotado', 'error');
        return;
      }

      this.generationService.getJobStatus(jobId).subscribe({
        next: (status) => {
          if (status.progress && status.progress > 0) {
            this.generationProgress = status.progress;
          }

          if (status.status === 'completed') {
            clearInterval(interval);
            this.generating = false;
            this.generationProgress = 0;

            if (status.is_video) {
              this.generatedVideos = (status as any).gallery_video_ids || status.video_ids || [];
              this.generatedImages = [];
              this.showToast('Video generado!', 'success');
              this.loadGallery();
            } else if (status.images && status.images.length > 0) {
              this.generatedImages = status.images.map(img =>
                img.startsWith('data:image') ? img : `data:image/png;base64,${img}`
              );
              this.generatedVideos = [];
              this.showToast('Imagen generada!', 'success');
              this.loadGallery();
            } else {
              this.showToast('No se gener\u00f3 ning\u00fan resultado', 'error');
            }
          } else if (status.status === 'error') {
            clearInterval(interval);
            this.generating = false;
            this.generationProgress = 0;
            this.showToast('Error: ' + (status.error || 'Generaci\u00f3n fallida'), 'error');
          }
        },
        error: () => {}
      });
    }, pollInterval);
  }

  handleGenerateVideo() {
    if (!this.prompt) {
      this.showToast('Escribe un prompt', 'error');
      return;
    }

    this.generating = true;
    this.generationProgress = 0;
    this.generatedImages = [];
    this.generatedVideos = [];

    const [w, h] = this.videoResolutionPreset.split('x').map(Number);

    const request: GenerationVideoRequest = {
      prompt: this.prompt,
      negative_prompt: this.negativePrompt,
      width: w || 832,
      height: h || 480,
      length: this.videoLength,
      fps: this.videoFps,
      steps: this.steps,
      cfg_scale: this.cfg,
      sampler: this.sampler,
      checkpoint: this.selectedVideoModel || undefined,
      seed: -1,
    };

    this.generationService.generateTxt2Video(request).subscribe({
      next: (response) => {
        if (response.status === 'missing_loras' && response.missing_loras) {
          this.generating = false;
          this.handleMissingLoras(response.missing_loras);
          return;
        }
        this.showToast('Generaci\u00f3n de video iniciada', 'success');
        this.pollJob(response.job_id);
      },
      error: (err) => {
        this.showToast('Error: ' + err.message, 'error');
        this.generating = false;
      }
    });

    this.generationService.saveSettings({
      strength: this.strength,
      negative_prompt: this.negativePrompt,
    }).subscribe();
  }

  getVideoUrl(videoId: string): string {
    return this.generationService.getVideoUrl(videoId);
  }

  // ─── CivitAI / Models ─────────────────────────────────────────────────

  handleCivitaiSearch() {
    this.civitaiPage = 1;
    this.civitaiCursor = '';
    this.civitaiResults = [];
    this.civitaiSearched = true;
    this.civitaiSearching = true;
    this._doCivitaiSearch(false);
  }

  handleCivitaiLoadMore() {
    this.civitaiSearching = true;
    this._doCivitaiSearch(true);
  }

  private _doCivitaiSearch(append: boolean) {
    const params: Record<string, string | number | boolean> = {
      query: this.civitaiQuery,
      types: this.civitaiType,
      sort: this.civitaiSort,
      limit: 20,
    };
    if (this.civitaiCursor) {
      params['cursor'] = this.civitaiCursor;
    } else if (!this.civitaiQuery) {
      params['page'] = this.civitaiPage;
    }

    this.generationService.searchCivitai(params).subscribe({
      next: (res: any) => {
        const items = res.items || [];
        this.civitaiResults = append ? [...this.civitaiResults, ...items] : items;
        const meta = res.metadata || {};
        this.civitaiCursor = meta.nextCursor || '';
        this.civitaiHasMore = !!(meta.nextCursor || meta.nextPage);
        if (!this.civitaiQuery && meta.nextPage) {
          this.civitaiPage++;
        }
        this.civitaiSearching = false;
      },
      error: () => {
        this.civitaiSearching = false;
        if (!append) this.showToast('Error buscando en CivitAI', 'error');
      },
    });
  }

  handleOpenModelDetail(model: any) {
    this.modelDetailOpen = true;
    this.modelDetailLoading = true;
    this.modelDetail = model;
    this.selectedVersionIdx = 0;
    this.generationService.getCivitaiModel(model.id).subscribe({
      next: (detail: any) => {
        this.modelDetail = detail;
        this.modelDetailLoading = false;
      },
      error: () => {
        this.modelDetailLoading = false;
        this.showToast('Error cargando detalle', 'error');
      },
    });
  }

  getSelectedVersion(): any {
    if (!this.modelDetail?.modelVersions) return null;
    return this.modelDetail.modelVersions[this.selectedVersionIdx] || null;
  }

  getDetailImages(): string[] {
    const version = this.getSelectedVersion();
    if (!version?.images) return [];
    return version.images.map((img: any) => img.url).filter(Boolean);
  }

  getDetailTriggerWords(): string[] {
    const version = this.getSelectedVersion();
    if (!version?.trainedWords) return [];
    return version.trainedWords;
  }

  handleDownloadFile(file: any) {
    if (!this.modelDetail) return;
    const version = this.getSelectedVersion();
    if (!version) return;

    file._downloading = true;
    const meta = {
      thumbnail: this.getDetailImages()[0] || '',
      triggerWords: this.getDetailTriggerWords(),
      creator: this.modelDetail.creator?.username || '',
    };
    this.generationService.downloadModel({
      civitai_model_id: this.modelDetail.id,
      civitai_version_id: version.id,
      download_url: file.downloadUrl,
      name: this.modelDetail.name,
      type: this.modelDetail.type,
      filename: file.name,
      size_bytes: (file.sizeKB || 0) * 1024,
      metadata: JSON.stringify(meta),
    }).subscribe({
      next: () => {
        file._downloading = false;
        this.showToast('Descarga iniciada', 'success');
        this.loadCache();
        if (this.modelsView === 'inventory') this.loadInventory();
      },
      error: () => {
        file._downloading = false;
        this.showToast('Error iniciando descarga', 'error');
      },
    });
  }

  loadCache() {
    this.cacheLoading = true;
    this.generationService.getCache().subscribe({
      next: (res) => {
        this.cacheItems = res.items || [];
        this.cacheLoading = false;
        const hasActive = this.cacheItems.some(i => i.status === 'downloading');
        if (hasActive && !this.cacheInterval) {
          this.cacheInterval = setInterval(() => this.pollCache(), 2000);
        }
        if (!hasActive && this.cacheInterval) {
          clearInterval(this.cacheInterval);
          this.cacheInterval = undefined;
        }
      },
      error: () => { this.cacheLoading = false; },
    });
  }

  pollCache() {
    this.generationService.getCache().subscribe({
      next: (res) => {
        this.cacheItems = res.items || [];
        const hasActive = this.cacheItems.some(i => i.status === 'downloading');
        if (!hasActive && this.cacheInterval) {
          clearInterval(this.cacheInterval);
          this.cacheInterval = undefined;
        }
      },
    });
  }

  handleDeleteCacheItem(id: string) {
    this.generationService.deleteCacheItem(id).subscribe({
      next: () => {
        this.cacheItems = this.cacheItems.filter(i => i.id !== id);
        this.showToast('Modelo eliminado', 'success');
      },
      error: () => this.showToast('Error eliminando modelo', 'error'),
    });
  }

  loadInventory() {
    this.inventoryLoading = true;
    this.generationService.getInventory().subscribe({
      next: (res) => {
        this.inventoryCategories = res.categories || [];
        this.inventoryTotalBytes = res.total_bytes || 0;
        this.inventoryTotalFiles = res.total_files || 0;
        this.inventoryActiveDownloads = (res.active_downloads || []) as CachedModel[];
        this.inventoryLoading = false;
        if (this.inventoryActiveDownloads.length > 0 && !this.cacheInterval) {
          this.cacheInterval = setInterval(() => this.loadInventory(), 3000);
        }
        if (this.inventoryActiveDownloads.length === 0 && this.cacheInterval) {
          clearInterval(this.cacheInterval);
          this.cacheInterval = undefined;
        }
      },
      error: () => { this.inventoryLoading = false; },
    });
  }

  handleToggleInventoryCategory(key: string) {
    this.inventoryCollapsed[key] = !this.inventoryCollapsed[key];
  }

  getFilteredItems(cat: InventoryCategory): InventoryItem[] {
    if (!this.inventoryFilter) return cat.items;
    const q = this.inventoryFilter.toLowerCase();
    return cat.items.filter(i =>
      i.filename.toLowerCase().includes(q) ||
      (i.civitai_name && i.civitai_name.toLowerCase().includes(q)) ||
      (i.base_model && i.base_model.toLowerCase().includes(q)) ||
      (i.architecture_label && i.architecture_label.toLowerCase().includes(q))
    );
  }

  handleDeleteInventoryItem(item: InventoryItem, event: Event) {
    event.stopPropagation();
    if (!confirm(`Eliminar "${item.civitai_name || item.filename}" de ComfyUI?`)) return;
    this.generationService.deleteInventoryModel(item.folder, item.filename).subscribe({
      next: () => {
        for (const cat of this.inventoryCategories) {
          const idx = cat.items.indexOf(item);
          if (idx >= 0) {
            cat.items.splice(idx, 1);
            cat.count = cat.items.length;
            cat.total_bytes -= item.size_bytes;
            break;
          }
        }
        this.inventoryTotalFiles--;
        this.inventoryTotalBytes -= item.size_bytes;
        this.showToast('Modelo eliminado de ComfyUI', 'success');
      },
      error: () => this.showToast('Error eliminando modelo', 'error'),
    });
  }

  getInventoryIcon(icon: string): string {
    const icons: Record<string, string> = {
      'cube': '\u{1F4E6}',
      'sparkles': '\u2728',
      'film': '\u{1F3AC}',
      'sliders': '\u{1F39B}\uFE0F',
      'cog': '\u2699\uFE0F',
      'arrow-up': '\u2B06\uFE0F',
      'folder': '\u{1F4C1}',
    };
    return icons[icon] || '\u{1F4C1}';
  }

  // ─── Model Override Modal ─────────────────────────────────────────────

  handleOpenOverrideModal(item: InventoryItem) {
    this.overrideModalItem = item;
    this.overrideModalOpen = true;
    this.overrideModalLoading = true;
    this.overrideForm = {
      architecture: '',
      sampler: '',
      scheduler: '',
      steps: null,
      cfg: null,
      vae: '',
      hidden: false,
      notes: '',
    };

    if (this.overrideArchitectures.length === 0) {
      this.generationService.getArchitectures().subscribe({
        next: (res) => { this.overrideArchitectures = res.architectures || []; },
        error: () => {},
      });
    }

    this.generationService.getModelOverride(item.filename).subscribe({
      next: (res) => {
        if (res.override) {
          const o = res.override;
          this.overrideForm = {
            architecture: o.architecture || '',
            sampler: o.sampling?.sampler || '',
            scheduler: o.sampling?.scheduler || '',
            steps: o.sampling?.steps ?? null,
            cfg: o.sampling?.cfg ?? null,
            vae: o.vae || '',
            hidden: !!o.hidden,
            notes: o.notes || '',
          };
        }
        this.overrideModalLoading = false;
      },
      error: () => { this.overrideModalLoading = false; },
    });
  }

  handleSaveOverride() {
    if (!this.overrideModalItem) return;
    this.overrideModalSaving = true;

    const sampling: Record<string, any> = {};
    if (this.overrideForm.sampler) sampling['sampler'] = this.overrideForm.sampler;
    if (this.overrideForm.scheduler) sampling['scheduler'] = this.overrideForm.scheduler;
    if (this.overrideForm.steps != null) sampling['steps'] = this.overrideForm.steps;
    if (this.overrideForm.cfg != null) sampling['cfg'] = this.overrideForm.cfg;

    const data: Record<string, any> = {
      architecture: this.overrideForm.architecture || null,
      sampling,
      vae: this.overrideForm.vae || null,
      hidden: this.overrideForm.hidden,
      notes: this.overrideForm.notes,
    };

    this.generationService.saveModelOverride(this.overrideModalItem.filename, data).subscribe({
      next: () => {
        this.overrideModalSaving = false;
        this.overrideModalOpen = false;
        this.overrideModalItem!.has_override = true;
        this.showToast('Override guardado', 'success');
        this.loadInventory();
      },
      error: () => {
        this.overrideModalSaving = false;
        this.showToast('Error guardando override', 'error');
      },
    });
  }

  handleDeleteOverride() {
    if (!this.overrideModalItem) return;
    this.generationService.deleteModelOverride(this.overrideModalItem.filename).subscribe({
      next: () => {
        this.overrideModalOpen = false;
        this.overrideModalItem!.has_override = false;
        this.showToast('Override eliminado', 'success');
        this.loadInventory();
      },
      error: () => this.showToast('Error eliminando override', 'error'),
    });
  }

  // ─── Missing LoRAs Dialog ──────────────────────────────────────────────

  handleMissingLoras(missing: MissingLoraResult[]) {
    this.missingLoras = missing;
    this.missingLoraSelections = {};
    this.missingLoraProgress = {};
    this.missingLoraDownloading = false;

    for (const ml of missing) {
      this.missingLoraSelections[ml.lora_tag] = ml.candidates.length > 0
        ? ml.candidates[0]
        : null;
    }
    this.missingLorasOpen = true;
  }

  handleSelectLoraCandidate(loraTag: string, candidate: MissingLoraCandidate) {
    this.missingLoraSelections[loraTag] = candidate;
  }

  handleCloseMissingLoras() {
    this.missingLorasOpen = false;
    this.missingLoras = [];
    this.missingLoraSelections = {};
    this.missingLoraProgress = {};
    this.missingLoraDownloading = false;
  }

  handleDownloadMissingLoras() {
    const toDownload: { tag: string; candidate: MissingLoraCandidate }[] = [];
    for (const ml of this.missingLoras) {
      const sel = this.missingLoraSelections[ml.lora_tag];
      if (sel) {
        toDownload.push({ tag: ml.lora_tag, candidate: sel });
      }
    }

    if (toDownload.length === 0) {
      this.showToast('Selecciona al menos un LoRA para descargar', 'error');
      return;
    }

    this.missingLoraDownloading = true;
    let completed = 0;

    for (const item of toDownload) {
      this.missingLoraProgress[item.tag] = { status: 'starting', progress: 0 };
      this.generationService.downloadLora({
        civitai_model_id: item.candidate.civitai_model_id,
        civitai_version_id: item.candidate.civitai_version_id,
        name: item.candidate.name,
        filename: item.candidate.filename,
        download_url: item.candidate.download_url,
        size_bytes: item.candidate.size_bytes,
      }).subscribe({
        next: (resp) => {
          const dlId = resp.download_id;
          if (dlId) {
            this.pollLoraDownload(item.tag, dlId, () => {
              completed++;
              if (completed >= toDownload.length) {
                this.handleAllLorasDownloaded();
              }
            });
          } else {
            this.missingLoraProgress[item.tag] = { status: 'error', progress: 0 };
            completed++;
            if (completed >= toDownload.length) {
              this.handleAllLorasDownloaded();
            }
          }
        },
        error: () => {
          this.missingLoraProgress[item.tag] = { status: 'error', progress: 0 };
          completed++;
          if (completed >= toDownload.length) {
            this.handleAllLorasDownloaded();
          }
        },
      });
    }
  }

  pollLoraDownload(loraTag: string, downloadId: string, onDone: () => void) {
    const interval = setInterval(() => {
      this.generationService.getLoraDownloadStatus(downloadId).subscribe({
        next: (resp) => {
          const status = resp.status || 'unknown';
          const progress = resp.progress || 0;
          this.missingLoraProgress[loraTag] = { status, progress };

          if (status === 'completed' || status === 'not_found') {
            clearInterval(interval);
            onDone();
          } else if (status === 'error' || status === 'failed') {
            clearInterval(interval);
            this.missingLoraProgress[loraTag] = { status: 'error', progress: 0 };
            onDone();
          }
        },
        error: () => {
          clearInterval(interval);
          this.missingLoraProgress[loraTag] = { status: 'error', progress: 0 };
          onDone();
        },
      });
    }, 2000);
  }

  handleAllLorasDownloaded() {
    const allOk = Object.values(this.missingLoraProgress).every(
      p => p.status === 'completed' || p.status === 'not_found'
    );

    if (allOk) {
      this.showToast('LoRAs descargados. Reintentando generación...', 'success');
      this.missingLorasOpen = false;
      this.missingLoras = [];
      this.missingLoraSelections = {};
      this.missingLoraProgress = {};
      this.missingLoraDownloading = false;
      setTimeout(() => this.handleGenerateImage(), 1500);
    } else {
      this.missingLoraDownloading = false;
      this.showToast('Algunos LoRAs no se pudieron descargar', 'error');
    }
  }

  formatSizeMB(bytes: number): string {
    if (!bytes || bytes <= 0) return '';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  }

  getModelThumb(model: any): string {
    const versions = model.modelVersions;
    if (!versions?.length) return '';
    const images = versions[0]?.images;
    if (!images?.length) return '';
    return images[0]?.url || '';
  }

  getTypeColor(type: string): string {
    const colors: Record<string, string> = {
      Checkpoint: '#6366f1',
      LORA: '#f59e0b',
      LoCon: '#f59e0b',
      Controlnet: '#22c55e',
      VAE: '#ec4899',
      TextualInversion: '#8b5cf6',
      Hypernetwork: '#14b8a6',
      Upscaler: '#0ea5e9',
    };
    return colors[type] || '#6b7280';
  }

  formatNumber(n: number | undefined): string {
    if (!n) return '0';
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
    if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
    return String(n);
  }

  formatBytes(bytes: number): string {
    if (!bytes) return '0 B';
    if (bytes >= 1024 * 1024 * 1024) return (bytes / (1024 * 1024 * 1024)).toFixed(1) + ' GB';
    if (bytes >= 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    if (bytes >= 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return bytes + ' B';
  }

  // ─── Image Browser ────────────────────────────────────────────────

  handleBrowseImages(reset = false) {
    if (this.imgBrowseLoaded && !reset) return;
    this.imgBrowseLoading = true;
    if (reset) {
      this.imgBrowseResults = [];
      this.imgBrowseCursor = '';
    }
    this._doBrowseImages(false);
  }

  handleBrowseImagesMore() {
    this.imgBrowseLoading = true;
    this._doBrowseImages(true);
  }

  private _doBrowseImages(append: boolean) {
    const params: Record<string, string | number> = {
      sort: this.imgBrowseSort,
      period: this.imgBrowsePeriod,
      limit: 20,
    };
    if (this.imgBrowseCursor) {
      params['cursor'] = this.imgBrowseCursor;
    }
    this.generationService.browseCivitaiImages(params).subscribe({
      next: (data: any) => {
        const items = data.items || [];
        this.imgBrowseResults = append ? [...this.imgBrowseResults, ...items] : items;
        const meta = data.metadata || {};
        this.imgBrowseCursor = meta.nextCursor ? String(meta.nextCursor) : '';
        this.imgBrowseHasMore = !!meta.nextCursor || !!meta.nextPage;
        this.imgBrowseLoading = false;
        this.imgBrowseLoaded = true;
      },
      error: () => {
        this.imgBrowseLoading = false;
        this.showToast('Error cargando imágenes', 'error');
      },
    });
  }

  handleOpenBrowsedImage(img: any) {
    this.imageMetaOpen = true;
    this.imageMetaLoading = false;
    this.imageMetaData = img;
    this.imageMetaUrl = img.url || '';
  }

  getImageThumbUrl(img: any): string {
    if (!img.url) return '';
    if (img.type === 'video') return img.url;
    return img.url.replace(/width=\d+/, 'width=450').replace('original=true', 'width=450');
  }

  handleVideoHover(event: Event, play: boolean) {
    const el = event.target as HTMLVideoElement;
    if (play) { el.play().catch(() => {}); } else { el.pause(); }
  }

  // ─── Image Meta Detail ─────────────────────────────────────────────

  handleOpenImageMeta(imageUrl: string) {
    this.imageMetaOpen = true;
    this.imageMetaLoading = true;
    this.imageMetaData = null;
    this.imageMetaUrl = imageUrl;

    const version = this.getSelectedVersion();
    if (!version?.id) {
      this.imageMetaLoading = false;
      return;
    }

    const cached = this.versionImagesCache[version.id];
    if (cached) {
      this.imageMetaData = this.findImageByUrl(cached, imageUrl);
      this.imageMetaLoading = false;
      return;
    }

    this.generationService.getCivitaiVersionImages(version.id, 30).subscribe({
      next: (res: any) => {
        const items = res.items || [];
        this.versionImagesCache[version.id] = items;
        this.imageMetaData = this.findImageByUrl(items, imageUrl);
        this.imageMetaLoading = false;
      },
      error: () => {
        this.imageMetaLoading = false;
        this.showToast('Error cargando metadatos', 'error');
      },
    });
  }

  private findImageByUrl(items: any[], targetUrl: string): any | null {
    const targetUuid = this.extractUuidFromUrl(targetUrl);
    if (!targetUuid) return items[0] || null;

    const match = items.find(
      (img: any) => img.url && this.extractUuidFromUrl(img.url) === targetUuid
    );
    return match || items[0] || null;
  }

  private extractUuidFromUrl(url: string): string {
    const parts = url.split('/');
    const uuid = parts.find(p => p.length >= 32 && p.includes('-'));
    return uuid || '';
  }

  getImageResources(): any[] {
    if (!this.imageMetaData?.meta?.resources) return [];
    return this.imageMetaData.meta.resources.filter(
      (r: any) => r.name && r.type
    );
  }

  getResourceColor(type: string): string {
    const t = (type || '').toLowerCase();
    if (t === 'model' || t === 'checkpoint') return '#6366f1';
    if (t === 'lora') return '#f59e0b';
    if (t === 'embed' || t === 'embedding') return '#8b5cf6';
    if (t === 'vae') return '#ec4899';
    return '#6b7280';
  }

  handleCopyToClipboard(text: string) {
    navigator.clipboard.writeText(text).then(
      () => this.showToast('Copiado al portapapeles', 'success'),
      () => this.showToast('Error al copiar', 'error')
    );
  }

  handleUsePrompt(meta: any) {
    if (meta.prompt) {
      this.prompt = meta.prompt;
    }
    if (meta.negativePrompt) {
      this.negativePrompt = meta.negativePrompt;
    }
    // Copy additional parameters if available
    if (meta.sampler || meta.Sampler) {
      this.sampler = meta.sampler || meta.Sampler;
      this.handleSaveSetting('sampler', this.sampler);
    }
    if (meta.steps || meta.Steps) {
      this.steps = parseInt(meta.steps || meta.Steps, 10) || this.steps;
      this.handleSaveSetting('steps', String(this.steps));
    }
    if (meta.cfg || meta.CFG || meta.cfgScale) {
      this.cfg = parseFloat(meta.cfg || meta.CFG || meta.cfgScale) || this.cfg;
      this.handleSaveSetting('cfg', String(this.cfg));
    }
    if (meta.strength || meta.Strength || meta.denoise) {
      this.strength = parseFloat(meta.strength || meta.Strength || meta.denoise) || this.strength;
      this.handleSaveSetting('strength', String(this.strength));
    }
    if (meta.Model || meta.model || meta.checkpoint) {
      const modelName = meta.Model || meta.model || meta.checkpoint;
      // Only set if model exists in available models
      if (this.models.some(m => m.name === modelName)) {
        this.handleModelChange(modelName);
      }
    }
    this.imageMetaOpen = false;
    this.modelDetailOpen = false;
    this.activeTab = 'generate';
    this.showToast('Prompt y parámetros aplicados', 'success');
  }

  // ─── Model helpers ─────────────────────────────────────────────────

  getModelsByType(type: string): Model[] {
    return this.models.filter(m => m.type === type);
  }

  /** Primer checkpoint o diffusion model disponible (respaldo). */
  firstImageModelName(): string {
    const c = this.getModelsByType('checkpoint');
    const d = this.getModelsByType('diffusion_model');
    return c[0]?.name || d[0]?.name || this.lastRealImageModel || this.selectedModel;
  }

  /** Nunca enviar el valor centinela al backend. */
  effectiveImageCheckpoint(): string {
    if (this.selectedModel === this.modelPickAdvanced) {
      return this.lastRealImageModel || this.firstImageModelName();
    }
    return this.selectedModel;
  }

  getSelectedModelType(): string | undefined {
    const found = this.models.find(m => m.name === this.selectedModel);
    return found?.type;
  }

  handleMainImageModelSelectChange(value: string) {
    if (value === this.modelPickAdvanced) {
      this.showAdvanced = true;
      const restore =
        this.lastRealImageModel && this.lastRealImageModel !== this.modelPickAdvanced
          ? this.lastRealImageModel
          : this.firstImageModelName();
      queueMicrotask(() => {
        this.selectedModel = restore;
      });
      setTimeout(() => {
        document.querySelector('.advanced-card')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }, 80);
      return;
    }
    this.handleModelChange(value);
  }

  handleModelChange(name: string) {
    if (name === this.modelPickAdvanced) return;
    this.selectedModel = name;
    const im = this.models.find(
      m => m.name === name && (m.type === 'checkpoint' || m.type === 'diffusion_model')
    );
    if (im) {
      this.lastRealImageModel = name;
    }
    this.handleSaveSetting('checkpoint', name);
  }

  isPrincipalSelectorInventoryCategory(catKey: string): boolean {
    return catKey === 'image_models' || catKey === 'video_models';
  }

  useFavoriteShortcutsForMainModel(): boolean {
    return (this.modelFavoriteEntries || []).length > 0;
  }

  getMainImageModelPickList(): { name: string; display: string }[] {
    const imageModels = this.models.filter(
      m => m.type === 'checkpoint' || m.type === 'diffusion_model'
    );
    const folder = (t: string) => (t === 'diffusion_model' ? 'diffusion_models' : 'checkpoints');
    const entries = this.modelFavoriteEntries || [];
    if (!entries.length) {
      return [];
    }
    const favKey = (fd: string, fn: string) => `${fd}\0${fn}`;
    const favSet = new Set(entries.map((f) => favKey(f.folder, f.filename)));
    const out: { name: string; display: string }[] = [];
    const cur = imageModels.find((m) => m.name === this.selectedModel);
    if (cur && !favSet.has(favKey(folder(cur.type), cur.name))) {
      out.push({ name: cur.name, display: '(actual) ' + cur.name });
    }
    const sorted = [...entries].sort(
      (a, b) => a.sort_order - b.sort_order || a.filename.localeCompare(b.filename)
    );
    for (const f of sorted) {
      const m = imageModels.find((x) => x.name === f.filename && folder(x.type) === f.folder);
      if (m) {
        const disp = (f.label || '').trim() || m.name;
        out.push({ name: m.name, display: disp });
      }
    }
    if (out.length === 0) {
      return imageModels.map((m) => ({ name: m.name, display: m.name }));
    }
    return out;
  }

  handleToggleModelFavorite(item: InventoryItem, checked: boolean) {
    if (checked) {
      const short = (item.civitai_name || item.filename).slice(0, 48);
      this.generationService.putModelFavorite({ folder: item.folder, filename: item.filename, label: short }).subscribe({
        next: () => {
          item.is_favorite = true;
          item.favorite_label = short;
          this.loadModelFavorites();
          this.loadInventory();
        },
        error: () => this.showToast('No se pudo guardar el favorito', 'error'),
      });
    } else {
      this.generationService.deleteModelFavorite(item.folder, item.filename).subscribe({
        next: () => {
          item.is_favorite = false;
          item.favorite_label = undefined;
          this.loadModelFavorites();
          this.loadInventory();
        },
        error: () => this.showToast('No se pudo quitar el favorito', 'error'),
      });
    }
  }

  handleSaveFavoriteLabel(item: InventoryItem, raw: string) {
    if (!item.is_favorite) return;
    const label = (raw || '').trim().slice(0, 200);
    if (label === (item.favorite_label || '').trim()) return;
    this.generationService.putModelFavorite({ folder: item.folder, filename: item.filename, label }).subscribe({
      next: () => {
        item.favorite_label = label || null;
        this.loadModelFavorites();
      },
      error: () => this.showToast('No se pudo guardar la etiqueta', 'error'),
    });
  }

  // ─── NSFW Level Toggles ──────────────────────────────────────────────

  isNsfwBitAllowed(bit: number): boolean {
    return (this.contentMaxBitmask & bit) !== 0;
  }

  hasNsfwBit(bit: number): boolean {
    const level = parseInt(this.civitaiNsfwLevel, 10) || 0;
    return (level & bit) !== 0;
  }

  toggleNsfwBit(bit: number) {
    if (!this.isNsfwBitAllowed(bit)) return;
    let level = parseInt(this.civitaiNsfwLevel, 10) || 0;
    level ^= bit;
    this.civitaiNsfwLevel = String(level);
  }

  toggleLlmContentFilter() {
    if (!this.llmFilterCanToggle) return;
    this.llmContentFilterUserEnabled = !this.llmContentFilterUserEnabled;
  }

  // ─── Utils ─────────────────────────────────────────────────────────────

  showToast(message: string, type: 'success' | 'error') {
    this.toastMessage = message;
    this.toastType = type;
    setTimeout(() => { this.toastMessage = ''; }, 3000);
  }
}
