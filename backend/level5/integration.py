"""Cross-intelligence integration: an application that consumes a CABER building.

Milestone 6 requires the three CABER intelligences to work through one platform,
not as three disconnected applications. This module implements the first real
handoff: Intelligence A (Application Creation) builds a viewer web application
around the scene produced by Intelligence C (Building Creation).

The handoff is deliberate and verifiable:

1.  Intelligence C builds a building project (spec -> geometry -> validation ->
    scene) and writes ``building.scene.json`` and ``building.spec.json``.
2.  Intelligence A reads that *real* artifact from the building project's
    workspace, copies it into its own, and generates a self-contained viewer app
    whose page loads the scene data from a sibling JSON file.
3.  The generated app is built and its output served through the normal web
    preview path.

Nothing is simulated: if the upstream building has no scene, the handoff fails
loudly rather than emitting a placeholder, and the generated app is only marked
built once its real build has run.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from level5.caber.service import CABERBuildingService
from level5.config import get_settings
from level5.models import (
    Artifact,
    CABERModule,
    Project,
    ProjectDomain,
    ProjectStatus,
    TestResult,
)
from level5.preview import build_web_app, static_preview_dir
from level5.storage.store import get_store

logger = logging.getLogger("level5.integration")

# Source artifacts the app consumes, and the names they take in the app workspace.
_SCENE_SOURCE = "building.scene.json"
_SPEC_SOURCE = "building.spec.json"


class HandoffError(RuntimeError):
    """The upstream building could not supply a scene for the application."""


def _scene_artifact(project: Project) -> Path | None:
    workspace = Path(project.workspace_path)
    candidate = workspace / _SCENE_SOURCE
    return candidate if candidate.is_file() else None


async def ensure_building_project(
    request: str, *, name: str | None = None
) -> Project:
    """Return a building project for ``request``, building one if none matches.

    Reuses an already-delivered building whose request matches, so a repeated
    handoff does not spend model budget rebuilding an identical building.
    """
    store = get_store()
    for row in await store.list(limit=200):
        if row.get("caber_module") != CABERModule.BUILDING.value:
            continue
        existing = await store.get(row["id"])
        if existing is None:
            continue
        if (
            existing.original_request.strip() == request.strip()
            and _scene_artifact(existing) is not None
        ):
            return existing
    service = CABERBuildingService()
    project = await service.create_project(request, name=name)
    return await service.build(project)


async def create_building_viewer_app(
    building_project_id: str, *, name: str | None = None
) -> Project:
    """Create an application project that renders a CABER building's scene.

    The new project is Intelligence A (module A); the building is Intelligence C
    (module C). The app copies the building's real scene artifact and generates a
    viewer that loads it, so the two intelligences are linked by data, not by a
    claim.
    """
    store = get_store()
    building = await store.get(building_project_id)
    if building is None:
        raise HandoffError(f"building project {building_project_id} not found")
    if building.specification.caber_module != CABERModule.BUILDING:
        raise HandoffError(f"project {building_project_id} is not a building project")

    app = Project(
        name=name or f"{building.name} — 3D viewer app",
        original_request=(
            f"Build a web application that displays the building "
            f"'{building.name}' in an interactive 3D viewport"
        ),
    )
    app.workspace_path = str(get_settings().projects_dir / app.id)
    await apply_building_viewer(app, building)
    await store.save(app)
    return app


async def apply_building_viewer(app: Project, building: Project) -> Project:
    """Populate ``app`` as a viewer for ``building`` and run its real build.

    Kept separate from project creation so the command-box pipeline can reuse the
    project it already created rather than spawning a second one.
    """
    scene_path = _scene_artifact(building)
    if scene_path is None:
        raise HandoffError(
            f"building {building.id} has no {_SCENE_SOURCE}; build it first"
        )
    scene = json.loads(scene_path.read_text(encoding="utf-8"))
    spec_path = Path(building.workspace_path) / _SPEC_SOURCE

    app.specification.domain = ProjectDomain.WEB_APP
    app.specification.caber_module = CABERModule.APPLICATION
    app.specification.intent = "Render an existing CABER building in a web application"
    app.specification.deliverable = "Interactive 3D building viewer web application"
    workspace = Path(app.workspace_path)
    workspace.mkdir(parents=True, exist_ok=True)

    # Copy the real upstream artifacts so the app is self-contained and the
    # lineage is visible in the workspace.
    shutil.copyfile(scene_path, workspace / _SCENE_SOURCE)
    if spec_path.is_file():
        shutil.copyfile(spec_path, workspace / _SPEC_SOURCE)

    _write_app(workspace, app, building, scene)

    app.artifacts.append(
        Artifact(
            name="web/index.html",
            kind="file",
            path="web/index.html",
            size_bytes=(workspace / "web" / "index.html").stat().st_size,
            description="Viewer application entry point",
        )
    )
    app.artifacts.append(
        Artifact(
            name=_SCENE_SOURCE,
            kind="model3d",
            path=_SCENE_SOURCE,
            size_bytes=scene_path.stat().st_size,
            description=f"Scene handed off from building {building.id}",
        )
    )
    app.log(
        "handoff",
        f"Received scene from building {building.id} "
        f"({scene.get('stats', {}).get('primitives', '?')} primitives)",
        source_project=building.id,
        module_from="C",
        module_to="A",
    )

    _run_build(app)
    return app


def _run_build(app: Project) -> None:
    """Run the generated app's real build and record the true outcome."""
    result = build_web_app(app.workspace_path)
    app.tests.append(
        TestResult(
            suite="build",
            name="npm run build (viewer app)",
            status="passed" if result.succeeded else "failed",
            message=result.output[-1500:],
        )
    )
    if not result.succeeded:
        app.status = ProjectStatus.FAILED
        app.log("build_failed", f"Viewer app build failed: {result.output[-400:]}")
        return
    app.log("build", "Viewer app built", dist_dir=result.dist_dir)
    dist = static_preview_dir(app.workspace_path)
    if dist is not None:
        app.preview_url = f"/api/projects/{app.id}/preview/"
        app.artifacts.append(
            Artifact(
                name="web/dist",
                kind="preview",
                path=str(Path(dist).relative_to(app.workspace_path)),
                description="Built viewer application",
            )
        )
    app.status = ProjectStatus.DELIVERED
    app.snapshot("delivered", note="Building viewer application built")


