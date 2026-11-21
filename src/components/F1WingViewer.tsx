import React, { useCallback, useEffect, useRef, useState } from 'react';
import '@kitware/vtk.js/Rendering/Profiles/Geometry';
import vtkGenericRenderWindow from '@kitware/vtk.js/Rendering/Misc/GenericRenderWindow';
import vtkXMLPolyDataReader from '@kitware/vtk.js/IO/XML/XMLPolyDataReader';
import vtkMapper from '@kitware/vtk.js/Rendering/Core/Mapper';
import vtkActor from '@kitware/vtk.js/Rendering/Core/Actor';
import vtkTubeFilter from '@kitware/vtk.js/Filters/General/TubeFilter';
import vtkColorTransferFunction from '@kitware/vtk.js/Rendering/Core/ColorTransferFunction';
import vtkColorMaps from '@kitware/vtk.js/Rendering/Core/ColorTransferFunction/ColorMaps';
import { ColorMode, ScalarMode } from '@kitware/vtk.js/Rendering/Core/Mapper/Constants';
import vtkOrientationMarkerWidget from '@kitware/vtk.js/Interaction/Widgets/OrientationMarkerWidget';
import vtkAnnotatedCubeActor from '@kitware/vtk.js/Rendering/Core/AnnotatedCubeActor';
import { Box, Wind, Layers, Compass } from 'lucide-react';
import { TRANSLATIONS, type DrsMode, type Lang } from '../i18n';

export interface F1ViewState {
  showWing: boolean;
  showStreams: boolean;
  showSlice: boolean;
  wireframe: boolean;
  streamRadius: number;
  sliceOpacity: number;
}

interface F1WingViewerProps {
  lang: Lang;
  drsMode: DrsMode;
  view: F1ViewState;
}

interface F1SceneHandle {
  genericRW: ReturnType<typeof vtkGenericRenderWindow.newInstance>;
  wingActor: ReturnType<typeof vtkActor.newInstance>;
  wingMapper: ReturnType<typeof vtkMapper.newInstance>;
  streamActor: ReturnType<typeof vtkActor.newInstance>;
  streamMapper: ReturnType<typeof vtkMapper.newInstance>;
  tubeFilter: ReturnType<typeof vtkTubeFilter.newInstance>;
  sliceActor: ReturnType<typeof vtkActor.newInstance>;
  sliceMapper: ReturnType<typeof vtkMapper.newInstance>;
  orientWidget: ReturnType<typeof vtkOrientationMarkerWidget.newInstance> | null;
  dataLoaded: boolean;
}

const CP_GRADIENT =
  'linear-gradient(90deg, #3b4cc0 0%, #7b9ff9 25%, #e2e2e2 50%, #f4987a 75%, #b40426 100%)';
const FLOW_GRADIENT =
  'linear-gradient(90deg, #1b4f9c 0%, #26a9e0 25%, #5fd38d 50%, #f5c342 75%, #c92a2a 100%)';

// Cache parsed VTP buffers in memory so toggling DRS Closed <-> Open is instant!
const bufferCache = new Map<string, ArrayBuffer>();

async function fetchCachedVtp(url: string): Promise<ArrayBuffer> {
  const hit = bufferCache.get(url);
  if (hit) return hit;
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`${url} (${resp.status})`);
  const buf = await resp.arrayBuffer();
  bufferCache.set(url, buf);
  return buf;
}

function parseVtp(buf: ArrayBuffer) {
  const reader = vtkXMLPolyDataReader.newInstance();
  reader.parseAsArrayBuffer(buf);
  return reader.getOutputData(0);
}

