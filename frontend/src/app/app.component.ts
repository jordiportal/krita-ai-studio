import { Component, OnInit, OnDestroy, HostListener } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Subscription } from 'rxjs';
import { GenerationService } from './generation.service';
import { AuthService } from './auth.service';
import {
  Model, GenerationRequest, Settings, ComfyConfig,
  ConnectionTestResult, GalleryItem, CachedModel, ModelTypeOption,
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
        <form (ngSubmit)="handleLogin()">
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
            <label>Prompt</label>
            <textarea
              class="textarea-field"
              [(ngModel)]="prompt"
              placeholder="Describe la imagen que quieres generar..."
              rows="3"
              (keydown.meta.enter)="handleGenerate()"
              (keydown.control.enter)="handleGenerate()">
            </textarea>
          </div>

          <div class="input-group">
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
            <span>{{ generating ? 'Generando...' : 'Generar Imagen' }}</span>
          </button>
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
                <label>Modelo</label>
                <select class="select-field" [(ngModel)]="selectedModel" (ngModelChange)="handleSaveSetting('checkpoint', $event)">
                  <option *ngFor="let model of models" [value]="model.name">{{ model.name }}</option>
                  <option *ngIf="models.length === 0" value="">Cargando...</option>
                </select>
              </div>

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

              <div class="input-group">
                <label>Ancho</label>
                <select class="select-field" [(ngModel)]="width" (ngModelChange)="handleSaveSetting('width', $event)">
                  <option [ngValue]="512">512</option>
                  <option [ngValue]="768">768</option>
                  <option [ngValue]="1024">1024</option>
                  <option [ngValue]="1280">1280</option>
                  <option [ngValue]="1536">1536</option>
                </select>
              </div>

              <div class="input-group">
                <label>Alto</label>
                <select class="select-field" [(ngModel)]="height" (ngModelChange)="handleSaveSetting('height', $event)">
                  <option [ngValue]="512">512</option>
                  <option [ngValue]="768">768</option>
                  <option [ngValue]="1024">1024</option>
                  <option [ngValue]="1280">1280</option>
                  <option [ngValue]="1536">1536</option>
                </select>
              </div>
            </div>
          </div>
        </div>

        <!-- Last result -->
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
              <div class="nsfw-toggles">
                <div class="nsfw-toggle-row">
                  <div class="nsfw-toggle-info">
                    <span class="nsfw-toggle-label">PG</span>
                    <span class="nsfw-toggle-desc">Safe for work</span>
                  </div>
                  <label class="toggle-switch">
                    <input type="checkbox" [checked]="hasNsfwBit(1)" (change)="toggleNsfwBit(1)">
                    <span class="toggle-slider"></span>
                  </label>
                </div>
                <div class="nsfw-toggle-row">
                  <div class="nsfw-toggle-info">
                    <span class="nsfw-toggle-label">PG-13</span>
                    <span class="nsfw-toggle-desc">Ropa sugerente, gore ligero</span>
                  </div>
                  <label class="toggle-switch">
                    <input type="checkbox" [checked]="hasNsfwBit(2)" (change)="toggleNsfwBit(2)">
                    <span class="toggle-slider"></span>
                  </label>
                </div>
                <div class="nsfw-toggle-row">
                  <div class="nsfw-toggle-info">
                    <span class="nsfw-toggle-label">R</span>
                    <span class="nsfw-toggle-desc">Desnudez parcial, situaciones adultas</span>
                  </div>
                  <label class="toggle-switch">
                    <input type="checkbox" [checked]="hasNsfwBit(4)" (change)="toggleNsfwBit(4)">
                    <span class="toggle-slider"></span>
                  </label>
                </div>
                <div class="nsfw-toggle-row">
                  <div class="nsfw-toggle-info">
                    <span class="nsfw-toggle-label">X</span>
                    <span class="nsfw-toggle-desc">Desnudez expl&iacute;cita, contenido adulto</span>
                  </div>
                  <label class="toggle-switch">
                    <input type="checkbox" [checked]="hasNsfwBit(8)" (change)="toggleNsfwBit(8)">
                    <span class="toggle-slider"></span>
                  </label>
                </div>
                <div class="nsfw-toggle-row">
                  <div class="nsfw-toggle-info">
                    <span class="nsfw-toggle-label">XXX</span>
                    <span class="nsfw-toggle-desc">Contenido extremo</span>
                  </div>
                  <label class="toggle-switch">
                    <input type="checkbox" [checked]="hasNsfwBit(16)" (change)="toggleNsfwBit(16)">
                    <span class="toggle-slider"></span>
                  </label>
                </div>
              </div>
            </div>
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
      </ng-container>

      <!-- ============ MODELS TAB ============ -->
      <ng-container *ngIf="activeTab === 'models'">
        <div class="sub-tabs">
          <button class="sub-tab" [class.active]="modelsView === 'search'" (click)="modelsView = 'search'">Modelos</button>
          <button class="sub-tab" [class.active]="modelsView === 'images'" (click)="modelsView = 'images'; handleBrowseImages()">Im&aacute;genes</button>
          <button class="sub-tab" [class.active]="modelsView === 'cache'" (click)="modelsView = 'cache'; loadCache()">
            Descargados
            <span class="sub-tab-badge" *ngIf="cacheItems.length > 0">{{ cacheItems.length }}</span>
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

        <!-- CACHE -->
        <ng-container *ngIf="modelsView === 'cache'">
          <div *ngIf="cacheItems.length === 0 && !cacheLoading" class="empty-gallery">
            <div class="empty-icon">&#128230;</div>
            <p>Sin modelos descargados</p>
            <p class="empty-sub">Busca y descarga modelos de CivitAI</p>
          </div>

          <div *ngIf="cacheLoading && cacheItems.length === 0" class="gallery-loading"><span class="spinner"></span></div>

          <div class="cache-list" *ngIf="cacheItems.length > 0">
            <div class="cache-item" *ngFor="let item of cacheItems">
              <div class="cache-item-info">
                <span class="cache-item-name">{{ item.name }}</span>
                <div class="cache-item-meta">
                  <span class="model-type-badge small" [style.background]="getTypeColor(item.type)">{{ item.type }}</span>
                  <span>{{ formatBytes(item.size_bytes) }}</span>
                </div>
                <div class="cache-progress-bar" *ngIf="item.status === 'downloading'">
                  <div class="cache-progress-fill" [style.width.%]="item.progress"></div>
                </div>
                <span class="cache-item-status" *ngIf="item.status === 'downloading'">
                  {{ item.progress?.toFixed(0) }}% &middot; {{ formatBytes(item.speed || 0) }}/s
                </span>
                <span class="cache-item-status error" *ngIf="item.status === 'error'">Error</span>
              </div>
              <button class="cache-delete-btn" (click)="handleDeleteCacheItem(item.id)"
                      aria-label="Eliminar" *ngIf="item.status !== 'downloading'">&#128465;</button>
            </div>
          </div>
        </ng-container>

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
    .config-actions { display: flex; gap: 12px; margin-bottom: 12px; }
    .config-actions .btn { flex: 1; }
    .connection-result { padding: 12px 16px; border-radius: 10px; font-size: 14px; font-weight: 500; }
    .connection-result.success { background: rgba(34,197,94,0.15); color: var(--success); border: 1px solid rgba(34,197,94,0.3); }
    .connection-result.error { background: rgba(239,68,68,0.15); color: var(--error); border: 1px solid rgba(239,68,68,0.3); }
    .last-result { display: flex; gap: 8px; }
    .last-result-img { flex: 1; width: 100%; border-radius: 12px; cursor: pointer; }
    .last-result-img:active { transform: scale(0.98); }
    .auth-hint { font-size: 13px; color: var(--text-secondary); margin-bottom: 12px; line-height: 1.4; }
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

  modelsView: 'search' | 'images' | 'cache' = 'search';
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

  configHost = '';
  configPort = '8188';
  configSecure = 'false';
  authUser = '';
  authPass = '';
  civitaiApiKey = '';
  civitaiNsfwLevel = '31';
  testingConnection = false;
  savingConfig = false;
  connectionTestResult: ConnectionTestResult | null = null;

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

  private sessionSub?: Subscription;
  private healthInterval?: ReturnType<typeof setInterval>;

  constructor(
    private generationService: GenerationService,
    private authService: AuthService,
  ) {}

  ngOnInit() {
    this.sessionSub = this.authService.sessionExpired$.subscribe(() => {
      this.appState = 'login';
      this.loginError = 'Sesi\u00f3n expirada';
    });
    this.checkAuthAndInit();
  }

  ngOnDestroy() {
    this.sessionSub?.unsubscribe();
    if (this.healthInterval) clearInterval(this.healthInterval);
    if (this.cacheInterval) clearInterval(this.cacheInterval);
  }

  checkAuthAndInit() {
    this.authService.checkStatus().subscribe({
      next: (status) => {
        this.isAuthEnabled = status.auth_enabled;
        if (status.logged_in) {
          this.appState = 'app';
          this.initApp();
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

  private initApp() {
    this.loadConfig();
    this.checkHealth();
    this.loadModels();
    this.loadSamplers();
    this.loadSettings();
    this.loadGallery();
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
        this.appState = 'app';
        this.initApp();
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
    this.authService.logout();
    this.appState = 'login';
    this.loginError = '';
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
        this.civitaiNsfwLevel = cfg.civitai_nsfw_level || '31';
        if (cfg.auth_enabled !== undefined) {
          this.isAuthEnabled = cfg.auth_enabled;
        }
      },
      error: () => {}
    });
  }

  loadModels() {
    this.generationService.getModels().subscribe({
      next: (data) => {
        const checkpoints = data.checkpoints || [];
        this.models = checkpoints.map((item: any) => {
          if (typeof item === 'string') return { name: item, type: 'checkpoint' };
          return { name: item.name || item, type: item.type || 'checkpoint' };
        });
        if (!this.selectedModel && this.models.length > 0) {
          this.selectedModel = this.models[0].name;
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

  loadSettings() {
    this.generationService.getSettings().subscribe({
      next: (s: Settings) => {
        if (s.checkpoint) this.selectedModel = s.checkpoint;
        if (s.sampler !== undefined) this.sampler = s.sampler;
        if (s.steps) this.steps = Number(s.steps) || 0;
        if (s.cfg) this.cfg = Number(s.cfg) || 0;
        if (s.width) this.width = Number(s.width) || 1024;
        if (s.height) this.height = Number(s.height) || 1024;
        if (s.negative_prompt) this.negativePrompt = s.negative_prompt;
        if (s.strength) this.strength = Number(s.strength) || 1.0;
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
      checkpoint: this.selectedModel,
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
    }).subscribe({
      next: (res: any) => {
        this.savingConfig = false;
        if (res?.token) {
          this.authService.setToken(res.token);
        }
        this.isAuthEnabled = !!res?.auth_enabled;
        if (res?.auth_activated) {
          this.showToast('Autenticaci\u00f3n activada', 'success');
        } else {
          this.showToast('Configuraci\u00f3n guardada', 'success');
        }
        this.checkHealth();
        this.loadModels();
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

    this.generating = true;
    this.generatedImages = [];

    const request: GenerationRequest = {
      prompt: this.prompt,
      negative_prompt: this.negativePrompt,
      width: this.width,
      height: this.height,
      steps: this.steps,
      cfg_scale: this.cfg,
      sampler: this.sampler,
      checkpoint: this.selectedModel,
      seed: -1,
      strength: this.strength,
    };

    this.generationService.generateTxt2Img(request).subscribe({
      next: (response) => {
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
    const maxAttempts = 60;
    const interval = setInterval(() => {
      attempts++;
      if (attempts > maxAttempts) {
        clearInterval(interval);
        this.generating = false;
        this.showToast('Tiempo de espera agotado', 'error');
        return;
      }

      this.generationService.getJobStatus(jobId).subscribe({
        next: (status) => {
          if (status.status === 'completed') {
            clearInterval(interval);
            this.generating = false;
            if (status.images && status.images.length > 0) {
              this.generatedImages = status.images.map(img =>
                img.startsWith('data:image') ? img : `data:image/png;base64,${img}`
              );
              this.showToast('Imagen generada!', 'success');
              this.loadGallery();
            } else {
              this.showToast('No se gener\u00f3 ninguna imagen', 'error');
            }
          } else if (status.status === 'error') {
            clearInterval(interval);
            this.generating = false;
            this.showToast('Error: ' + (status.error || 'Generaci\u00f3n fallida'), 'error');
          }
        },
        error: () => {}
      });
    }, 2000);
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
        this.selectedModel = modelName;
        this.handleSaveSetting('checkpoint', modelName);
      }
    }
    this.imageMetaOpen = false;
    this.modelDetailOpen = false;
    this.activeTab = 'generate';
    this.showToast('Prompt y parámetros aplicados', 'success');
  }

  // ─── NSFW Level Toggles ──────────────────────────────────────────────

  hasNsfwBit(bit: number): boolean {
    const level = parseInt(this.civitaiNsfwLevel, 10) || 0;
    return (level & bit) !== 0;
  }

  toggleNsfwBit(bit: number) {
    let level = parseInt(this.civitaiNsfwLevel, 10) || 0;
    level ^= bit;
    this.civitaiNsfwLevel = String(level);
  }

  // ─── Utils ─────────────────────────────────────────────────────────────

  showToast(message: string, type: 'success' | 'error') {
    this.toastMessage = message;
    this.toastType = type;
    setTimeout(() => { this.toastMessage = ''; }, 3000);
  }
}