def _write_app(
    workspace: Path, app: Project, building: Project, scene: dict
) -> None:
    app_dir = workspace / "web"
    app_dir.mkdir(parents=True, exist_ok=True)
    title = str(scene.get("title") or building.name)
    stats = scene.get("stats", {})
    (app_dir / "package.json").write_text(
        json.dumps(
            {
                "name": "caber-building-viewer",
                "private": True,
                "version": "1.0.0",
                "type": "module",
                "scripts": {
                    "build": "node build.mjs",
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (app_dir / "index.html").write_text(
        _index_html(title, stats, building.id), encoding="utf-8"
    )
    (app_dir / "viewer.js").write_text(_viewer_js(), encoding="utf-8")
    # A dependency-free build step that validates the scene and stages the site.
    (app_dir / "build.mjs").write_text(_build_mjs(), encoding="utf-8")


def _index_html(title: str, stats: dict, building_id: str) -> str:
    safe_title = title.replace("<", "&lt;")
    room_count = stats.get("rooms", "?")
    primitive_count = stats.get("primitives", "?")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{safe_title} — 3D viewer</title>
<style>
  :root{{color-scheme:dark}}
  html,body{{margin:0;height:100%;background:#0b0f14;color:#e6edf3;
    font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif}}
  header{{position:fixed;top:0;left:0;right:0;padding:12px 18px;
    background:linear-gradient(180deg,rgba(11,15,20,.92),rgba(11,15,20,0));
    pointer-events:none}}
  h1{{margin:0;font-size:16px;font-weight:600}}
  p{{margin:4px 0 0;font-size:12px;color:#9fb0c3}}
  #viewport{{position:fixed;inset:0}}
  #status{{position:fixed;bottom:12px;left:18px;font-size:12px;color:#9fb0c3}}
  #error{{position:fixed;inset:0;display:none;place-items:center;padding:40px;text-align:center}}
</style>
</head>
<body>
<header>
  <h1>{safe_title}</h1>
  <p id="meta">{room_count} rooms · {primitive_count} primitives · source building {building_id}</p>
</header>
<div id="viewport"></div>
<div id="status">loading scene…</div>
<div id="error">WebGL is unavailable in this browser context.</div>
<script type="importmap">
{{"imports":{{"three":"https://unpkg.com/three@0.169.0/build/three.module.js",
 "three/addons/":"https://unpkg.com/three@0.169.0/examples/jsm/"}}}}
</script>
<script type="module" src="./viewer.js"></script>
</body>
</html>
"""


def _viewer_js() -> str:
    return """import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const statusEl = document.getElementById('status');
try {
  const scene = await fetch('./building.scene.json').then((r) => r.json());
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setSize(innerWidth, innerHeight);
  renderer.shadowMap.enabled = true;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  document.getElementById('viewport').appendChild(renderer.domElement);

  const three = new THREE.Scene();
  three.background = new THREE.Color('#0b0f14');
  const camera = new THREE.PerspectiveCamera(55, innerWidth / innerHeight, 0.1, 5000);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;

  for (const prim of scene.primitives) {
    const geo = new THREE.BoxGeometry(prim.size[0], prim.size[1], prim.size[2]);
    const mat = new THREE.MeshStandardMaterial({
      color: prim.material?.color || '#cccccc',
      roughness: prim.material?.roughness ?? 0.8,
      metalness: prim.material?.metalness ?? 0.0,
      transparent: (prim.material?.opacity ?? 1) < 1,
      opacity: prim.material?.opacity ?? 1,
    });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.set(prim.position[0], prim.position[1], prim.position[2]);
    mesh.rotation.set(prim.rotation[0], prim.rotation[1], prim.rotation[2]);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    three.add(mesh);
  }
  for (const light of scene.lights || []) {
    if (light.kind === 'ambient') {
      three.add(new THREE.AmbientLight(light.color, light.intensity));
    } else {
      const dl = new THREE.DirectionalLight(light.color || '#ffffff', light.intensity);
      dl.position.set(light.position[0], light.position[1], light.position[2]);
      dl.castShadow = true;
      three.add(dl);
    }
  }

  const size = new THREE.Vector3(...scene.bounds.size);
  const center = new THREE.Vector3(...scene.bounds.center);
  const radius = Math.max(size.x, size.y, size.z);
  camera.position.set(center.x + radius, center.y + radius, center.z + radius);
  controls.target.copy(center);
  controls.update();

  addEventListener('resize', () => {
    camera.aspect = innerWidth / innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(innerWidth, innerHeight);
  });

  renderer.setAnimationLoop(() => {
    controls.update();
    renderer.render(three, camera);
  });
  statusEl.textContent =
    scene.primitives.length + ' primitives · ' + (scene.lights || []).length + ' lights';
} catch (err) {
  statusEl.textContent = 'scene failed to load: ' + err;
  document.getElementById('error').style.display = 'grid';
}
"""


def _build_mjs() -> str:
    """A dependency-free build: validate the scene and stage the static site."""
    return """import { mkdir, copyFile, readFile, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';

const out = 'dist';
await mkdir(out, { recursive: true });

const scene = JSON.parse(await readFile('../building.scene.json', 'utf8'));
if (!Array.isArray(scene.primitives) || scene.primitives.length === 0) {
  throw new Error('scene has no primitives');
}
for (const prim of scene.primitives) {
  if (!Array.isArray(prim.size) || prim.size.some((s) => !(s > 0))) {
    throw new Error('primitive with non-positive size: ' + prim.id);
  }
}

for (const file of ['index.html', 'viewer.js']) {
  await copyFile(file, join(out, file));
}
await copyFile('../building.scene.json', join(out, 'building.scene.json'));

const meta = {
  title: scene.title,
  primitives: scene.primitives.length,
  lights: (scene.lights || []).length,
  rooms: scene.stats?.rooms ?? null,
};
await writeFile(join(out, 'build-info.json'), JSON.stringify(meta, null, 2));
console.log('viewer built:', meta.primitives, 'primitives,', meta.lights, 'lights');
"""
