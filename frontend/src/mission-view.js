import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {STLLoader} from 'three/addons/loaders/STLLoader.js';
import {ColladaLoader} from 'three/addons/loaders/ColladaLoader.js';
import {signalSurface} from './signal-surface.js';

export class MissionView{
 constructor(element){
  this.element=element;this.scene=new THREE.Scene();this.scene.background=new THREE.Color('#e9eee7');
  this.camera=new THREE.PerspectiveCamera(42,1,.05,1000);this.camera.up.set(0,0,1);
  this.renderer=new THREE.WebGLRenderer({antialias:true,preserveDrawingBuffer:true});this.renderer.setPixelRatio(Math.min(devicePixelRatio,2));
  element.appendChild(this.renderer.domElement);this.orbit=new OrbitControls(this.camera,this.renderer.domElement);this.orbit.enableDamping=true;
  this.scene.add(new THREE.HemisphereLight(0xffffff,0x748675,2.4));const sun=new THREE.DirectionalLight(0xffffff,3);sun.position.set(-8,-12,20);this.scene.add(sun);
  this.world=new THREE.Group();this.scene.add(this.world);this.robot=new THREE.Group();this.scene.add(this.robot);
  this.rx=new THREE.Group();this.robot.add(this.rx);this.rx.add(new THREE.Mesh(new THREE.SphereGeometry(.12,14,10),new THREE.MeshStandardMaterial({color:0x3aada1,emissive:0x136558})));
  const antenna=new THREE.Mesh(new THREE.CylinderGeometry(.015,.015,.48,8),new THREE.MeshStandardMaterial({color:0x222c2a}));antenna.rotation.x=Math.PI/2;antenna.position.z=-.2;this.rx.add(antenna);
  this.tx=new THREE.Group();this.scene.add(this.tx);this.tx.add(new THREE.Mesh(new THREE.SphereGeometry(.18,16,12),new THREE.MeshStandardMaterial({color:0xe77b40})));
  this.overlay=new THREE.Group();this.scene.add(this.overlay);this.meshes=[];this.walls=[];this.key=null;
  this.surfaceMesh=null;this.surfaceStats=null;this.surfaceAmplitude=5;
  this.tip=document.createElement('div');this.tip.className='signal-tip';this.tip.hidden=true;element.appendChild(this.tip);
  const ray=new THREE.Raycaster();this.renderer.domElement.addEventListener('pointermove',event=>{
   if(!this.surfaceMesh){this.tip.hidden=true;return;}const rect=element.getBoundingClientRect();
   ray.setFromCamera(new THREE.Vector2((event.clientX-rect.left)/rect.width*2-1,1-(event.clientY-rect.top)/rect.height*2),this.camera);
   const hit=ray.intersectObject(this.surfaceMesh)[0];this.tip.hidden=!hit;if(!hit)return;
   const samples=this.surfaceMesh.userData.samples.slice(hit.faceIndex*3,hit.faceIndex*3+3);
   const cell=samples.reduce((a,b)=>Math.hypot(a.position_m[0]-hit.point.x,a.position_m[1]-hit.point.y)<Math.hypot(b.position_m[0]-hit.point.x,b.position_m[1]-hit.point.y)?a:b);
   this.tip.textContent=`RSSI ${cell.mean_dbm.toFixed(1)} dBm · X ${cell.position_m[0].toFixed(1)} / Y ${cell.position_m[1].toFixed(1)} m · антена Z ${cell.position_m[2].toFixed(2)} m`;
  });this.renderer.domElement.addEventListener('pointerleave',()=>{this.tip.hidden=true;});
  const grid=new THREE.GridHelper(40,40,0x91a58d,0xcbd6c6);grid.rotation.x=Math.PI/2;grid.position.z=.005;this.scene.add(grid);
  this.dirty=true;this.orbit.addEventListener('change',()=>{this.dirty=true;});
  new ResizeObserver(()=>{const r=element.getBoundingClientRect();this.camera.aspect=r.width/Math.max(1,r.height);this.camera.updateProjectionMatrix();this.renderer.setSize(r.width,r.height);this.dirty=true;}).observe(element);
  this.renderer.setAnimationLoop(()=>{this.orbit.update();if(this.dirty){this.renderer.render(this.scene,this.camera);this.dirty=false;}});
 }
 async loadAssets(){
  for(const mesh of this.meshes)this.robot.remove(mesh);this.meshes=[];
  const response=await fetch('/assets/husky/model.json');if(!response.ok)throw Error('Офіційна модель Husky ще готується');
  this.manifest=await response.json();const loader=new STLLoader();
  const visuals=new Map();for(const item of this.manifest.meshes){if(!visuals.has(item.file)){
    const visual=item.file.endsWith('.dae')?(await new ColladaLoader().loadAsync('/assets/husky/'+item.file)).scene:
      new THREE.Mesh(await loader.loadAsync('/assets/husky/'+item.file),new THREE.MeshStandardMaterial({color:new THREE.Color(...item.color),roughness:.72}));
    visuals.set(item.file,visual);
   }
   const mesh=visuals.get(item.file).clone(true);
   mesh.position.fromArray(item.position);mesh.quaternion.fromArray(item.quaternion_xyzw);mesh.scale.fromArray(item.scale);
   mesh.userData={...item,restQuaternion:mesh.quaternion.clone()};this.meshes.push(mesh);this.robot.add(mesh);
  }return this.manifest;
 }
 setScene(scenario){
  const key=JSON.stringify([scenario.objects,scenario.tx,scenario.rx.mount_position,scenario.rx.mount_orientation_rad,scenario.robot]);if(key===this.key)return;
  this.key=key;this.scenario=scenario;this.clear(this.world);this.clear(this.overlay);this.surfaceMesh=null;this.surfaceStats=null;this.walls=[];
  for(const obj of scenario.objects){const floor=obj.center[2]+obj.size[2]/2<=.01;
   const geometry=new THREE.BoxGeometry(...obj.size);const material=new THREE.MeshStandardMaterial({color:floor?'#cad7bf':obj.material==='metal'?'#819397':'#b8b5a6',transparent:!floor,opacity:floor?1:.36,depthWrite:floor,roughness:.8});
   const mesh=new THREE.Mesh(geometry,material);mesh.position.fromArray(obj.center);mesh.rotation.z=obj.yaw_rad;
   mesh.add(new THREE.LineSegments(new THREE.EdgesGeometry(geometry),new THREE.LineBasicMaterial({color:'#8b9983',transparent:true,opacity:.55})));this.world.add(mesh);if(!floor)this.walls.push(mesh);
  }
  this.tx.position.fromArray(scenario.tx.position);this.rx.position.fromArray(scenario.rx.mount_position);
  this.world.add(this.label('Tx · база',scenario.tx.position,'#e77b40'));
  for(const obj of scenario.objects){if(obj.center[2]+obj.size[2]/2<=.01)continue;
   this.world.add(this.label(obj.label,[obj.center[0],obj.center[1],obj.center[2]+obj.size[2]/2+.4],'#526657'));}
  this.rx.quaternion.setFromEuler(new THREE.Euler(scenario.rx.mount_orientation_rad[2],scenario.rx.mount_orientation_rad[1],scenario.rx.mount_orientation_rad[0],'ZYX'));
  this.setPose({position:scenario.robot.position,quaternion_xyzw:new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,0,1),scenario.robot.yaw_rad).toArray()});
  this.fit();
 }
 fit(top=false){
  if(!this.scenario)return;const box=new THREE.Box3();
  for(const obj of this.scenario.objects){if(obj.center[2]+obj.size[2]/2<=.01)continue;box.expandByPoint(new THREE.Vector3(obj.center[0]-obj.size[0]/2,obj.center[1]-obj.size[1]/2,0));box.expandByPoint(new THREE.Vector3(obj.center[0]+obj.size[0]/2,obj.center[1]+obj.size[1]/2,obj.size[2]));}
  box.expandByPoint(new THREE.Vector3(...this.scenario.tx.position));box.expandByPoint(new THREE.Vector3(...this.scenario.robot.position));
  if(this.surfaceMesh)box.expandByObject(this.surfaceMesh);
  if(box.isEmpty()){box.min.set(-5,-5,0);box.max.set(5,5,3);}const center=box.getCenter(new THREE.Vector3()),size=box.getSize(new THREE.Vector3());const d=Math.max(7,size.x,size.y)*1.3;
  this.orbit.target.copy(center);this.camera.position.copy(center).add(top?new THREE.Vector3(0,-.001,d*1.65):new THREE.Vector3(d*.8,-d,d));this.orbit.update();
 }
 setPose(pose){if(!pose)return;this.dirty=true;this.robot.position.fromArray(pose.position);this.robot.quaternion.fromArray(pose.quaternion_xyzw);
  for(const mesh of this.meshes){const angle=pose.joint_positions?.[mesh.userData.joint_name];if(angle!==undefined)mesh.quaternion.copy(mesh.userData.restQuaternion).multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(...mesh.userData.joint_axis),angle));}
 }
 setTransparent(value){this.dirty=true;for(const mesh of this.walls){mesh.material.opacity=value?.36:1;mesh.material.depthWrite=!value;}}
 clear(group){group.traverse(obj=>{if(obj.isInstancedMesh)obj.dispose();obj.geometry?.dispose();if(obj.material){for(const m of Array.isArray(obj.material)?obj.material:[obj.material]){m.map?.dispose();m.dispose();}}});group.clear();}
 line(points,color,width=1){if(points.length<2)return;const geometry=new THREE.BufferGeometry().setFromPoints(points.map(p=>new THREE.Vector3(p[0],p[1],.035)));this.overlay.add(new THREE.Line(geometry,new THREE.LineBasicMaterial({color,linewidth:width})));}
 update(data,layer='observations',step=1){
  const hadSurface=Boolean(this.surfaceMesh);this.dirty=true;this.setPose(data.pose||data.poses?.at(-1));this.clear(this.overlay);this.surfaceMesh=null;this.surfaceStats=null;this.tip.hidden=true;
  this.line((data.poses||[]).map(p=>p.position),0x1c755f);if(data.target)this.line(data.target.path||[],0xea8a34);
  const observations=data.observations||[];
  if(observations.length){const geometry=new THREE.BufferGeometry().setFromPoints(observations.map(o=>new THREE.Vector3(o.position_m[0],o.position_m[1],.06)));
   geometry.setAttribute('color',new THREE.Float32BufferAttribute(observations.flatMap(o=>new THREE.Color().setHSL(Math.max(0,Math.min(1,((o.rssi_dbm??-110)+100)/80))*.34,.7,.42).toArray()),3));
   this.overlay.add(new THREE.Points(geometry,new THREE.PointsMaterial({size:.12,vertexColors:true})));}
  const heat=layer.startsWith('reference')?data.reference:data.map;
  if((layer==='height'||layer==='reference-height')&&heat?.cells?.length){
   const surface=signalSurface(heat.cells,step,this.surfaceAmplitude,this.scenario?.objects||[]);
   if(surface.triangles){const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(surface.positions,3));geometry.setAttribute('color',new THREE.Float32BufferAttribute(surface.colors.flatMap(t=>new THREE.Color().setHSL(t*.34,.65,.52).toArray()),3));
    this.surfaceMesh=new THREE.Mesh(geometry,new THREE.MeshBasicMaterial({vertexColors:true,transparent:true,opacity:.62,depthWrite:false,side:THREE.DoubleSide}));this.surfaceMesh.userData.samples=surface.samples;this.overlay.add(this.surfaceMesh);
    const wire=new THREE.WireframeGeometry(geometry);this.overlay.add(new THREE.LineSegments(wire,new THREE.LineBasicMaterial({color:0x284e3f,transparent:true,opacity:.1,depthWrite:false})));
    this.surfaceStats={triangles:surface.triangles,minimum_height:Math.min(...surface.positions.filter((v,i)=>i%3===2)),maximum_height:Math.max(...surface.positions.filter((v,i)=>i%3===2)),antenna_z_m:surface.antenna_z_m,source:layer==='reference-height'?'reference':'prediction',observation_count:heat.observation_count};
    if(!hadSurface)this.fit();
   }
  }else if(layer!=='observations'&&heat?.cells?.length){const cells=heat.cells.filter(c=>c.mean_dbm!==null&&(layer!=='std'||c.std_db!=null));const mesh=new THREE.InstancedMesh(new THREE.PlaneGeometry(step*.95,step*.95),new THREE.MeshBasicMaterial({transparent:true,opacity:.5,depthWrite:false,side:THREE.DoubleSide}),cells.length);
   const matrix=new THREE.Matrix4();for(let i=0;i<cells.length;i++){const c=cells[i];matrix.makeTranslation(c.position_m[0],c.position_m[1],.025);mesh.setMatrixAt(i,matrix);const value=layer==='std'?c.std_db:layer==='lower'?c.lower_dbm:c.mean_dbm;const t=Math.max(0,Math.min(1,layer==='std'?(value??0)/30:((value??-110)+100)/80));mesh.setColorAt(i,new THREE.Color().setHSL((layer==='std'?1-t:t)*.34,.65,.52));}this.overlay.add(mesh);}
  if(data.shadowGoal){const ring=new THREE.Mesh(new THREE.TorusGeometry(.4,.04,8,32),new THREE.MeshBasicMaterial({color:0x4582b3}));ring.position.set(...data.shadowGoal,.06);this.overlay.add(ring);this.overlay.add(this.label('Ціль радіотіні',[...data.shadowGoal,1.5],'#397194'));}
  if(data.target){const marker=new THREE.Mesh(new THREE.TorusGeometry(.25,.035,8,32),new THREE.MeshBasicMaterial({color:0xec942d}));marker.position.set(data.target.base[0],data.target.base[1],.08);this.overlay.add(marker);}
  const last=observations.at(-1);if(last&&this.scenario){const geometry=new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(...this.scenario.tx.position),new THREE.Vector3(...last.position_m)]);this.overlay.add(new THREE.Line(geometry,new THREE.LineDashedMaterial({color:last.line_of_sight===false?0xcd5d4e:0x54a77e,dashSize:.18,gapSize:.12})));this.overlay.children.at(-1).computeLineDistances();}
 }
 receiverPosition(){return this.rx.getWorldPosition(new THREE.Vector3()).toArray();}
 label(text,point,color){const canvas=document.createElement('canvas');canvas.width=512;canvas.height=64;const ctx=canvas.getContext('2d');ctx.fillStyle='#fafbf7e8';ctx.fillRect(0,0,512,64);ctx.fillStyle=color;ctx.font='28px sans-serif';ctx.textAlign='center';ctx.fillText(text,256,43);const texture=new THREE.CanvasTexture(canvas);const sprite=new THREE.Sprite(new THREE.SpriteMaterial({map:texture,depthTest:false}));sprite.position.fromArray(point);sprite.scale.set(3.4,.425,1);return sprite;}
}