export const F1WingViewer: React.FC<F1WingViewerProps> = ({
  lang,
  drsMode,
  view,
}) => {
  const t = TRANSLATIONS[lang];
  const langRef = useRef<Lang>(lang);
  langRef.current = lang;
  const containerRef = useRef<HTMLDivElement | null>(null);
  const sceneRef = useRef<F1SceneHandle | null>(null);
  const viewRef = useRef<F1ViewState>(view);
  viewRef.current = view;
  const hasSetInitialCam = useRef(false);

  const [status, setStatus] = useState<string>(t.loading);

  const applyView = useCallback((scene: F1SceneHandle, v: F1ViewState) => {
    if (!scene.dataLoaded) return;
    scene.wingActor.setVisibility(v.showWing);
    scene.wingActor.getProperty().setRepresentation(v.wireframe ? 1 : 2);

    scene.tubeFilter.setRadius(v.streamRadius);
    scene.streamActor.setVisibility(v.showStreams);

    scene.sliceActor.setVisibility(v.showSlice);
    scene.sliceActor.getProperty().setOpacity(v.sliceOpacity);

    scene.genericRW.getRenderWindow().render();
  }, []);

  const setCameraPreset = useCallback((preset: 'iso' | 'wake' | 'side' | 'top') => {
    const scene = sceneRef.current;
    if (!scene) return;
    const renderer = scene.genericRW.getRenderer();
    const camera = renderer.getActiveCamera();
    // Wing center is around x=0.35, y=0.0, z=0.14
    camera.setFocalPoint(0.32, 0.0, 0.14);
    if (preset === 'wake') {
      camera.setPosition(2.45, 0.25, 0.42);
      camera.setViewUp(0, 0, 1);
    } else if (preset === 'side') {
      camera.setPosition(0.35, -2.05, 0.16);
      camera.setViewUp(0, 0, 1);
    } else if (preset === 'top') {
      camera.setPosition(0.35, 0.0, 2.35);
      camera.setViewUp(0, 1, 0);
    } else {
      camera.setPosition(-1.35, -1.55, 0.88);
      camera.setViewUp(0, 0, 1);
    }
    renderer.resetCameraClippingRange();
    scene.genericRW.getRenderWindow().render();
  }, []);

  // 1. Initialize VTK.js WebGL window once
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    let disposed = false;

    const genericRW = vtkGenericRenderWindow.newInstance({
      background: [0.032, 0.038, 0.056],
    });
    genericRW.setContainer(el);
    genericRW.resize();

    const renderer = genericRW.getRenderer();
    const interactor = genericRW.getInteractor();

    // LUT 1: Wing surface Pressure Coefficient Cp (-2.0 .. +1.0, Cool to Warm)
    const cpLut = vtkColorTransferFunction.newInstance();
    cpLut.applyColorMap(vtkColorMaps.getPresetByName('Cool to Warm'));
    cpLut.setMappingRange(-2.0, 1.0);
    cpLut.updateRange();

    // LUT 2: Streamlines & Velocity Slice |U| (15 .. 105 m/s, Rainbow Desaturated)
    const flowLut = vtkColorTransferFunction.newInstance();
    flowLut.applyColorMap(
      vtkColorMaps.getPresetByName('Rainbow Desaturated') ||
        vtkColorMaps.getPresetByName('Cool to Warm')
    );
    flowLut.setMappingRange(15.0, 105.0);
    flowLut.updateRange();

    // Actor 1: Full-span 3D F1 Rear Wing colored by Cp
    const wingMapper = vtkMapper.newInstance();
    wingMapper.setLookupTable(cpLut);
    wingMapper.setColorMode(ColorMode.MAP_SCALARS);
    wingMapper.setScalarMode(ScalarMode.USE_POINT_FIELD_DATA);
    wingMapper.setColorByArrayName('Cp');
    wingMapper.setScalarRange(-2.0, 1.0);
    wingMapper.setScalarVisibility(true);

    const wingActor = vtkActor.newInstance();
    wingActor.setMapper(wingMapper);
    wingActor.setVisibility(false);
    wingActor.getProperty().setAmbient(0.28);
    wingActor.getProperty().setDiffuse(0.72);
    wingActor.getProperty().setSpecular(0.32);
    wingActor.getProperty().setSpecularPower(30);
    renderer.addActor(wingActor);

    // Actor 2: 3D Streamline Tubes colored by |U|
    const tubeFilter = vtkTubeFilter.newInstance({
      radius: 0.004,
      numberOfSides: 6,
      capping: false,
    });
    const streamMapper = vtkMapper.newInstance();
    streamMapper.setInputConnection(tubeFilter.getOutputPort());
    streamMapper.setLookupTable(flowLut);
    streamMapper.setColorMode(ColorMode.MAP_SCALARS);
    streamMapper.setScalarMode(ScalarMode.USE_POINT_FIELD_DATA);
    streamMapper.setColorByArrayName('U_mag');
    streamMapper.setScalarRange(15.0, 105.0);
    streamMapper.setScalarVisibility(true);

    const streamActor = vtkActor.newInstance();
    streamActor.setMapper(streamMapper);
    streamActor.setVisibility(false);
    streamActor.getProperty().setAmbient(0.35);
    streamActor.getProperty().setDiffuse(0.65);
    streamActor.getProperty().setSpecular(0.2);
    streamActor.getProperty().setOpacity(0.92);
    renderer.addActor(streamActor);

    // Actor 3: Centerline Velocity Slice (y ~ 0)
    const sliceMapper = vtkMapper.newInstance();
    sliceMapper.setLookupTable(flowLut);
    sliceMapper.setColorMode(ColorMode.MAP_SCALARS);
    sliceMapper.setScalarMode(ScalarMode.USE_POINT_FIELD_DATA);
    sliceMapper.setColorByArrayName('U_mag');
    sliceMapper.setScalarRange(15.0, 105.0);
    sliceMapper.setScalarVisibility(true);

    const sliceActor = vtkActor.newInstance();
    sliceActor.setMapper(sliceMapper);
    sliceActor.setVisibility(false);
    sliceActor.getProperty().setOpacity(0.45);
    renderer.addActor(sliceActor);

    renderer.resetCamera();
    genericRW.getRenderWindow().render();

    // Orientation marker cube
    let orientWidget: ReturnType<typeof vtkOrientationMarkerWidget.newInstance> | null =
      null;
    try {
      const cube = vtkAnnotatedCubeActor.newInstance();
      cube.setDefaultStyle({
        text: '+X',
        fontStyle: 'bold',
        fontFamily: 'Inter, system-ui, sans-serif',
        fontColor: '#f8fafc',
        fontSizeScale: (res: number) => res / 2.2,
        faceColor: '#151924',
        edgeThickness: 0.12,
        edgeColor: '#00d2be',
        resolution: 256,
      });
      cube.setXPlusFaceProperty({ text: 'AFT' });
      cube.setXMinusFaceProperty({ text: 'FWD' });
      cube.setYPlusFaceProperty({ text: 'L' });
      cube.setYMinusFaceProperty({ text: 'R' });
      cube.setZPlusFaceProperty({ text: 'TOP' });
      cube.setZMinusFaceProperty({ text: 'BOT' });

      orientWidget = vtkOrientationMarkerWidget.newInstance({
        actor: cube,
        interactor,
        parentRenderer: renderer,
        viewportCorner: vtkOrientationMarkerWidget.Corners.BOTTOM_RIGHT,
        viewportSize: 0.15,
        minPixelSize: 76,
        maxPixelSize: 118,
      });
      orientWidget.setEnabled(true);
    } catch {
      orientWidget = null;
    }

    sceneRef.current = {
      genericRW,
      wingActor,
      wingMapper,
      streamActor,
      streamMapper,
      tubeFilter,
      sliceActor,
      sliceMapper,
      orientWidget,
      dataLoaded: false,
    };

    const ro = new ResizeObserver(() => {
      if (!disposed) genericRW.resize();
    });
    ro.observe(el);

    return () => {
      disposed = true;
      ro.disconnect();
      if (orientWidget) {
        try {
          orientWidget.setEnabled(false);
          orientWidget.delete();
        } catch {
          // ignore
        }
      }
      try {
        genericRW.delete();
      } catch {
        // ignore
      }
      sceneRef.current = null;
    };
  }, []);

  // 2. Load DRS Closed / Open OpenFOAM .vtp files
  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene) return;
    let cancelled = false;

    const loadMode = async () => {
      setStatus(TRANSLATIONS[langRef.current].loading);
      try {
        const [wingBuf, streamBuf, sliceBuf] = await Promise.all([
          fetchCachedVtp(`/data/${drsMode}_wing.vtp`),
          fetchCachedVtp(`/data/${drsMode}_streamlines.vtp`),
          fetchCachedVtp(`/data/${drsMode}_slice.vtp`),
        ]);
        if (cancelled || !sceneRef.current) return;

        const wingPoly = parseVtp(wingBuf);
        const streamPoly = parseVtp(streamBuf);
        const slicePoly = parseVtp(sliceBuf);

        const s = sceneRef.current;
        s.wingMapper.setInputData(wingPoly);
        s.tubeFilter.setInputData(streamPoly);
        s.sliceMapper.setInputData(slicePoly);
        s.dataLoaded = true;

        applyView(s, viewRef.current);
        if (!hasSetInitialCam.current) {
          setCameraPreset('iso');
          hasSetInitialCam.current = true;
        }
        setStatus('');
      } catch (err) {
        if (!cancelled) {
          setStatus(`${TRANSLATIONS[langRef.current].errorPrefix}${(err as Error).message}`);
        }
      }
    };

    loadMode();
    return () => {
      cancelled = true;
    };
  }, [drsMode, applyView, setCameraPreset]);

  // 3. Live layer toggles
  useEffect(() => {
    if (sceneRef.current?.dataLoaded) {
      applyView(sceneRef.current, view);
    }
  }, [view, applyView]);

  return (
    <div className="viewer-shell">
      <div ref={containerRef} className="vtk-canvas" />

      <div className="viewer-toolbar">
        <button type="button" onClick={() => setCameraPreset('iso')}>
          <Box size={14} /> {t.camIso}
        </button>
        <button type="button" onClick={() => setCameraPreset('wake')}>
          <Wind size={14} /> {t.camWake}
        </button>
        <button type="button" onClick={() => setCameraPreset('side')}>
          <Layers size={14} /> {t.camSide}
        </button>
        <button type="button" onClick={() => setCameraPreset('top')}>
          <Compass size={14} /> {t.camTop}
        </button>
      </div>

      <div className="colorbars-stack">
        {view.showWing && (
          <div className="colorbar-card">
            <div className="colorbar-header">
              <span>{t.colorbarWing}</span>
              <span className="colorbar-unit">Cp</span>
            </div>
            <div className="colorbar-strip" style={{ background: CP_GRADIENT }} />
            <div className="colorbar-ticks">
              <span>{t.colorbarSuction}</span>
              <span>-0.5</span>
              <span>{t.colorbarStag}</span>
            </div>
          </div>
        )}
        {(view.showStreams || view.showSlice) && (
          <div className="colorbar-card">
            <div className="colorbar-header">
              <span>{t.colorbarFlow}</span>
              <span className="colorbar-unit">m/s</span>
            </div>
            <div className="colorbar-strip" style={{ background: FLOW_GRADIENT }} />
            <div className="colorbar-ticks">
              <span>15</span>
              <span>60</span>
              <span>105</span>
            </div>
          </div>
        )}
      </div>

      <div className="viewer-hint">{t.hint}</div>

      {status && (
        <div className="viewer-overlay">
          <div className="spinner-card">
            <div className="spinner" />
            <div>{status}</div>
          </div>
        </div>
      )}
    </div>
  );
};
