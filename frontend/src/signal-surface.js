// RSSI is a graph height over XY; antenna Z stays a separate physical coordinate.
export function signalHeight(dbm,amplitude=5,range=[-100,-20]){return .08+Math.max(0,Math.min(1,(dbm-range[0])/(range[1]-range[0])))*amplitude;}

export function signalSurface(cells,step=1,amplitude=5,objects=[],range=[-100,-20]){
 const finite=cells.filter(c=>Number.isFinite(c.mean_dbm)&&c.position_m.every(Number.isFinite));
 if(!finite.length)return {positions:[],colors:[],samples:[],triangles:0};
 const z=finite[0].position_m[2],rows=finite.filter(c=>Math.abs(c.position_m[2]-z)<.01);
 const xmin=Math.min(...rows.map(c=>c.position_m[0])),ymin=Math.min(...rows.map(c=>c.position_m[1]));
 const grid=new Map();
 for(const c of rows){const x=Math.round((c.position_m[0]-xmin)/step),y=Math.round((c.position_m[1]-ymin)/step);
  if(Math.abs(c.position_m[0]-xmin-x*step)<1e-4&&Math.abs(c.position_m[1]-ymin-y*step)<1e-4)grid.set(x+','+y,{cell:c,x,y});}
 const obstacles=objects.filter(o=>o.center[2]-o.size[2]/2<z&&o.center[2]+o.size[2]/2>z);
 function blocked(a,b){
  for(const o of obstacles){
   const c=Math.cos(o.yaw_rad),s=Math.sin(o.yaw_rad),local=p=>[c*(p[0]-o.center[0])+s*(p[1]-o.center[1]),-s*(p[0]-o.center[0])+c*(p[1]-o.center[1])],p=local(a),q=local(b);
   // Segment/rectangle intersection, including thin walls between grid vertices.
   let lo=0,hi=1;for(let axis=0;axis<2;axis++){const d=q[axis]-p[axis],half=o.size[axis]/2;
    if(Math.abs(d)<1e-10){if(Math.abs(p[axis])>half){lo=2;break;}}
    else{const t1=(-half-p[axis])/d,t2=(half-p[axis])/d;lo=Math.max(lo,Math.min(t1,t2));hi=Math.min(hi,Math.max(t1,t2));}}
   if(lo<=hi)return true;
  }return false;
 }
 const positions=[],colors=[],samples=[];
 function add(triangle){if(triangle.some(c=>!c))return;const a=triangle.map(r=>r.cell);
  if(a.some((c,i)=>blocked(c.position_m,a[(i+1)%3].position_m)))return;
  for(const c of a){positions.push(c.position_m[0],c.position_m[1],signalHeight(c.mean_dbm,amplitude,range));colors.push(Math.max(0,Math.min(1,(c.mean_dbm-range[0])/(range[1]-range[0]))));samples.push(c);}}
 for(const {x,y} of grid.values()){
  const corners=[[x,y],[x+1,y],[x+1,y+1],[x,y+1]].map(([a,b])=>grid.get(a+','+b));
  if(corners.filter(Boolean).length===3)add(corners.filter(Boolean));
  else{add([corners[0],corners[1],corners[2]]);add([corners[0],corners[2],corners[3]]);}
 }
 return {positions,colors,samples,triangles:positions.length/9,antenna_z_m:z};
}
