"""CABER Building Creation Intelligence service.

Request -> architectural understanding -> three-block specification ->
procedural geometry -> validation -> interactive 3D scene.

The scene is written to the project workspace as ``building.scene.json`` and a
standalone viewer page is emitted so the result can be explored in a browser.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from level5.caber.architect import ArchitecturalArchitect
from level5.caber.geometry import build_scene
from level5.caber.models import BuildingSpec
from level5.caber.validator import ValidationReport, validate
from level5.models import Artifact, Project, ProjectDomain, ProjectStatus, CABERModule
from level5.storage.store import get_store

logger = logging.getLogger("level5.caber.service")


class CABERBuildingService:
    """Builds architectural projects end to end."""

    def __init__(self, architect: ArchitecturalArchitect | None = None) -> None:
        self.architect = architect or ArchitecturalArchitect()
        self.store = get_store()

    async def create_project(
        self, request: str, *, name: str | None = None, preferences: str = ""
    ) -> Project:
        project = Project(
            name=name or _short_name(request),
            original_request=request,
            status=ProjectStatus.PLANNING,
        )
        project.specification.domain = ProjectDomain.ARCHITECTURE_3D
        project.specification.caber_module = CABERModule.BUILDING
        project.specification.intent = request[:200]
        project.specification.deliverable = "Interactive 3D architectural environment"
        project.workspace_path = str(self._workspace(project))
        await self.store.save(project)
        return project

    async def build(self, project: Project, *, preferences: str = "") -> Project:
        project.status = ProjectStatus.EXECUTING
        project.log("phase", "Architectural understanding", phase="understanding")

        spec = await self.architect.design(project.original_request, preferences=preferences)
        project.log(
            "architecture",
            f"Designed {spec.title}: {len(spec.block1.rooms)} rooms",
            rooms=len(spec.block1.rooms),
            objects=len(spec.all_objects),
        )

        scene = build_scene(spec)
        report = validate(spec)

        workspace = Path(project.workspace_path)
        workspace.mkdir(parents=True, exist_ok=True)

        (workspace / "building.spec.json").write_text(
            spec.model_dump_json(indent=2), encoding="utf-8"
        )
        (workspace / "building.scene.json").write_text(
            json.dumps(scene, indent=2), encoding="utf-8"
        )
        (workspace / "validation.json").write_text(
            json.dumps(report.as_dict(), indent=2), encoding="utf-8"
        )
        viewer = workspace / "viewer.html"
        viewer.write_text(_render_viewer(spec, scene), encoding="utf-8")

        project.artifacts = [
            Artifact(name="building.spec.json", kind="document", path="building.spec.json",
                     description="Three-block architectural specification"),
            Artifact(name="building.scene.json", kind="model3d", path="building.scene.json",
                     description=f"{scene['stats']['primitives']} primitives"),
            Artifact(name="viewer.html", kind="preview", path="viewer.html",
                     description="Interactive 3D viewport"),
            Artifact(name="validation.json", kind="test_result", path="validation.json",
                     description=f"Validation score {report.score}"),
        ]
        project.preview_url = f"/api/projects/{project.id}/caber/viewer"
        project.log(
            "validation",
            f"Validation score {report.score}% ({sum(c.passed for c in report.checks)}/{len(report.checks)} checks)",
            passed=report.passed,
        )
        project.status = ProjectStatus.DELIVERED if report.passed else ProjectStatus.REVIEWING
        project.snapshot_workspace("built", note=f"{scene['stats']['primitives']} primitives")
        self._last_spec[project.id] = spec
        self._last_scene[project.id] = scene
        self._last_report[project.id] = report
        await self.store.save(project)
        return project

    # -- accessors used by the API -------------------------------------- #
    _last_spec: dict[str, BuildingSpec] = {}
    _last_scene: dict[str, dict[str, Any]] = {}
    _last_report: dict[str, ValidationReport] = {}

    def scene(self, project_id: str) -> dict[str, Any] | None:
        return self._last_scene.get(project_id)

    def spec(self, project_id: str) -> BuildingSpec | None:
        return self._last_spec.get(project_id)

    def report(self, project_id: str) -> ValidationReport | None:
        return self._last_report.get(project_id)

    def _workspace(self, project: Project) -> Path:
        from level5.config import get_settings

        return get_settings().projects_dir / project.id


def _short_name(request: str) -> str:
    text = request.strip().split("\n")[0][:60]
    return text or "Building project"


def _render_viewer(spec: BuildingSpec, scene: dict[str, Any]) -> str:
    """A self-contained Three.js viewer for the generated scene."""
    payload = json.dumps(scene)
    title = spec.title.replace("<", "&lt;")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title} - CABER 3D viewport</title>
<style>
  html,body{{margin:0;height:100%;background:#0e1116;color:#e6edf3;
    font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;overflow:hidden}}
  #hud{{position:fixed;top:12px;left:12px;padding:10px 14px;background:rgba(16,20,28,.82);
    border:1px solid #2a3341;border-radius:10px;font-size:13px;line-height:1.5;max-width:320px}}
  #hud b{{color:#7dd3fc}}
  #stats{{position:fixed;bottom:12px;left:12px;padding:8px 12px;background:rgba(16,20,28,.82);
    border:1px solid #2a3341;border-radius:10px;font-size:12px;color:#9fb0c3}}
  #err{{position:fixed;inset:0;display:none;place-items:center;padding:40px;text-align:center}}
</style>
</head>
<body>
<div id="hud"><b>{title}</b><br/><span id="meta"></span></div>
<div id="stats"></div>
<div id="err">WebGL is unavailable in this browser context.</div>
<script type="importmap">
{{"imports":{{"three":"https://unpkg.com/three@0.169.0/build/three.module.js",
 "three/addons/":"https://unpkg.com/three@0.169.0/examples/jsm/"}}}}
</script>
<script type="module">
import * as THREE from 'three';
import {{ OrbitControls }} from 'three/addons/controls/OrbitControls.js';
const SCENE = {payload};
try {{
  const renderer = new THREE.WebGLRenderer({{antialias:true}});
  renderer.setPixelRatio(Math.min(devicePixelRatio,2));
  renderer.setSize(innerWidth, innerHeight);
  renderer.shadowMap.enabled = true;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  document.body.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0e1116);
  scene.fog = new THREE.Fog(0x0e1116, 60, 220);
  const b = SCENE.bounds;
  const camera = new THREE.PerspectiveCamera(50, innerWidth/innerHeight, 0.1, 2000);
  camera.position.set(b.center[0]+28, b.center[1]+22, b.center[2]+34);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(b.center[0], b.center[1], b.center[2]);
  controls.enableDamping = true;
  const hemi = new THREE.HemisphereLight(0xbcd4ff, 0x3a3a2f, 0.6); scene.add(hemi);
  for (const l of SCENE.lights) {{
    if (l.kind === 'ambient') {{ scene.add(new THREE.AmbientLight(new THREE.Color(l.color), l.intensity)); }}
    else if (l.kind === 'directional') {{
      const d = new THREE.DirectionalLight(new THREE.Color(l.color), l.intensity);
      d.position.set(l.position[0], l.position[1], l.position[2]);
      d.castShadow = true; d.shadow.mapSize.set(2048,2048);
      d.shadow.camera.left=-80; d.shadow.camera.right=80; d.shadow.camera.top=80; d.shadow.camera.bottom=-80;
      scene.add(d);
    }} else {{
      const p = new THREE.PointLight(new THREE.Color(l.color), l.intensity, 30);
      p.position.set(l.position[0], l.position[1], l.position[2]); scene.add(p);
    }}
  }}
  const root = new THREE.Group(); scene.add(root);
  const boxGeo = new THREE.BoxGeometry(1,1,1);
  for (const p of SCENE.primitives) {{
    const mat = new THREE.MeshStandardMaterial({{
      color: new THREE.Color(p.material.color),
      roughness: p.material.roughness,
      metalness: p.material.metalness,
      transparent: p.material.opacity < 1,
      opacity: p.material.opacity,
    }});
    const mesh = new THREE.Mesh(boxGeo, mat);
    mesh.position.set(p.position[0], p.position[1], p.position[2]);
    mesh.scale.set(p.size[0], p.size[1], p.size[2]);
    mesh.rotation.set(THREE.MathUtils.degToRad(p.rotation[0]),
                      THREE.MathUtils.degToRad(p.rotation[1]),
                      THREE.MathUtils.degToRad(p.rotation[2]));
    mesh.castShadow = p.kind !== 'ground' && p.kind !== 'outdoor';
    mesh.receiveShadow = true;
    mesh.userData = {{id:p.id, name:p.name, kind:p.kind, room_id:p.room_id}};
    root.add(mesh);
  }}
  const raycaster = new THREE.Raycaster(); const pointer = new THREE.Vector2();
  const hud = document.getElementById('meta');
  addEventListener('pointerdown', (e) => {{
    pointer.x = (e.clientX/innerWidth)*2-1; pointer.y = -(e.clientY/innerHeight)*2+1;
    raycaster.setFromCamera(pointer, camera);
    const hit = raycaster.intersectObjects(root.children)[0];
    hud.textContent = hit ? (hit.object.userData.name + ' [' + hit.object.userData.kind + ']') : '';
  }});
  const st = SCENE.stats;
  document.getElementById('stats').textContent =
    st.rooms + ' rooms | ' + st.objects + ' objects | ' + st.primitives + ' primitives | ' + st.floor_area + ' m2';
  addEventListener('resize', () => {{
    camera.aspect = innerWidth/innerHeight; camera.updateProjectionMatrix();
    renderer.setSize(innerWidth, innerHeight);
  }});
  (function loop(){{ requestAnimationFrame(loop); controls.update(); renderer.render(scene, camera); }})();
}} catch (e) {{
  document.getElementById('err').style.display='grid';
  document.getElementById('err').textContent = 'Renderer error: ' + e.message;
}}
</script>
</body>
</html>"""
