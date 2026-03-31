import { Component, OnInit, HostListener } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClientModule } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { GenerationService } from './generation.service';
import {
  Model, GenerationRequest, Settings, ComfyConfig,
  ConnectionTestResult, GalleryItem,
} from './types';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, HttpClientModule, FormsModule],
  providers: [GenerationService],
  template: `
    <div class="app-container" [class.has-bottom-nav]="true">
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

          <h2 class="card-title" style="margin-top: 8px;">Autenticaci&oacute;n (Basic Auth)</h2>
          <p class="auth-hint">Protege el acceso a esta app. D&eacute;jalo vac&iacute;o para acceso libre.</p>

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
export class AppComponent implements OnInit {
  activeTab: 'generate' | 'gallery' | 'config' = 'generate';
  comfyOnline = false;

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

  constructor(private generationService: GenerationService) {}

  ngOnInit() {
    this.loadConfig();
    this.checkHealth();
    this.loadModels();
    this.loadSamplers();
    this.loadSettings();
    this.loadGallery();

    setInterval(() => this.checkHealth(), 30000);
  }

  @HostListener('document:keydown', ['$event'])
  handleKeyboard(e: KeyboardEvent) {
    if (!this.viewerOpen) return;
    if (e.key === 'Escape') this.handleCloseViewer();
    if (e.key === 'ArrowLeft') this.handleViewerPrev(e);
    if (e.key === 'ArrowRight') this.handleViewerNext(e);
  }

  handleSwitchTab(tab: 'generate' | 'gallery' | 'config') {
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
      next: (cfg: ComfyConfig) => {
        this.configHost = cfg.comfyui_host || '';
        this.configPort = cfg.comfyui_port || '8188';
        this.configSecure = cfg.comfyui_secure || 'false';
        this.authUser = cfg.auth_user || '';
        this.authPass = cfg.auth_pass || '';
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
    return this.generationService.getGalleryImageUrl(imgId);
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
    }).subscribe({
      next: () => {
        this.savingConfig = false;
        this.showToast('Configuraci\u00f3n guardada', 'success');
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

  // ─── Utils ─────────────────────────────────────────────────────────────

  showToast(message: string, type: 'success' | 'error') {
    this.toastMessage = message;
    this.toastType = type;
    setTimeout(() => { this.toastMessage = ''; }, 3000);
  }
}
