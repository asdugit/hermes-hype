three.js r170 (npm three@0.170.0), MIT licence (see LICENSE). Files copied unmodified from the npm tarball:

build/three.module.min.js
examples/jsm/postprocessing/{EffectComposer,MaskPass,Pass,RenderPass,ShaderPass,UnrealBloomPass,BokehPass,OutputPass}.js
examples/jsm/shaders/{CopyShader,LuminosityHighPassShader,OutputShader,BokehShader}.js
examples/jsm/loaders/GLTFLoader.js
examples/jsm/utils/BufferGeometryUtils.js

Pages map the bare specifiers with an import map:
  "three" -> ./vendor/three/build/three.module.min.js, "three/addons/" -> ./vendor/three/examples/jsm/
showreel_core/film/page.py copies this folder into a job only when a kit or scene needs THREE.
