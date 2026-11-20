import React, { useEffect, useState } from 'react';
import {
  ArrowDown,
  Cpu,
  Eye,
  Flame,
  Gauge,
  Globe,
  TrendingUp,
  Wind,
  Zap,
} from 'lucide-react';
import { F1WingViewer, type F1ViewState } from './components/F1WingViewer';
import { detectInitialLang, TRANSLATIONS, type DrsMode, type Lang } from './i18n';

interface ModeAero {
  Cl_downforce: number;
  Cd_drag: number;
  L_over_D: number;
  downforce_N: number;
  downforce_kgf: number;
  drag_N: number;
  speed_kmh: number;
  n_cells: number;
  iterations: number;
}

interface AeroSummary {
  drs_closed: ModeAero;
  drs_open: ModeAero;
  drs_effect: {
    drag_reduction_pct: number;
    downforce_reduction_pct: number;
    drag_saved_N: number;
  };
}

export const App: React.FC = () => {
  const [lang, setLang] = useState<Lang>(detectInitialLang);
  const [drsMode, setDrsMode] = useState<DrsMode>('drs_closed');
  const [speedKmh, setSpeedKmh] = useState<number>(252);
  const [summary, setSummary] = useState<AeroSummary | null>(null);
  const [view, setView] = useState<F1ViewState>({
    showWing: true,
    showStreams: true,
    showSlice: false,
    wireframe: false,
    streamRadius: 0.004,
    sliceOpacity: 0.45,
  });

  const t = TRANSLATIONS[lang];

  useEffect(() => {
    document.title = t.pageTitle;
    document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en';
    try {
      localStorage.setItem('f1wing_lang', lang);
    } catch {
      // ignore
    }
  }, [lang, t.pageTitle]);

  useEffect(() => {
    fetch('/data/aero_summary.json')
      .then((r) => r.json())
      .then((d: AeroSummary) => setSummary(d))
      .catch(() => {});
  }, []);

  const active = summary ? summary[drsMode] : null;
  // High-Re incompressible dynamic-pressure scaling: F(v) = F(252 km/h) * (v / 252)^2
  const speedScale = active ? Math.pow(speedKmh / active.speed_kmh, 2) : 1;
  const downforceN = active ? active.downforce_N * speedScale : 0;
  const downforceKgf = downforceN / 9.81;
  const dragN = active ? active.drag_N * speedScale : 0;

  return (
    <div className="app-layout">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-top">
            <div className="brand-badge">{t.badge}</div>
            <button
              type="button"
              className="lang-toggle"
              onClick={() => setLang((p) => (p === 'zh' ? 'en' : 'zh'))}
            >
              <Globe size={12} />
              <span>{lang === 'zh' ? 'EN' : '中文'}</span>
            </button>
          </div>
          <h1>{t.title}</h1>
          <p>{t.subtitle}</p>
        </div>

        {/* Section 1: DRS Mode Toggle */}
        <section className="panel-section">
          <div className="section-title">
            <Zap size={14} /> {t.sectionDrs}
          </div>
          <div className="drs-grid">
            <button
              type="button"
              className={`drs-btn closed ${drsMode === 'drs_closed' ? 'active' : ''}`}
              onClick={() => setDrsMode('drs_closed')}
            >
              <strong>{t.drsClosed}</strong>
              <span>{t.drsClosedSub}</span>
            </button>
            <button
              type="button"
              className={`drs-btn open ${drsMode === 'drs_open' ? 'active' : ''}`}
              onClick={() => setDrsMode('drs_open')}
            >
              <strong>{t.drsOpen}</strong>
              <span>{t.drsOpenSub}</span>
            </button>
          </div>

          {summary && (
            <div className="drs-delta-box">
              <div className="drs-delta-title">{t.drsGainTitle} @ {speedKmh} km/h</div>
              <div className="drs-delta-row">
                <span>{t.dragReduction}</span>
                <span className="good">
                  -{summary.drs_effect.drag_reduction_pct.toFixed(1)}% (
                  -{(summary.drs_effect.drag_saved_N * speedScale).toFixed(0)} N)
                </span>
              </div>
              <div className="drs-delta-row">
                <span>{t.downforceChange}</span>
                <span className="warn">
                  -{summary.drs_effect.downforce_reduction_pct.toFixed(1)}%
                </span>
              </div>
            </div>
          )}
        </section>

        {/* Section 2: Albert Park Speed Scaling */}
        <section className="panel-section">
          <div className="section-title">
            <Gauge size={14} /> {t.sectionSpeed}
          </div>
          <label className="slider-row">
            <div className="slider-header">
              <span>{t.speedLabel}</span>
              <strong>
                {speedKmh} km/h ({(speedKmh / 3.6).toFixed(1)} m/s)
              </strong>
            </div>
            <input
              type="range"
              min={100}
              max={330}
              step={5}
              value={speedKmh}
              onChange={(e) => setSpeedKmh(Number(e.target.value))}
            />
          </label>
          <div className="corner-pills">
            {[
              { v: 110, label: t.corners.hairpin, drs: 'drs_closed' as DrsMode },
              { v: 252, label: t.corners.chicane, drs: 'drs_closed' as DrsMode },
              { v: 325, label: t.corners.straight, drs: 'drs_open' as DrsMode },
            ].map((c) => (
              <button
                key={c.v}
                type="button"
                className={`corner-pill ${speedKmh === c.v ? 'active' : ''}`}
                onClick={() => {
                  setSpeedKmh(c.v);
                  setDrsMode(c.drs);
                }}
              >
                {c.label}
              </button>
            ))}
          </div>
        </section>

        {/* Section 3: 3D Visualization Controls */}
        <section className="panel-section">
          <div className="section-title">
            <Eye size={14} /> {t.sectionVisual}
          </div>
          <div className="toggle-grid">
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={view.showWing}
                onChange={(e) => setView({ ...view, showWing: e.target.checked })}
              />
              <span>{t.showWing}</span>
            </label>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={view.showStreams}
                onChange={(e) => setView({ ...view, showStreams: e.target.checked })}
              />
              <span>{t.showStreams}</span>
            </label>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={view.showSlice}
                onChange={(e) => setView({ ...view, showSlice: e.target.checked })}
              />
              <span>{t.showSlice}</span>
            </label>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={view.wireframe}
                onChange={(e) => setView({ ...view, wireframe: e.target.checked })}
              />
              <span>{t.wireframe}</span>
            </label>
          </div>

          <label className="slider-row">
            <div className="slider-header">
              <span>{t.streamRadius}</span>
              <strong>{(view.streamRadius * 1000).toFixed(1)} mm</strong>
            </div>
            <input
              type="range"
              min={0.002}
              max={0.009}
              step={0.0005}
              value={view.streamRadius}
              onChange={(e) =>
                setView({ ...view, streamRadius: Number(e.target.value) })
              }
            />
          </label>

          {view.showSlice && (
            <label className="slider-row">
              <div className="slider-header">
                <span>{t.sliceOpacity}</span>
                <strong>{Math.round(view.sliceOpacity * 100)}%</strong>
              </div>
              <input
                type="range"
                min={0.15}
                max={0.95}
                step={0.05}
                value={view.sliceOpacity}
                onChange={(e) =>
                  setView({ ...view, sliceOpacity: Number(e.target.value) })
                }
              />
            </label>
          )}
        </section>

        <div className="sidebar-footer">
          <Flame size={13} />
          <span>{t.footerNote}</span>
        </div>
      </aside>

      <main className="workspace">
        <header className="kpi-bar">
          <div className="kpi-card">
            <div className="kpi-label">
              <ArrowDown size={14} /> {t.kpiDownforce}
            </div>
            <div className="kpi-value cyan">
              {active ? `${downforceKgf.toFixed(0)} kgf (${downforceN.toFixed(0)} N)` : '--'}
            </div>
          </div>
          <div className="kpi-card">
            <div className="kpi-label">
              <Wind size={14} /> {t.kpiDrag}
            </div>
            <div className="kpi-value orange">
              {active ? `${dragN.toFixed(0)} N` : '--'}
            </div>
          </div>
          <div className="kpi-card">
            <div className="kpi-label">
              <Gauge size={14} /> {t.kpiClCd}
            </div>
            <div className="kpi-value">
              {active
                ? `CL ${active.Cl_downforce.toFixed(2)} / CD ${active.Cd_drag.toFixed(2)}`
                : '--'}
            </div>
          </div>
          <div className="kpi-card">
            <div className="kpi-label">
              <TrendingUp size={14} /> {t.kpiEfficiency}
            </div>
            <div className="kpi-value">
              {active ? `${active.L_over_D.toFixed(2)} : 1` : '--'}
            </div>
          </div>
          <div className="kpi-card">
            <div className="kpi-label">
              <Cpu size={14} /> {t.kpiMesh}
            </div>
            <div className="kpi-value">
              {active ? `${(active.n_cells * 2).toLocaleString()} hex` : '--'}
            </div>
          </div>
        </header>

        <div className="viewer-wrapper">
          <F1WingViewer lang={lang} drsMode={drsMode} view={view} />
        </div>
      </main>
    </div>
  );
};
