import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClientModule } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { GenerationService } from './generation.service';
import { ComfyStatus, Model, GenerationRequest, Settings } from './types';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, HttpClientModule, FormsModule],
  providers: [GenerationService],
  template: `
    <div class="app-container">
      <header class="header">
        <h1>Krita AI</h1>
        <div class="status" [class.online]="comfyOnline" [class.offline]="!comfyOnline">
          <span class="status-indicator"></span>
          <span>{{ comfyOnline ? 'Online' : 'Offline' }}</span>
        </div>
      </header>

      <!-- Main controls (like Krita plugin) -->
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

      <!-- Advanced options (collapsible) -->
      <div class="card advanced-card">
        <button
          class="advanced-toggle"
          (click)="handleToggleAdvanced()"
          aria-label="Toggle advanced options"
          [attr.aria-expanded]="showAdvanced">
          <span class="advanced-toggle-icon" [class.open]="showAdvanced">&#9654;</span>
          Opciones avanzadas
        </button>

        <div *ngIf="showAdvanced" class="advanced-body">
          <div class="input-group">
            <label>Negative Prompt</label>
            <textarea
              class="textarea-field"
              [(ngModel)]="negativePrompt"
              placeholder="Lo que NO quieres en la imagen (vacío = auto según modelo)..."
              rows="2">
            </textarea>
          </div>

          <div class="settings-grid">
            <div class="input-group">
              <label>Modelo</label>
              <select class="select-field" [(ngModel)]="selectedModel" (ngModelChange)="handleSaveSetting('checkpoint', $event)">
                <option *ngFor="let model of models" [value]="model.name">
                  {{ model.name }}
                </option>
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

      <!-- Results -->
      <div class="card" *ngIf="generatedImages.length > 0">
        <h2 class="card-title">Resultados</h2>
        <div class="gallery">
          <div
            class="gallery-item"
            *ngFor="let img of generatedImages; let i = index"
            (click)="handleDownload(img)">
            <img [src]="img" [alt]="'Generated ' + i">
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
      display: flex;
      align-items: center;
      gap: 8px;
      width: 100%;
      background: none;
      border: none;
      color: var(--text-secondary);
      font-size: 14px;
      font-weight: 500;
      cursor: pointer;
      padding: 4px 0;
      font-family: inherit;
    }
    .advanced-toggle:hover { color: var(--text-primary); }
    .advanced-toggle-icon {
      display: inline-block;
      font-size: 10px;
      transition: transform 0.2s;
    }
    .advanced-toggle-icon.open { transform: rotate(90deg); }
    .advanced-body {
      margin-top: 16px;
      animation: fadeIn 0.15s ease;
    }
    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(-4px); }
      to { opacity: 1; transform: translateY(0); }
    }
  `]
})
export class AppComponent implements OnInit {
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

  toastMessage = '';
  toastType: 'success' | 'error' = 'success';

  constructor(private generationService: GenerationService) {}

  ngOnInit() {
    this.checkHealth();
    this.loadModels();
    this.loadSamplers();
    this.loadSettings();

    setInterval(() => this.checkHealth(), 30000);
  }

  checkHealth() {
    this.generationService.getHealth().subscribe({
      next: (status) => { this.comfyOnline = status.comfyui === 'ok'; },
      error: () => { this.comfyOnline = false; }
    });
  }

  loadModels() {
    this.generationService.getModels().subscribe({
      next: (data) => {
        const checkpoints = data.checkpoints || [];
        this.models = checkpoints.map((item: any) => {
          if (typeof item === 'string') {
            return { name: item, type: 'checkpoint' };
          }
          return { name: item.name || item, type: item.type || 'checkpoint' };
        });
        if (!this.selectedModel && this.models.length > 0) {
          this.selectedModel = this.models[0].name;
        }
      },
      error: () => { this.showToast('Error cargando modelos', 'error'); }
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
        if (s.sampler) this.sampler = s.sampler;
        if (s.scheduler) { /* reserved for future use */ }
        if (s.steps) this.steps = Number(s.steps) || 0;
        if (s.cfg) this.cfg = Number(s.cfg) || 0;
        if (s.width) this.width = Number(s.width) || 1024;
        if (s.height) this.height = Number(s.height) || 1024;
        if (s.negative_prompt) this.negativePrompt = s.negative_prompt;
        if (s.strength) this.strength = Number(s.strength) || 1.0;
      },
      error: () => { /* use defaults */ }
    });
  }

  handleSaveSetting(key: string, value: any) {
    this.generationService.saveSettings({ [key]: value }).subscribe();
  }

  handleToggleAdvanced() {
    this.showAdvanced = !this.showAdvanced;
  }

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
        this.showToast('Generación iniciada', 'success');
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
            } else {
              this.showToast('No se generó ninguna imagen', 'error');
            }
          } else if (status.status === 'error') {
            clearInterval(interval);
            this.generating = false;
            this.showToast('Error: ' + (status.error || 'Generación fallida'), 'error');
          }
        },
        error: () => { /* keep polling */ }
      });
    }, 2000);
  }

  handleDownload(img: string) {
    const link = document.createElement('a');
    link.href = img;
    link.download = `krita-ai-${Date.now()}.png`;
    link.click();
  }

  showToast(message: string, type: 'success' | 'error') {
    this.toastMessage = message;
    this.toastType = type;
    setTimeout(() => { this.toastMessage = ''; }, 3000);
  }
}
