export type Lang = 'zh' | 'en';
export type DrsMode = 'drs_closed' | 'drs_open';

export function detectInitialLang(): Lang {
  try {
    const saved = localStorage.getItem('f1wing_lang');
    if (saved === 'zh' || saved === 'en') return saved;
  } catch {
    // Ignore storage issues
  }
  if (typeof navigator !== 'undefined' && navigator.language) {
    return navigator.language.toLowerCase().startsWith('zh') ? 'zh' : 'en';
  }
  return 'zh';
}

export const TRANSLATIONS = {
  zh: {
    pageTitle: 'Albert Park F1 Wing CFD — 墨尔本 F1 尾翼 3D 气动实验室',
    badge: '墨尔本 Albert Park GP · OpenFOAM v2512',
    title: 'F1 Rear Wing CFD',
    subtitle: '多段式尾翼下压力、DRS 减阻与 3D 翼尖涡流线仿真',
    sectionDrs: 'DRS 空气动力学模式',
    drsClosed: 'DRS 关闭 (高下压力)',
    drsClosedSub: '弯道模式 · 42° 襟翼',
    drsOpen: 'DRS 开启 (直道超车)',
    drsOpenSub: '减阻模式 · 8° 襟翼',
    drsGainTitle: 'DRS 实测气动收益',
    dragReduction: '风阻降低',
    downforceChange: '下压力变化',
    sectionSpeed: '阿尔伯特公园赛道车速换算',
    speedLabel: '模拟车速 v',
    corners: {
      hairpin: 'T3 慢弯 (110 km/h)',
      chicane: 'T9/10 高速 S 弯 (252 km/h)',
      straight: '发车大直道 (325 km/h)',
    },
    sectionVisual: 'VTK.js 3D 流场图层',
    showWing: '3D 尾翼表面压力 Cp',
    showStreams: '3D 气动流线与翼尖涡',
    showSlice: '中轴线速度截面',
    wireframe: '尾翼网格线框',
    streamRadius: '流线管径',
    sliceOpacity: '截面透明度',
    footerNote: '基于真实 OpenFOAM snappyHexMesh + simpleFoam (k-ω SST) 求解',
    kpiDownforce: '全翼下压力 (Downforce)',
    kpiDrag: '总气动阻力 (Drag)',
    kpiClCd: '气动系数 CL / CD',
    kpiEfficiency: '气动效率 L/D',
    kpiMesh: '3D 网格规模 (全翼等效)',
    camIso: '3D 赛场视角',
    camWake: '尾流翼尖涡',
    camSide: '侧面翼型 XZ',
    camTop: '俯视图 XY',
    colorbarWing: '翼面压力系数 Cp',
    colorbarFlow: '流线/截面流速 |U|',
    hint: '左键 360° 旋转 · 滚轮缩放 · Shift+左键平移',
    loading: '正在加载 OpenFOAM 3D 尾翼与流线 (.vtp)...',
    errorPrefix: '加载失败：',
  },
  en: {
    pageTitle: 'Albert Park F1 Wing CFD — 3D Aerodynamics & Streamlines Lab',
    badge: 'Melbourne Albert Park GP · OpenFOAM v2512',
    title: 'F1 Rear Wing CFD',
    subtitle: 'Multi-Element Downforce, DRS Drag Reduction & 3D Wingtip Vortices',
    sectionDrs: 'DRS Aerodynamic Mode',
    drsClosed: 'DRS CLOSED (High Downforce)',
    drsClosedSub: 'Cornering · 42° Flap',
    drsOpen: 'DRS OPEN (Overtaking)',
    drsOpenSub: 'Low Drag · 8° Flap',
    drsGainTitle: 'Measured DRS Aero Delta',
    dragReduction: 'Drag Reduction',
    downforceChange: 'Downforce Delta',
    sectionSpeed: 'Albert Park Circuit Speed Scaling',
    speedLabel: 'Vehicle Speed v',
    corners: {
      hairpin: 'T3 Hairpin (110 km/h)',
      chicane: 'T9/10 Chicane (252 km/h)',
      straight: 'Pit Straight (325 km/h)',
    },
    sectionVisual: 'VTK.js 3D Visualization Layers',
    showWing: '3D Wing Surface Cp',
    showStreams: '3D Streamlines & Vortices',
    showSlice: 'Centerline Velocity Slice',
    wireframe: 'Surface Wireframe',
    streamRadius: 'Streamline Radius',
    sliceOpacity: 'Slice Opacity',
    footerNote: 'Solved with OpenFOAM v2512 snappyHexMesh + simpleFoam (k-ω SST)',
    kpiDownforce: 'Full-Wing Downforce',
    kpiDrag: 'Total Aero Drag',
    kpiClCd: 'Aero Coeffs CL / CD',
    kpiEfficiency: 'Aero Efficiency L/D',
    kpiMesh: '3D Mesh Scale (Full Span)',
    camIso: '3D Pit-Wall',
    camWake: 'Rear Vortices',
    camSide: 'Side Airfoil XZ',
    camTop: 'Top View XY',
    colorbarWing: 'Wing Surface Pressure Cp',
    colorbarFlow: 'Streamline Velocity |U|',
    hint: 'Drag: 360° Orbit · Scroll: Zoom · Shift+Drag: Pan',
    loading: 'Loading OpenFOAM 3D Wing & Streamlines (.vtp)...',
    errorPrefix: 'Load error: ',
  },
} as const;
