import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { Scene } from "./types";

interface Props {
  scene: Scene | null;
  selectedId: string | null;
  onSelect: (primitiveId: string | null, name: string | null) => void;
  mode: "solid" | "wireframe";
}

/**
 * Interactive 3D viewport for CABER building scenes.
 *
 * Renders the generated primitives with PBR materials, shadows and the
 * building's own lighting rig. Clicking a primitive selects it, which drives
 * the object inspector and the natural-language edit box.
 */
export default function Viewport({ scene, selectedId, onSelect, mode }: Props) {
  const mountRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const meshById = useRef<Map<string, THREE.Mesh>>(new Map());
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount || !scene) return;
    let disposed = false;

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(mount.clientWidth, mount.clientHeight);
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.05;
    mount.appendChild(renderer.domElement);
    rendererRef.current = renderer;

    const threeScene = new THREE.Scene();
    threeScene.background = new THREE.Color("#0b0e13");
    const [cx, cy, cz] = scene.bounds.center;
    const span = Math.max(...scene.bounds.size, 10);
    threeScene.fog = new THREE.Fog("#0b0e13", span * 1.5, span * 5);

    const camera = new THREE.PerspectiveCamera(
      50,
      mount.clientWidth / mount.clientHeight,
      0.1,
      5000,
    );
    camera.position.set(cx + span * 0.9, cy + span * 0.7, cz + span * 1.1);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(cx, cy, cz);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.maxPolarAngle = Math.PI / 2.02;

    for (const light of scene.lights) {
      const color = new THREE.Color(light.color);
      if (light.kind === "ambient") {
        threeScene.add(new THREE.AmbientLight(color, light.intensity));
      } else if (light.kind === "directional") {
        const dir = new THREE.DirectionalLight(color, light.intensity);
        dir.position.set(...light.position);
        dir.castShadow = true;
        dir.shadow.mapSize.set(2048, 2048);
        const cam = dir.shadow.camera as THREE.OrthographicCamera;
        cam.left = -span;
        cam.right = span;
        cam.top = span;
        cam.bottom = -span;
        cam.far = span * 4;
        threeScene.add(dir);
      } else {
        const point = new THREE.PointLight(color, light.intensity, span * 3);
        point.position.set(...light.position);
        threeScene.add(point);
      }
    }
    threeScene.add(new THREE.HemisphereLight(0xbcd4ff, 0x3a3a2f, 0.45));

    const root = new THREE.Group();
    threeScene.add(root);
    meshById.current = new Map();
    const boxGeometry = new THREE.BoxGeometry(1, 1, 1);

    for (const primitive of scene.primitives) {
      const material = new THREE.MeshStandardMaterial({
        color: new THREE.Color(primitive.material.color),
        roughness: primitive.material.roughness,
        metalness: primitive.material.metalness,
        transparent: primitive.material.opacity < 1,
        opacity: primitive.material.opacity,
        wireframe: mode === "wireframe",
      });
      const mesh = new THREE.Mesh(boxGeometry, material);
      mesh.position.set(...primitive.position);
      mesh.scale.set(...primitive.size);
      mesh.rotation.set(
        THREE.MathUtils.degToRad(primitive.rotation[0]),
        THREE.MathUtils.degToRad(primitive.rotation[1]),
        THREE.MathUtils.degToRad(primitive.rotation[2]),
      );
      mesh.castShadow = !["ground", "outdoor"].includes(primitive.kind);
      mesh.receiveShadow = true;
      mesh.userData = { id: primitive.id, name: primitive.name, kind: primitive.kind };
      meshById.current.set(primitive.id, mesh);
      root.add(mesh);
    }

    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    const handleClick = (event: MouseEvent) => {
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);
      const hit = raycaster.intersectObjects(root.children)[0];
      if (hit) onSelect(hit.object.userData.id as string, hit.object.userData.name as string);
      else onSelect(null, null);
    };
    renderer.domElement.addEventListener("click", handleClick);

    const handleResize = () => {
      if (!mount) return;
      camera.aspect = mount.clientWidth / mount.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(mount.clientWidth, mount.clientHeight);
    };
    const observer = new ResizeObserver(handleResize);
    observer.observe(mount);

    let frame = 0;
    const animate = () => {
      if (disposed) return;
      frame = requestAnimationFrame(animate);
      controls.update();
      renderer.render(threeScene, camera);
    };
    animate();
    setError(null);

    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
      observer.disconnect();
      renderer.domElement.removeEventListener("click", handleClick);
      controls.dispose();
      boxGeometry.dispose();
      root.children.forEach((child) => {
        const mesh = child as THREE.Mesh;
        (mesh.material as THREE.Material)?.dispose();
      });
      renderer.dispose();
      mount.removeChild(renderer.domElement);
      rendererRef.current = null;
    };
  }, [scene, onSelect, mode]);

  // Highlight the selected primitive without rebuilding the scene.
  useEffect(() => {
    meshById.current.forEach((mesh, id) => {
      const material = mesh.material as THREE.MeshStandardMaterial;
      const original = mesh.userData.baseColor as string | undefined;
      if (id === selectedId) {
        mesh.userData.baseColor = original ?? `#${material.color.getHexString()}`;
        material.emissive = new THREE.Color("#2b6cb0");
        material.emissiveIntensity = 0.6;
      } else if (original) {
        material.emissive = new THREE.Color("#000000");
        material.emissiveIntensity = 0;
      }
    });
  }, [selectedId]);

  if (!scene) {
    return (
      <div className="viewport empty">
        <p>No 3D scene yet. Describe a building to generate one.</p>
      </div>
    );
  }

  return (
    <div className="viewport">
      <div ref={mountRef} className="viewport-canvas" />
      {error && <div className="viewport-error">{error}</div>}
      <div className="viewport-stats">
        {Object.entries(scene.stats)
          .map(([key, value]) => `${key.replace(/_/g, " ")}: ${value}`)
          .join("  |  ")}
      </div>
    </div>
  );
}
